"""Skill tools — Copilot/Agent-Skills parity: the PULL side of skills.

The system prompt carries a compact ``<available_skills>`` index (name +
description). Loading a skill's full body is on demand: the model calls
``skill_view(name)`` — hermes' ``skill_view`` shape, the same pull model
Copilot's skill tool uses (discovery -> activation -> execution). The eager
trigger-injection layer (``ContextEngine._skills_layer``) still auto-injects
bodies for matched tasks; these tools give the model read access to every
skill anyway — including user-created skills that never match a trigger.

``skills_list`` is the same index as a tool (the read target file_safety's
".hub blocked" error points at).

Both follow the hermes tool shape (D17): errors are returned as strings,
never raised.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import tool

_SKILL_SUPPORT_DIRS = ("references", "assets", "scripts", "templates")
_MAX_SUPPORT_FILES = 20
_MAX_LISTED_NAMES = 40


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _skills_dir() -> Path:
    return _repo_root() / "skills"


def _manager() -> Any:
    from src.agents.skill_manager import skill_manager
    return skill_manager


def _find(name: str) -> dict | None:
    raw = (name or "").strip()
    if not raw:
        return None
    skills = _manager().list_skills()
    for s in skills:
        if str(s.get("name", "")) == raw:
            return s
    low = raw.lower()
    for s in skills:
        if str(s.get("name", "")).lower() == low:
            return s
    return None


@tool
def skill_view(name: str) -> str:
    """Load a skill's full instructions into context — do this when the skills
    index lists a skill relevant to the current task, then follow its body.

    Returns the skill body (frontmatter stripped) and, for bundled skills, the
    skill folder's supporting files (scripts, references, templates). Covers
    bundled SKILL.md skills and user-created skills alike.

    Args:
        name: skill name exactly as it appears in the skills index,
            e.g. "media-sourcing".
    """
    skill = _find(name)
    if skill is None:
        names = sorted(
            str(s.get("name", ""))
            for s in _manager().list_skills()
            if s.get("enabled", True) and s.get("state") != "archived"
        )
        shown = ", ".join(names[:_MAX_LISTED_NAMES])
        if len(names) > _MAX_LISTED_NAMES:
            shown += ", ..."
        return f"skill_view error: no skill named {name!r}. Available: {shown}"

    skill_name = str(skill["name"])
    source = "bundled" if skill.get("created_by") == "bundled" else str(skill.get("created_by", "user"))
    parts = [
        f"# skill: {skill_name}",
        f"(source: {source}; triggers: {', '.join(skill.get('triggers', []) or [])})",
    ]

    body = ""
    support_note = ""
    skill_md = _skills_dir() / skill_name / "SKILL.md"
    if skill.get("created_by") == "bundled" and skill_md.is_file():
        # Read the file itself: the stored instruction is capped, skill_view
        # must return the whole body.
        from src.agents.skill_manager import _parse_skill_frontmatter
        try:
            _, body = _parse_skill_frontmatter(skill_md.read_text(encoding="utf-8"))
        except Exception:
            body = str(skill.get("instruction", ""))
        support: list[str] = []
        for sub in _SKILL_SUPPORT_DIRS:
            d = skill_md.parent / sub
            if d.is_dir():
                support.extend(
                    str(p.relative_to(skill_md.parent))
                    for p in sorted(d.rglob("*"))
                    if p.is_file()
                )
        if support:
            listed = support[:_MAX_SUPPORT_FILES]
            note = "Supporting files (relative to the skill folder):\n" + "\n".join(
                f"- {f}" for f in listed
            )
            if len(support) > _MAX_SUPPORT_FILES:
                note += f"\n(+{len(support) - _MAX_SUPPORT_FILES} more)"
            support_note = note
    else:
        body = str(skill.get("instruction", ""))

    body = (body or "").strip()
    if not body:
        return f"skill_view error: skill {skill_name!r} has an empty body"

    _manager().record_usage(skill_name, "view")
    parts.append(body)
    if support_note:
        parts.append(support_note)
    return "\n\n".join(parts)


@tool
def skills_list() -> str:
    """List installed skills (name, source, triggers, state, use count) — the
    skills index as a tool. Load one with skill_view(name)."""
    rows: list[str] = []
    for s in _manager().list_skills():
        name = str(s.get("name", ""))
        if not name:
            continue
        source = "bundled" if s.get("created_by") == "bundled" else str(s.get("created_by", "user"))
        flags = []
        if not s.get("enabled", True):
            flags.append("disabled")
        if s.get("state") == "archived":
            flags.append("archived")
        flag_txt = f" [{' '.join(flags)}]" if flags else ""
        triggers = ", ".join(s.get("triggers", []) or [])
        rows.append(
            f"- {name} ({source}){flag_txt} triggers: {triggers or '-'} "
            f"use_count: {s.get('use_count', 0)}"
        )
    if not rows:
        return "No skills installed."
    return (
        "Available skills (load one with skill_view(name)):\n" + "\n".join(rows)
    )


SKILL_TOOLS = (skills_list, skill_view)
