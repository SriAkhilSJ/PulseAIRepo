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

import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

_SKILL_SUPPORT_DIRS = ("references", "assets", "scripts", "templates")
_MAX_SUPPORT_FILES = 20
_MAX_LISTED_NAMES = 40
_MAX_BOOKS_PER_VIEW = 6
_MAX_VIEW_CHARS = 60000


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _skills_dir() -> Path:
    return _repo_root() / "skills"


def _manager() -> Any:
    from src.agents.skill_manager import skill_manager
    return skill_manager


def _skill_file(skill: dict) -> Path | None:
    """Locate a bundled skill's SKILL.md from its recorded shelf path.

    The library is nested (domain -> branch -> technology -> skill), so
    ``skills/<name>/SKILL.md`` is only correct for flat legacy skills.
    """
    rel = str(skill.get("path") or skill.get("name") or "").strip()
    if not rel:
        return None
    candidate = (_skills_dir() / rel / "SKILL.md").resolve()
    try:
        candidate.relative_to(_skills_dir().resolve())
    except ValueError:
        return None  # never read outside the library
    return candidate if candidate.is_file() else None


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


def _render_skill(skill: dict) -> str | None:
    """Render one skill as the text the model reads. None if it has no body."""
    skill_name = str(skill["name"])
    source = "bundled" if skill.get("created_by") == "bundled" else str(skill.get("created_by", "user"))
    parts = [
        f"# skill: {skill_name}",
        f"(source: {source}; triggers: {', '.join(skill.get('triggers', []) or [])})",
    ]

    body = ""
    support_note = ""
    skill_md = _skill_file(skill)
    if skill.get("created_by") == "bundled" and skill_md is not None:
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

    if str(skill.get("phase", "always")) == "planning":
        parts.append(
            "PLANNING SKILL — apply it while shaping the plan / todo list. "
            "Do not keep re-reading it mid-execution."
        )

    body = (body or "").strip()
    if not body:
        return None

    _manager().record_usage(skill_name, "view")
    parts.append(body)
    if support_note:
        parts.append(support_note)
    return "\n\n".join(parts)


@tool
def skill_view(name: str) -> str:
    """Load one or more skills' full instructions into context — take every
    book the task needs, not just one: a plan that touches a framework and its
    testing strategy wants both. Then follow what you read.

    Returns each skill body (frontmatter stripped) and, for bundled skills, the
    skill folder's supporting files (scripts, references, templates). Covers
    bundled SKILL.md skills and user-created skills alike.

    Args:
        name: one skill name, or several separated by commas/spaces, exactly as
            they appear in the library — e.g.
            "fastapi-architect, react-testing-architect".
    """
    raw = (name or "").strip()
    if not raw:
        return "skill_view error: name is required (skills_list to browse the library)"

    requested: list[str] = []
    for token in re.split(r"[,;\s]+", raw):
        token = token.strip()
        if token and token not in requested:
            requested.append(token)

    if len(requested) > _MAX_BOOKS_PER_VIEW:
        extra = requested[_MAX_BOOKS_PER_VIEW:]
        requested = requested[:_MAX_BOOKS_PER_VIEW]
        overflow = (
            f"\n\nNot opened (limit {_MAX_BOOKS_PER_VIEW} books per call): "
            + ", ".join(extra)
            + " — call skill_view again for these if the plan needs them."
        )
    else:
        overflow = ""

    rendered: list[str] = []
    errors: list[str] = []
    for token in requested:
        skill = _find(token)
        if skill is None:
            errors.append(token)
            continue
        text = _render_skill(skill)
        if text is None:
            errors.append(f"{token} (empty body)")
            continue
        rendered.append(text)

    if not rendered:
        names = sorted(
            str(s.get("name", ""))
            for s in _manager().list_skills()
            if s.get("enabled", True) and s.get("state") != "archived"
        )
        shown = ", ".join(names[:_MAX_LISTED_NAMES])
        if len(names) > _MAX_LISTED_NAMES:
            shown += ", ..."
        missing = ", ".join(errors)
        return f"skill_view error: no skill named {missing}. Available: {shown}"

    out = "\n\n---\n\n".join(rendered)
    if len(out) > _MAX_VIEW_CHARS:
        out = out[:_MAX_VIEW_CHARS] + "\n\n[... skill_view budget reached — open the rest separately]"
    if errors:
        out += "\n\nSkipped (not found): " + ", ".join(errors)
    return out + overflow


@tool
def skills_list(shelf: str = "") -> str:
    """Browse the skills library — shelves first, then the books on them.
    Take as many books as the plan needs with skill_view("a, b, c").

    The library is a tree: domain -> branch -> technology -> skill. Call with no
    argument to see the top-level shelves, then call again with a shelf path to
    see what is on it. Open one book with skill_view(name).

    Args:
        shelf: shelf path to browse, e.g. "website-architect" or
            "website-architect/backend-development-architect/python-architect".
            Empty browses the library root.
    """
    manager = _manager()
    shelf = (shelf or "").strip().strip("/")

    shelves: set[str] = set()
    books: list[dict] = []
    for s in manager.list_skills():
        name = str(s.get("name", ""))
        if not name:
            continue
        path = str(s.get("path") or name)
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if parent == shelf:
            books.append(s)
        elif parent.startswith(shelf + "/") if shelf else parent:
            # First path segment below the requested shelf.
            rest = parent[len(shelf) + 1:] if shelf else parent
            segment = rest.split("/", 1)[0]
            if segment:
                shelves.add(segment)

    # A shelf may itself be a skill (the branch/language skill): it belongs on
    # its own listing, first, above the books underneath it.
    if shelf:
        own = [s for s in manager.list_skills() if str(s.get("path") or "") == shelf]
        books = own + books

    lines: list[str] = []
    if shelves:
        header = f"Shelves in {shelf}/" if shelf else "Shelves:"
        lines.append(header)
        lines.extend(f"- {seg}/" for seg in sorted(shelves))
    if books:
        if lines:
            lines.append("")
        header = f"Skills in {shelf}/" if shelf else "Skills at the library root:"
        lines.append(header)
        for s in sorted(books, key=lambda x: str(x.get("name", ""))):
            flags = []
            if not s.get("enabled", True):
                flags.append("disabled")
            if s.get("state") == "archived":
                flags.append("archived")
            flag_txt = f" [{' '.join(flags)}]" if flags else ""
            desc = str(s.get("description") or "").strip()
            if len(desc) > 160:
                desc = desc[:157].rstrip() + "..."
            lines.append(f"- {s['name']}{flag_txt}" + (f" — {desc}" if desc else ""))

    if not lines:
        hint = f"No shelf or skill at {shelf!r}. " if shelf else ""
        return hint + "Browse from the root with skills_list()."

    trailer = (
        "\n\nOpen one with skill_view(name) — read it, then follow it.\n"
        "Architect skills are planning instruments: take one when you are "
        "producing a plan or a todo list, not while executing the steps."
    )
    return "\n".join(lines) + trailer


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
        try:
            from src.agents.skills_hub import notify_skills_changed
            notify_skills_changed()
        except Exception:
            pass
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
    try:
        from src.agents.skills_hub import notify_skills_changed
        notify_skills_changed()
    except Exception:
        pass
    return (
        f"{verb}: {name} (triggers: {', '.join(trigger_list)}). "
        f"It now appears in the skills index; future sessions matching those triggers "
        f"will be pointed at it.{note}"
    )


SKILL_TOOLS = (skills_list, skill_view, skill_manage)
