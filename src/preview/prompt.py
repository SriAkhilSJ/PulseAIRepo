"""Crusor Preview — turn a batch of clicked-element fixes into one scoped agent turn.

The Preview window collects fixes (element + instruction) while the user clicks around the UI
the agent built. On **Review → Send to Crusor** the batch crosses the existing bridge as an
ordinary ``prompt`` frame (protocol v2, no new method, no version bump): the value of this
module is the *text* it produces, which is what makes the agent edit the right element instead
of repainting the page.

Design rules encoded here:

* every fix names its element three ways — human label, CSS selector, and grep-able
  fingerprints — because the agent's only reliable path from DOM to source is search;
* the instruction is verbatim (the user's words are the requirement, never paraphrased);
* the batch is explicitly *bounded*: change only these elements, touch nothing else;
* the whole prompt is capped, oldest-fix-first truncation, so a 40-click session cannot blow
  the turn budget.

Pure stdlib, pure functions — pinned by ``src/tests/test_preview_prompt.py``.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "MAX_PROMPT_CHARS",
    "PREVIEW_PROMPT_MARKER",
    "build_preview_prompt",
    "build_prompt_frame",
    "describe_element",
    "summarize_batch",
]

#: Hard ceiling for the generated prompt. The batch is truncated (newest fixes dropped, with a
#: visible note) rather than allowed to grow without bound.
MAX_PROMPT_CHARS = 12_000

#: Stable marker so the renderer can recognise a preview-sourced turn and draw it as a card.
PREVIEW_PROMPT_MARKER = "crusor-preview:fix-batch"

#: Instructions the agent gets about scope. Kept as one block so it reads as a contract.
_SCOPE_RULES = (
    "Apply every fix below. Each one was created by clicking an element in the live preview of the "
    "UI you built, so:\n"
    "- change ONLY the named elements; leave the rest of the page alone;\n"
    "- locate each element in the source with the fingerprints given (grep the classes, the text, "
    "the data attributes) before editing — do not guess a file;\n"
    "- keep the fix minimal and in the project's own style system (its tokens/variables/utility "
    "classes), not inline overrides, unless the project already does that;\n"
    "- if a fix is ambiguous or the element cannot be found, say so for that fix and continue with "
    "the others;\n"
    "- when done, list the files you changed."
)


def _text(value: Any, limit: int = 0) -> str:
    text = str(value or "").replace("\r", " ").strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _classes(element: Mapping[str, Any]) -> list[str]:
    raw = element.get("classes")
    if isinstance(raw, str):
        return [c for c in raw.split() if c][:8]
    if isinstance(raw, Iterable):
        return [str(c) for c in raw if str(c)][:8]
    return []


def _fingerprint_line(element: Mapping[str, Any]) -> str:
    """The grep-able identity of the element: what literally appears in the source file."""
    fingerprint = element.get("fingerprint") if isinstance(element.get("fingerprint"), Mapping) else {}
    parts: list[str] = []
    classes = _classes(element)
    if classes:
        parts.append("classes=" + " ".join(classes))
    text = _text(fingerprint.get("text") or element.get("text"), 90)
    if text:
        parts.append(f'text="{text}"')
    attrs = fingerprint.get("attrs")
    if isinstance(attrs, Iterable):
        rendered = [
            f'{a.get("name")}="{_text(a.get("value"), 60)}"'
            for a in attrs
            if isinstance(a, Mapping) and a.get("name")
        ][:6]
        if rendered:
            parts.append("attrs=" + ", ".join(rendered))
    if element.get("id"):
        parts.append(f'id="{_text(element.get("id"), 60)}"')
    return " · ".join(parts)


def _source_hint(element: Mapping[str, Any]) -> str | None:
    """Precise mapping, when the project stamps source positions into the DOM."""
    fingerprint = element.get("fingerprint") if isinstance(element.get("fingerprint"), Mapping) else {}
    source = fingerprint.get("source") or element.get("source")
    if not isinstance(source, Mapping):
        return None
    file = _text(source.get("file"), 200)
    if not file:
        return None
    line = source.get("line")
    component = _text(source.get("component"), 80)
    bits = [file]
    if isinstance(line, int) and line > 0:
        bits.append(f"line {line}")
    if component:
        bits.append(f"component {component}")
    return " → ".join(bits)


def _style_line(element: Mapping[str, Any]) -> str:
    styles = element.get("styles")
    if not isinstance(styles, Mapping):
        return ""
    # Only the properties a visual fix usually moves, in a stable order.
    order = (
        "background-color", "color", "border-radius", "border", "font-size", "font-weight",
        "padding", "margin", "gap", "width", "height", "display", "text-align", "box-shadow",
    )
    rendered = [f"{key}: {styles[key]}" for key in order if key in styles and styles[key]]
    rendered += [f"{k}: {v}" for k, v in styles.items() if k not in order and v][:4]
    return "; ".join(rendered[:10])


def describe_element(element: Mapping[str, Any]) -> str:
    """Human label for one element: `<tag> "text"` or `<tag> .class`."""
    tag = _text(element.get("tag"), 40) or "element"
    text = _text(element.get("text"), 40)
    classes = _classes(element)
    if text:
        return f'<{tag}> "{text}"'
    if classes:
        return f"<{tag}> .{classes[0]}"
    return f"<{tag}>"


def _fix_block(index: int, fix: Mapping[str, Any]) -> str:
    element = fix.get("element") if isinstance(fix.get("element"), Mapping) else {}
    label = _text(fix.get("label"), 120) or describe_element(element)
    rect = element.get("rect") if isinstance(element.get("rect"), Mapping) else {}
    viewport = element.get("viewport") if isinstance(element.get("viewport"), Mapping) else {}

    lines = [
        f"Fix {index} — {label}",
        f"  instruction: {_text(fix.get('instruction'), 400) or '(empty)'}",
    ]
    if element.get("selector"):
        lines.append(f"  selector: {_text(element.get('selector'), 220)}")
    fingerprint = _fingerprint_line(element)
    if fingerprint:
        lines.append(f"  fingerprint: {fingerprint}")
    source = _source_hint(element)
    if source:
        lines.append(f"  source: {source}")
    if rect:
        box = f"  box: {rect.get('width', 0)}×{rect.get('height', 0)} at ({rect.get('x', 0)},{rect.get('y', 0)})"
        if viewport:
            box += f" · viewport {viewport.get('width', 0)}×{viewport.get('height', 0)}"
        lines.append(box)
    styles = _style_line(element)
    if styles:
        lines.append(f"  styles: {styles}")
    html = _text(element.get("outerHtml"), 420)
    if html:
        lines.append(f"  html: {html}")
    return "\n".join(lines)


def summarize_batch(batch: Mapping[str, Any]) -> str:
    """One-line summary for the transcript card / toast."""
    fixes = _fixes(batch)
    count = len(fixes)
    target = _text(batch.get("targetLabel") or batch.get("target"), 80)
    label = f"{count} preview fix" + ("" if count == 1 else "es")
    return f"{label} · {target}" if target else label


def _fixes(batch: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    raw = batch.get("fixes")
    if not isinstance(raw, Sequence):
        return ()
    return [f for f in raw if isinstance(f, Mapping) and _text(f.get("instruction"))]


def build_preview_prompt(batch: Mapping[str, Any]) -> str:
    """Render a fix batch as the scoped prompt text sent to Crusor.

    Truncates newest-first when the batch would exceed :data:`MAX_PROMPT_CHARS`, and says so in
    the prompt itself — a silent drop would leave the user believing a fix was sent.
    """
    fixes = list(_fixes(batch))
    if not fixes:
        return ""

    target = _text(batch.get("targetLabel") or batch.get("target"), 200) or "the previewed page"
    viewport = _text(batch.get("viewport"), 40)
    header = [
        f"<!-- {PREVIEW_PROMPT_MARKER} count={len(fixes)} -->",
        f"Crusor Preview — {len(fixes)} UI fix" + ("" if len(fixes) == 1 else "es") + f" from the live preview of {target}.",
        "",
        _SCOPE_RULES,
    ]
    if viewport and viewport != "responsive":
        header.append(f"(Previewed at the {viewport} viewport preset.)")

    blocks: list[str] = []
    dropped = 0
    for offset, fix in enumerate(fixes):
        candidate = "\n\n".join(blocks + [_fix_block(offset + 1, fix)])
        if len("\n".join(header)) + len(candidate) > MAX_PROMPT_CHARS:
            dropped = len(fixes) - offset
            break
        blocks.append(_fix_block(offset + 1, fix))

    parts = ["\n".join(header), "", "\n\n".join(blocks)]
    if dropped:
        parts.append(
            f"\n({dropped} further fix" + ("" if dropped == 1 else "es") +
            " were left out to stay inside the prompt budget — ask me to re-send them.)"
        )
    parts.append(
        "\nAfter editing, re-render the preview so the change can be checked in place."
    )
    return "\n".join(parts).strip() + "\n"


def build_prompt_frame(
    batch: Mapping[str, Any],
    *,
    session_id: str,
    workspace: str,
    mode: str = "agent",
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Wrap the prompt in a bridge v2 ``prompt`` frame.

    ``workspace`` is **required**, not optional, because the bridge requires it: ``prompt`` is in
    ``_WORKSPACE_REQUIRED_METHODS`` and the check runs per frame, before the session is even
    resolved, so a prompt frame without it is refused with
    ``workspace required: open a project folder before starting a Crusor session``. A builder that
    can silently emit a frame the engine rejects is a trap, and one shipped call site walked into
    it, which is why this is a required keyword rather than a default of ``""``.

    Raises ``ValueError`` for an empty batch so callers never fire a blank turn at the engine.
    """
    text = build_preview_prompt(batch)
    if not text:
        raise ValueError("preview fix batch is empty — nothing to send")
    if not str(workspace or "").strip():
        raise ValueError("preview prompt needs the workspace path the session is bound to")
    frame: dict[str, Any] = {
        "type": "prompt",
        "session_id": session_id,
        "workspace": str(workspace),
        "text": text,
        "mode": mode,
        "preview_batch": {
            "marker": PREVIEW_PROMPT_MARKER,
            "target": _text(batch.get("target"), 300),
            "target_label": _text(batch.get("targetLabel"), 200),
            "kind": _text(batch.get("kind"), 20),
            "viewport": _text(batch.get("viewport"), 40),
            "count": len(_fixes(batch)),
            "created_at": _text(batch.get("createdAt"), 40),
        },
    }
    if reasoning_effort:
        frame["reasoning_effort"] = reasoning_effort
    return frame
