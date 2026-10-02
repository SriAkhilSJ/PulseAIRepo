"""One-shot prompt templates — stateless quick jobs OUTSIDE the conversation.

The express counter (agent oneshot parity):
a template + variables -> ONE provider call -> ONE result. Deliberately
never touches session history, the transcript, or the prompt cache — a
one-shot must not cost the user a cache break or pollute the thread.

Registry contract: every template is a PURE function ``dict -> (system,
user)`` — no I/O, no imports with side effects, so the registry is safe to
introspect from the bridge and the UI. Unknown or missing fields render as
empty strings (fail-open); a template must never raise on bad variables.

Execution goes through the CHEAP auxiliary tier by default (the repo's
management-call routing law: compression, titling, one-shots never burn
the main model). ``invoke`` is injectable for hermetic tests, exactly like
``session_titling.generate_session_title``.
"""
from __future__ import annotations

from typing import Any, Callable

TemplateFn = Callable[[dict], tuple[str, str]]

_MAX_INPUT_CHARS = 12_000


def _v(variables: dict, *keys: str) -> str:
    """First non-empty string among keys, whitespace-normalized, capped."""
    for key in keys:
        raw = str(variables.get(key) or "").strip()
        if raw:
            import re
            return re.sub(r"[ \t]+", " ", raw)[:_MAX_INPUT_CHARS]
    return ""


def _t_commit_message(variables: dict) -> tuple[str, str]:
    diff = _v(variables, "diff", "input")
    notes = _v(variables, "notes", "context")
    system = (
        "You write git commit messages. Output ONLY the commit message: "
        "one imperative subject line (<= 72 chars, no trailing period), "
        "then a blank line, then a short body explaining the WHY when the "
        "subject alone is not obvious. No markdown fences, no preamble."
    )
    user = (
        "Write the commit message for this change.\n\nDiff / change summary:\n"
        f"{diff or '(not provided)'}"
        + (f"\n\nExtra context from the developer:\n{notes}" if notes else "")
    )
    return system, user


def _t_summarize(variables: dict) -> tuple[str, str]:
    text = _v(variables, "text", "input")
    system = (
        "You summarize technical content faithfully. Lead with the single "
        "most important sentence, then at most 5 tight bullets. Keep the "
        "author's terminology. No preamble, no opinions."
    )
    user = f"Summarize this.\n\n{text or '(not provided)'}"
    return system, user


def _t_rename_ideas(variables: dict) -> tuple[str, str]:
    subject = _v(variables, "subject", "context", "input")
    system = (
        "You propose names (features, modules, products, variables). "
        "Return exactly 8 candidates as a numbered list, each with a "
        "one-clause rationale. Prefer clear over clever; no duplicates."
    )
    user = (
        "Propose names for:\n"
        f"{subject or '(not provided)'}"
    )
    return system, user


def _t_title_session(variables: dict) -> tuple[str, str]:
    # Reuse the SHIPPED titling prompt instead of duplicating it — one
    # source of truth for how this product titles a session.
    from src.runtime.session_titling import _TITLE_PROMPT
    user = _v(variables, "user", "input")
    assistant = _v(variables, "assistant", "context")
    system = "You write short chat-session titles."
    rendered = _TITLE_PROMPT.format(user=user or "(not provided)", assistant=assistant or "(no reply yet)")
    return system, rendered


PROMPT_TEMPLATES: dict[str, TemplateFn] = {
    "commit_message": _t_commit_message,
    "summarize": _t_summarize,
    "rename_ideas": _t_rename_ideas,
    "title_session": _t_title_session,
}


def list_templates() -> list[dict]:
    """Catalog for the UI/bridge: name + the variables each accepts."""
    described = [
        ("commit_message", "Draft a git commit message from a diff or change summary.", ("diff", "notes")),
        ("summarize", "Summarize text or a page into the essentials.", ("text",)),
        ("rename_ideas", "Propose 8 named candidates with rationale.", ("subject",)),
        ("title_session", "Title a session from its first exchange.", ("user", "assistant")),
    ]
    return [{"name": n, "description": d, "variables": list(v)} for n, d, v in described]


def render_template(template: str, variables: dict | None = None) -> dict:
    """Pure render — no provider call. Bridge/UI preview path."""
    name = (template or "").strip()
    fn = PROMPT_TEMPLATES.get(name)
    if fn is None:
        return {
            "ok": False,
            "error": (
                f"unknown oneshot template {name!r} — available: "
                + ", ".join(sorted(PROMPT_TEMPLATES))
            ),
        }
    try:
        system, user = fn(dict(variables or {}))
    except Exception as exc:
        return {"ok": False, "error": f"template {name!r} failed to render: {exc}"}
    return {"ok": True, "template": name, "system": system, "user": user}


def run_oneshot(
    template: str = "",
    instructions: str = "",
    variables: dict | None = None,
    *,
    max_tokens: int = 512,
    invoke: Callable[[str], Any] | None = None,
) -> dict:
    """Execute one quick job and return the model's text.

    Two shapes:
      - template mode: ``template`` names a PROMPT_TEMPLATES entry
      - ad-hoc mode: ``instructions`` (system-ish ask) + the first of
        ``variables['input']`` as the user content

    The default ``invoke`` is the cheap auxiliary LLM (management-call
    routing law). Never raises — errors come back as ``{"ok": False}``.
    """
    variables = dict(variables or {})
    if template:
        rendered = render_template(template, variables)
        if not rendered.get("ok"):
            return rendered
        system, user = rendered["system"], rendered["user"]
    else:
        ask = (instructions or "").strip()
        if not ask:
            return {"ok": False, "error": "oneshot needs a template or instructions"}
        system = "You complete the requested one-off task precisely and without preamble."
        user = _v(variables, "input", "text") or "(not provided)"
        user = f"{ask}\n\n{user}"
        user = user[:_MAX_INPUT_CHARS + len(ask) + 2]

    if invoke is None:
        try:
            from src.llm.factory import get_auxiliary_llm
            raw = get_auxiliary_llm().invoke(user)
        except Exception as exc:
            return {"ok": False, "error": f"oneshot provider call failed: {str(exc)[:300]}"}
    else:
        try:
            raw = invoke(user)
        except Exception as exc:
            return {"ok": False, "error": f"oneshot call failed: {str(exc)[:300]}"}

    content = getattr(raw, "content", raw)
    if isinstance(content, list):
        parts = [
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content
        ]
        content = " ".join(parts)
    text = str(content or "").strip()
    if not text:
        return {"ok": False, "error": "oneshot returned an empty response"}
    return {"ok": True, "template": template or "adhoc", "text": text[:8000]}
