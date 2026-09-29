"""Server-side auto-titler (Hermes ``session.title`` parity).

Rule (field 2026-09-28): history titles are CREATED (model-written from the
first exchange), FIXED (automation never retitles a titled session — only an
explicit ``session_rename`` changes a title), and UNIQUE within the workspace
(``" (2)"`` suffixing on collision). Nothing captures the first message
verbatim anymore — untitled sessions render a generic placeholder until the
titler's live push lands.
"""

from __future__ import annotations

import re
from typing import Any, Callable

TITLE_MAX_CHARS = 60

_TITLE_PROMPT = (
    "Write a short chat-session title for the exchange below. Rules: at most 8 words, "
    "plain words only, no quotes, no trailing punctuation, never the word \"session\". "
    "Reply with ONLY the title.\n\n"
    "User: {user}\nAssistant: {assistant}\nTitle:"
)

_QUOTE_CHARS = "\"'“”‘’`"


def _clean_model_title(text: str) -> str:
    """First line, unquoted, unpunctuated, capped. Empty stays empty."""
    line = str(text or "").strip().splitlines()
    cleaned = re.sub(r"\s+", " ", line[0].strip() if line else "")
    cleaned = cleaned.strip(_QUOTE_CHARS).strip()
    cleaned = re.sub(r"[\s:;\-–—.,!?]+$", "", cleaned).strip()
    cleaned = cleaned.strip(_QUOTE_CHARS).strip()
    if len(cleaned) > TITLE_MAX_CHARS:
        cleaned = cleaned[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return cleaned


def shorten_title(text: str, limit: int = TITLE_MAX_CHARS) -> str:
    """Explicit text (a delegation goal, a draft title) -> fixed-length title."""
    collapsed = re.sub(r"\s+", " ", str(text or "").strip().splitlines()[0] if str(text or "").strip() else "")
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1].rstrip() + "…"
    return collapsed


def generate_session_title(
    user_text: str,
    assistant_text: str = "",
    invoke: Callable[[str], Any] | None = None,
) -> str:
    """Model-write a title for the first exchange. ``""`` on any failure.

    ``invoke`` defaults to the cheap auxiliary LLM; tests inject a fake.
    """
    user = re.sub(r"\s+", " ", str(user_text or "").strip())
    if not user:
        return ""
    assistant = re.sub(r"\s+", " ", str(assistant_text or "").strip())
    prompt = _TITLE_PROMPT.format(user=user[:600], assistant=assistant[:800] or "(no reply yet)")
    try:
        if invoke is None:
            from src.llm.factory import get_auxiliary_llm

            raw = get_auxiliary_llm().invoke(prompt)
        else:
            raw = invoke(prompt)
        content = getattr(raw, "content", raw)
        if isinstance(content, list):
            parts = [
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in content
            ]
            content = " ".join(parts)
        return _clean_model_title(str(content or ""))
    except Exception:
        return ""


def ensure_unique_title(store: Any, workspace: str, base: str) -> str:
    """Dedupe ``base`` against the workspace's titles (case-insensitive).

    ``"Deploy checklist"`` -> ``"Deploy checklist (2)"`` -> ``" (3)"`` ...
    """
    cleaned = shorten_title(base)
    if not cleaned:
        return ""
    try:
        rows = store.list_sessions_rich(workspace=workspace or None, limit=2000) or []
    except TypeError:
        rows = store.list_sessions_rich(limit=2000) or []
    taken = {
        str(row.get("title") or "").strip().lower()
        for row in rows
        if str(row.get("title") or "").strip()
    }
    if cleaned.lower() not in taken:
        return cleaned
    stem = re.sub(r"\s*\(\d+\)$", "", cleaned).rstrip() or cleaned
    index = 2
    while f"{stem} ({index})".lower() in taken:
        index += 1
    return f"{stem} ({index})"
