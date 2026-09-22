"""Preview lab — MOCK agent turn.

This is the demo double for the real Crusor turn. In the IDE, ``Send to Crusor`` posts a bridge v2
``prompt`` frame built by :mod:`src.preview.prompt` and the engine edits real source files. Here,
with no provider call and no repo to edit, the same batch is interpreted by rules and written to a
CSS override sheet that the fixture page links — so the loop is *visible*: send → edit → preview
reloads → the clicked element has changed.

Everything upstream of this file is the real thing: the preview window chrome, the injected
overlay, the proxy, the injection, and the prompt builder. Only the model is mocked.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = ["apply_batch", "interpret", "OVERRIDE_STYLESHEET", "reset"]

OVERRIDE_STYLESHEET = "preview-overrides.css"

#: Keyword -> declarations. Ordered: earlier rules win when several match, so "make it not rounded"
#: is handled before "rounded" by the negation pass.
_RULES: Sequence[tuple[tuple[str, ...], dict[str, str]]] = (
    (("hide", "remove", "delete", "get rid"), {"display": "none"}),
    (("uppercase", "all caps", "capital"), {"text-transform": "uppercase"}),
    (("lowercase",), {"text-transform": "lowercase"}),
    (("underline",), {"text-decoration": "underline"}),
    (("pill", "fully rounded", "fully round"), {"border-radius": "999px"}),
    (("rounded", "round the corners", "round corners", "softer corners"), {"border-radius": "14px"}),
    (("square corners", "sharp corners", "not rounded"), {"border-radius": "2px"}),
    (("bolder", "bold", "heavier", "stronger"), {"font-weight": "700"}),
    (("thinner", "lighter font", "not bold"), {"font-weight": "400"}),
    (("bigger", "larger", "increase size", "scale up", "more prominent"), {"font-size": "1.25em"}),
    (("smaller", "little smaller", "reduce size", "scale down", "subtler"), {"font-size": ".85em"}),
    (("wider", "full width", "stretch"), {"width": "100%"}),
    (("taller", "more height"), {"min-height": "56px"}),
    (("center", "centre", "middle"), {"text-align": "center", "margin-left": "auto", "margin-right": "auto"}),
    (("align left", "left align"), {"text-align": "left"}),
    (("align right", "right align"), {"text-align": "right"}),
    (("more spacing", "more padding", "roomier", "breathe", "airy"), {"padding": "1.5em 1.75em"}),
    (("less spacing", "tighter", "compact"), {"padding": ".45em .7em"}),
    (("more gap", "spread out", "space between"), {"gap": "24px"}),
    (("shadow", "elevate", "lift", "depth"), {"box-shadow": "0 14px 34px -12px rgba(16,20,28,.42)"}),
    (("no shadow", "flat", "remove shadow"), {"box-shadow": "none"}),
    (("border", "outline it", "add a border"), {"border": "1px solid currentColor"}),
    (("italic",), {"font-style": "italic"}),
    (("mono", "monospace", "code font"), {"font-family": "ui-monospace, SFMono-Regular, Menlo, monospace"}),
)

_COLORS: dict[str, tuple[str, str]] = {
    # name -> (background, foreground)
    "blue": ("#2563eb", "#ffffff"),
    "indigo": ("#4f46e5", "#ffffff"),
    "purple": ("#7c3aed", "#ffffff"),
    "violet": ("#8b5cf6", "#ffffff"),
    "pink": ("#db2777", "#ffffff"),
    "red": ("#dc2626", "#ffffff"),
    "orange": ("#ea7317", "#1a1206"),
    "amber": ("#f5b301", "#241c00"),
    "yellow": ("#facc15", "#241c00"),
    "green": ("#16a34a", "#ffffff"),
    "teal": ("#0d9488", "#ffffff"),
    "cyan": ("#0891b2", "#ffffff"),
    "black": ("#14161a", "#ffffff"),
    "white": ("#ffffff", "#14161a"),
    "grey": ("#e4e7ec", "#14161a"),
    "gray": ("#e4e7ec", "#14161a"),
}

_NEGATIONS = ("not ", "no ", "don't ", "dont ", "without ", "remove ", "never ")


def _split_clauses(instruction: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]|\band\b|\balso\b|\bthen\b", instruction.lower()) if part.strip()]


def interpret(instruction: str) -> tuple[dict[str, str], list[str]]:
    """Map one natural-language fix to CSS declarations.

    Returns ``(declarations, matched_rules)``. An empty ``declarations`` means the mock could not
    read the instruction — the lab reports that honestly instead of silently doing nothing.
    """
    declarations: dict[str, str] = {}
    matched: list[str] = []

    for clause in _split_clauses(instruction):
        negated = any(clause.startswith(neg) or f" {neg}" in clause for neg in _NEGATIONS)

        # Color is its own axis: "make it blue", "blue background", "text in blue".
        for name, (background, foreground) in _COLORS.items():
            if not re.search(rf"\b{name}\b", clause):
                continue
            if negated:
                declarations.pop("background-color", None)
                declarations.pop("color", None)
                matched.append(f"not-{name}")
                break
            if "text" in clause or "font" in clause or "label" in clause or "type" in clause:
                declarations["color"] = background
                matched.append(f"color:{name}")
            else:
                declarations["background-color"] = background
                declarations["color"] = foreground
                matched.append(f"background:{name}")
            break

        for keywords, styles in _RULES:
            if not any(keyword in clause for keyword in keywords):
                continue
            if negated and keywords[0] not in ("hide", "remove", "delete", "get rid"):
                matched.append("not-" + keywords[0])
                for key in styles:
                    declarations.pop(key, None)
                break
            declarations.update(styles)
            matched.append(keywords[0])
            break

    return declarations, matched


def _selector_for(element: dict[str, Any]) -> str:
    selector = str(element.get("selector") or "").strip()
    if not selector:
        tag = str(element.get("tag") or "body")
        selector = tag
    # A comma-free, single-element selector keeps the override sheet readable and reversible.
    return selector.split(",")[0].strip()


def _render(fixes: Iterable[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    blocks: list[str] = []
    results: list[dict[str, Any]] = []

    for index, fix in enumerate(fixes, start=1):
        element = fix.get("element") if isinstance(fix.get("element"), dict) else {}
        instruction = str(fix.get("instruction") or "").strip()
        selector = _selector_for(element)
        declarations, matched = interpret(instruction)
        label = str(fix.get("label") or element.get("tag") or "element")

        if not declarations:
            results.append({
                "order": index, "label": label, "selector": selector, "instruction": instruction,
                "status": "unresolved", "detail": "the mock agent could not read this instruction",
                "matched": matched,
            })
            continue

        source = element.get("fingerprint", {}).get("source") if isinstance(element.get("fingerprint"), dict) else None
        source_note = ""
        if isinstance(source, dict) and source.get("file"):
            line = source.get("line")
            source_note = f"{source['file']}" + (f":{line}" if line else "")
        body = "\n".join(f"  {key}: {value} !important;" for key, value in declarations.items())
        blocks.append(
            f"/* fix {index} · {label}\n"
            f"   instruction: {instruction}\n"
            f"   located via: {source_note or 'fingerprint (classes/text/attrs)'} */\n"
            f"{selector} {{\n{body}\n}}"
        )
        results.append({
            "order": index, "label": label, "selector": selector, "instruction": instruction,
            "status": "applied", "detail": ", ".join(f"{k}: {v}" for k, v in declarations.items()),
            "matched": matched, "source": source_note or None,
        })

    header = (
        "/* Crusor Preview — lab override sheet, written by the MOCK agent.\n"
        " * In the IDE the agent edits the project's own source; here the edits land in this\n"
        " * generated sheet so the loop is visible without a provider call. Reset clears it. */\n"
    )
    return header + "\n\n".join(blocks) + ("\n" if blocks else ""), results


def _strip_header(css: str) -> str:
    """Drop the leading comment block so repeated passes don't stack headers."""
    marker = "*/"
    index = css.find(marker)
    return css[index + len(marker):].strip() if index != -1 else css.strip()


def apply_batch(batch: dict[str, Any], runtime_dir: Path) -> dict[str, Any]:
    """Interpret a reviewed batch and write the override sheet. Returns an agent-shaped receipt."""
    fixes = [f for f in (batch.get("fixes") or []) if isinstance(f, dict)]
    css, results = _render(fixes)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    sheet = runtime_dir / OVERRIDE_STYLESHEET
    previous = sheet.read_text(encoding="utf-8") if sheet.is_file() else ""

    # Accumulate: a second review pass must not silently revert the first.
    if previous.strip():
        blocks = _strip_header(css)
        merged = previous.rstrip() + ("\n\n" + blocks + "\n" if blocks else "\n")
    else:
        merged = css
    sheet.write_text(merged, encoding="utf-8")

    applied = [r for r in results if r["status"] == "applied"]
    unresolved = [r for r in results if r["status"] != "applied"]
    return {
        "ok": bool(applied),
        "sheet": OVERRIDE_STYLESHEET,
        "files_changed": [f"preview-lab/.runtime/{OVERRIDE_STYLESHEET}"] if applied else [],
        "applied": applied,
        "unresolved": unresolved,
        "summary": (
            f"{len(applied)} of {len(results)} fix" + ("" if len(results) == 1 else "es") + " applied"
            + (f", {len(unresolved)} unresolved" if unresolved else "")
        ),
        "selectors": [r["selector"] for r in applied],
        "bytes_before": len(previous),
        "bytes_after": len(sheet.read_text(encoding="utf-8")),
        "at": time.time(),
    }


def reset(runtime_dir: Path) -> dict[str, Any]:
    sheet = runtime_dir / OVERRIDE_STYLESHEET
    if sheet.is_file():
        sheet.unlink()
    return {"ok": True, "cleared": OVERRIDE_STYLESHEET}
