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

``skill_manage`` is the WRITE half — hermes' learning loop: the model records
a non-trivial workflow it worked out (SKILLS_GUIDANCE's "record it with
skill_manage") as an agent-created skill. Creates/updates go to the user
store via SkillManager.add_skill (D39 provenance: created_by="agent", so the
curator lifecycle governs them); bundled repo skills are read-only. Until
this tool existed, the shipped guidance named a tool that was never bound
(hermes #39797 class: dangling guidance).

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


@tool
def skill_manage(
    action: str,
    name: str = "",
    triggers: str = "",
    instruction: str = "",
    description: str = "",
) -> str:
    """Record or update a skill — the WRITE side of the learning loop.

    When you work out a non-trivial workflow that future sessions should
    reuse, capture it here instead of re-deriving it every time. Creates and
    updates land in the user's skill store (~/.crusorai/skills.json) as
    agent-created skills; the D39 curator may archive unused ones (never
    deletes). Bundled repo skills (skills/<name>/SKILL.md) ship with the
    engine and are read-only here — ask the user to edit those files.

    Args:
        action: "create" (new skill), "patch" (update an existing one), or
            "archive" (retire a skill you created; nothing is deleted).
        name: lowercase-hyphenated skill name, <= 64 chars, e.g.
            "deploy-checklist".
        triggers: comma-separated words/phrases a matching USER TASK would
            literally contain, e.g. "deploy, release, ship checklist".
            Distinctive beats generic: "unit test", not "test".
        instruction: the skill body — the workflow itself: when to use it,
            exact steps framed through Crusor tools (run_terminal, edit_file,
            media_search, ...), pitfalls, and how to verify the result.
        description: one-line discovery summary for the skills index (<= 60
            chars, ends with a period, states the capability).
    """
    action = (action or "").strip().lower()
    name = (name or "").strip()
    manager = _manager()

    if action == "archive":
        skill = _find(name)
        if skill is None:
            return f"skill_manage error: no skill named {name!r} (skills_list to see what exists)"
        if skill.get("created_by") == "bundled":
            return (
                f"skill_manage error: {skill['name']} is a bundled repo skill — "
                "bundled skills are read-only; ask the user to edit skills/"
                f"{skill['name']}/SKILL.md in the engine repo"
            )
        skill["state"] = "archived"
        manager._save()
        return f"archived: {skill['name']} (archived skills stay on disk, never deleted; re-create or patch to reactivate)"

    if action not in ("create", "patch"):
        return f"skill_manage error: action must be create|patch|archive, got {action!r}"

    if not name:
        return "skill_manage error: name is required (lowercase-hyphenated, <= 64 chars)"
    if len(name) > 64 or any(c.isspace() for c in name):
        return (
            f"skill_manage error: name must be lowercase-hyphenated and <= 64 chars "
            f"(no spaces), got {name!r}"
        )

    existing = _find(name)
    if action == "create" and existing is not None:
        # hermes parity: create on an existing name is an update, surfaced as such
        action = "patch"

    if action == "patch" and existing is not None and existing.get("created_by") == "bundled":
        return (
            f"skill_manage error: {existing['name']} is a bundled repo skill — "
            "bundled skills are read-only; ask the user to edit skills/"
            f"{existing['name']}/SKILL.md in the engine repo"
        )

    trigger_list = [t.strip().lower() for t in (triggers or "").replace(",", " ").split() if t.strip()]
    if not trigger_list and action == "patch" and existing is not None:
        trigger_list = [str(t) for t in (existing.get("triggers") or [])]
    if not trigger_list:
        return (
            "skill_manage error: triggers is required — comma-separated words/phrases "
            "a matching user task would literally contain (e.g. 'deploy, release checklist')"
        )

    body = (instruction or "").strip()
    if action == "patch" and existing is not None and not body:
        body = str(existing.get("instruction", ""))
    if not body:
        return (
            "skill_manage error: instruction is required — the actual workflow "
            "(when to use, exact steps with Crusor tool names, pitfalls, verification)"
        )

    desc = (description or "").strip()
    note = ""
    if desc and len(desc) > 60:
        # hermes HARDLINE: the index displays the description; long ones
        # still work here (no silent cut) but route worse — say so.
        note = f"\n(note: description is {len(desc)} chars — over the 60-char house style; it will still be indexed in full)"

    manager.add_skill(
        name,
        trigger_list,
        body,
        created_by="agent",
        pinned=False,
        description=desc or (str(existing.get("description")) if existing is not None else ""),
    )
    verb = "created" if action == "create" else "updated"
    return (
        f"{verb}: {name} (triggers: {', '.join(trigger_list)}). "
        f"It now appears in the skills index; future sessions matching those triggers "
        f"will be pointed at it.{note}"
    )


SKILL_TOOLS = (skills_list, skill_view, skill_manage)
