"""Skills index for the system prompt — port of ``build_skills_system_prompt``.

Keeps upstream's machinery exactly: a two-layer cache (in-process LRU keyed by
``(skills_dir, tools, toolsets, hidden)`` + a disk snapshot validated by an
mtime/size manifest), per-skill frontmatter parsing, platform/environment
gating, category grouping with a names-only demotion tier, and the rendered
``<available_skills>`` block.

One Crusor deviation, documented in ``PROVENANCE.md``: upstream tells the model
to *pull* a skill with ``skill_view(name)``. Crusor has no skill tool — its
runtime injects the bodies of relevant skills (``SkillManager`` feeds
``ContextEngine._skills_layer``) — so the load sentence is rendered from
:data:`SKILLS_POINTER_MODE`, chosen on whether the session's toolset actually
contains the tool. When it does, the upstream sentence is used byte-for-byte.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from src.prompts.hermes.guidance import SKILLS_PROMPT_CACHE_MAX, SKILLS_SNAPSHOT_VERSION

logger = logging.getLogger(__name__)

_SKILLS_PROMPT_CACHE: "OrderedDict[tuple, str]" = OrderedDict()
_SKILLS_PROMPT_CACHE_LOCK = threading.Lock()

EXCLUDED_SKILL_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
SKILL_SUPPORT_DIRS = {"references", "assets", "scripts", "templates"}

_UPSTREAM_LOAD_SENTENCE = (
    "Before replying, scan the skills below. If a skill matches or is even partially "
    "relevant to your task, you MUST load it with skill_view(name) and follow its instructions. "
    "Err on the side of loading — it is always better to have context you don't need "
    "than to miss critical steps, pitfalls, or established workflows. "
    "Skills contain specialized knowledge — API endpoints, tool-specific commands, "
    "and proven workflows that outperform general-purpose approaches. Load the skill "
)
_PATCH_SENTENCE = "If a skill has issues, fix it with skill_manage(action='patch').\n"
_HUB_SENTENCE = (
    "Missing a capability the index doesn't cover? Search the Skills Hub with "
    "hub_search and install it with hub_install — installs are SHA-pinned and "
    "sandboxed, and the skill appears in this index immediately.\n"
)


def _injected_load_sentence(basic_tools: str) -> str:
    return (
        "Before replying, scan the skills below. A skill that matches or is even "
        "partially relevant to your task encodes proven workflow — API endpoints, "
        "tool-specific commands, quality standards — that outperforms "
        f"general-purpose approaches with basic tools like {basic_tools}. "
    )


def _skills_prompt_snapshot_path(home: Path) -> Path:
    return home / ".skills_prompt_snapshot.json"


def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """``---`` delimited YAML-ish frontmatter → (metadata, body)."""
    meta: Dict[str, str] = {}
    if not content.startswith("---"):
        return meta, content
    end = content.find("\n---", 3)
    if end == -1:
        return meta, content
    raw = content[3:end].strip("\n")
    body = content[end + 4:].lstrip("\n")
    key = None
    for line in raw.splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match:
            key, value = match.group(1), match.group(2).strip().strip("'\"")
            meta[key.lower()] = value
        elif key and line.startswith((" ", "\t")):
            meta[key.lower()] = f"{meta[key.lower()]} {line.strip()}".strip()
    return meta, body


def extract_skill_description(meta: Dict[str, str], body: str) -> str:
    desc = meta.get("description", "")
    if desc:
        return desc
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:160]
    return ""


def skill_matches_platform(meta: Dict[str, str]) -> bool:
    platforms = meta.get("platforms", "").lower()
    if not platforms or platforms in {"all", "any"}:
        return True
    current = {"linux": "linux", "darwin": "macos", "win32": "windows"}.get(os.name if hasattr(os, "name") else "", "")
    try:
        import platform as _platform

        current = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(_platform.system(), "")
    except Exception:
        pass
    return not current or current in platforms


def _parse_skill_file(skill_file: Path) -> Tuple[bool, Dict[str, str], str]:
    try:
        content = skill_file.read_text(encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not read skill %s: %s", skill_file, exc)
        return False, {}, ""
    meta, body = parse_frontmatter(content)
    name = meta.get("name") or skill_file.parent.name
    description = extract_skill_description(meta, body)
    return True, {"name": name, "description": description, **meta}, body


def _build_skills_manifest(skills_dir: Path) -> Dict[str, List[int]]:
    """(relpath → [mtime, size]) over indexed skill files — the snapshot guard."""
    manifest: Dict[str, List[int]] = {}
    if not skills_dir.exists():
        return manifest
    for skill_file in iter_skill_index_files(skills_dir):
        try:
            stat = skill_file.stat()
        except Exception:
            continue
        manifest[str(skill_file.relative_to(skills_dir))] = [int(stat.st_mtime), int(stat.st_size)]
    return manifest


def iter_skill_index_files(skills_dir: Path) -> Iterable[Path]:
    if not skills_dir.exists():
        return []
    found: List[Path] = []
    for category in sorted(p for p in skills_dir.iterdir() if p.is_dir() and p.name not in EXCLUDED_SKILL_DIRS):
        if category.name in SKILL_SUPPORT_DIRS or category.name.startswith("."):
            continue
        for name in ("SKILL.md", "skill.md"):
            candidate = category / name
            if candidate.is_file():
                found.append(candidate)
                break
        for nested in sorted(category.glob("*/SKILL.md")):
            found.append(nested)
    return found


def _load_skills_snapshot(skills_dir: Path, home: Path) -> Optional[dict]:
    path = _skills_prompt_snapshot_path(home)
    if not path.exists():
        return None
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(snapshot, dict) or snapshot.get("version") != SKILLS_SNAPSHOT_VERSION:
        return None
    if snapshot.get("manifest") != _build_skills_manifest(skills_dir):
        return None
    return snapshot


def _write_skills_snapshot(skills_dir: Path, home: Path, entries: List[dict]) -> None:
    try:
        path = _skills_prompt_snapshot_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": SKILLS_SNAPSHOT_VERSION,
                    "manifest": _build_skills_manifest(skills_dir),
                    "entries": entries,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("Could not write skills snapshot: %s", exc)


def clear_skills_system_prompt_cache(*, clear_snapshot: bool = False, home: Optional[Path] = None) -> None:
    with _SKILLS_PROMPT_CACHE_LOCK:
        _SKILLS_PROMPT_CACHE.clear()
    if clear_snapshot and home is not None:
        try:
            _skills_prompt_snapshot_path(Path(home)).unlink()
        except Exception:
            pass


def _collect_skills(skills_dir: Path, home: Path) -> List[Dict[str, str]]:
    snapshot = _load_skills_snapshot(skills_dir, home)
    if snapshot and isinstance(snapshot.get("entries"), list):
        return [e for e in snapshot["entries"] if isinstance(e, dict)]

    entries: List[Dict[str, str]] = []
    for skill_file in iter_skill_index_files(skills_dir):
        ok, meta, _body = _parse_skill_file(skill_file)
        if not ok or not meta.get("name"):
            continue
        if not skill_matches_platform(meta):
            continue
        category = meta.get("category") or skill_file.parent.parent.name
        entries.append(
            {
                "name": meta["name"],
                "description": meta.get("description", ""),
                "category": category,
                "hidden": "1" if meta.get("hidden", "").lower() in {"1", "true", "yes"} else "0",
            }
        )
    _write_skills_snapshot(skills_dir, home, entries)
    return entries


def _user_skill_entries() -> List[Dict[str, str]]:
    """Discovery entries for SkillManager's user/agent-created skills.

    The dir tree only carries bundled ``skills/<name>/SKILL.md``; without this
    merge a user-created skill would never appear in ``<available_skills>``,
    so the model could not discover it to pull it with ``skill_view``.
    Bundled entries are excluded — they already come from the dir tree.
    """
    try:
        from src.agents.skill_manager import skill_manager

        out: List[Dict[str, str]] = []
        for s in skill_manager.list_skills():
            if s.get("created_by") == "bundled":
                continue
            if not s.get("enabled", True) or s.get("state") == "archived":
                continue
            name = str(s.get("name", "")).strip()
            if not name:
                continue
            desc = str(s.get("description", "") or "").strip()
            if not desc:
                # Agent-Skills discovery is name + description; user skills
                # created before descriptions existed fall back to triggers.
                desc = ", ".join(str(t) for t in (s.get("triggers", []) or [])[:6])
            out.append({"name": name, "description": desc, "category": "user"})
        return out
    except Exception:
        return []


def _skills_lead(tools: Optional[Iterable[str]], basic_tools: str) -> str:
    """The paragraph above ``<available_skills>`` — one source of truth for
    both index sources. With ``skill_view`` bound it is the upstream/Copilot
    pull sentence ("load it with skill_view(name)"); without it, Crusor's
    eager-injection sentence stays truthful."""
    tools_set = None if tools is None else {str(t) for t in tools}
    has_skill_view = bool(tools_set) and "skill_view" in tools_set
    if has_skill_view:
        return _UPSTREAM_LOAD_SENTENCE + (
            f"even if you think you could handle the task with basic tools like {basic_tools}. "
            "Skills also encode the user's preferred approach, conventions, and quality standards "
            "for tasks like code review, planning, and testing — load them even for tasks you "
            "already know how to do, because the skill defines how it should be done here.\n"
            + (_PATCH_SENTENCE if tools_set is not None and "skill_manage" in tools_set else "")
            + (_HUB_SENTENCE if tools_set is not None and "hub_install" in tools_set else "")
        )
    return (
        _injected_load_sentence(basic_tools)
        + "Skills also encode the user's preferred approach, conventions, and quality "
        "standards — the runtime injects the body of any skill relevant to the current "
        "task later in this prompt, so treat the index as the map of what is known here.\n"
    )


# -- prompt-budget for the index -------------------------------------------
# MEASURED COST (2026-10-31): with the installed skill tree (241 SKILL.md
# files, 240 enabled) the index rendered here is 76,270 chars = 19,078 tokens,
# i.e. 86.5% of the whole assembled system prompt (22,066 tokens), and it is
# re-sent on EVERY provider call of EVERY turn (budget.py allows 20-45 calls).
# The demotion tier upstream ships (`compact_categories` -> names-only) was
# never actually driven by any caller, so the index grew without a ceiling.
#
# So it now has one. Over budget, every skill keeps its NAME (discovery is
# never lost) and descriptions are spent cheapest-first, round-robin across
# categories, until the budget is full. Deterministic, cache-safe, and honest:
# a footer states how many entries were trimmed and how to load one.
DEFAULT_SKILLS_INDEX_MAX_TOKENS = 3000
_CHARS_PER_TOKEN = 4  # the same ~chars/4 contract as tokenizer_fallback


def skills_index_token_budget() -> int:
    """Token ceiling for the rendered index; 0 disables budgeting (legacy).

    Read per call (the standing env rule): rotating the value must not
    require a process restart.
    """
    raw = (os.environ.get("CRUSORAI_SKILLS_INDEX_MAX_TOKENS") or "").strip()
    if not raw:
        return DEFAULT_SKILLS_INDEX_MAX_TOKENS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_SKILLS_INDEX_MAX_TOKENS


def _entry_name(line: str) -> str:
    body = line.strip()
    if body.startswith("- "):
        body = body[2:]
    return body.split(":", 1)[0].strip()


def _category_of(lines: List[str]) -> str:
    """Category a rendered entry belongs to ('' for the flat SkillManager list)."""
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("- "):
            return stripped[:-1]
    return ""


def _entries_budget(lead: str) -> int:
    """Budget for the entry list alone: the ceiling MINUS the fixed scaffolding.

    The env knob is documented as the ceiling for the whole skills block, so the
    lead sentence, the tags and the trim footer are charged against it — a
    budget that only governed the entries would silently overshoot by ~600
    tokens every call.
    """
    budget = skills_index_token_budget()
    if budget <= 0:
        return 0
    overhead = (len(lead) // _CHARS_PER_TOKEN) + 40  # tags + trim footer allowance
    return max(200, budget - overhead)


def apply_skills_index_budget(
    index_lines: List[str], max_tokens: int | None = None
) -> tuple[List[str], int]:
    """Trim ``index_lines`` to ``max_tokens`` (approx) by name-demoting entries.

    Returns (lines, trimmed_count). ``max_tokens <= 0`` returns the input
    untouched, which is the legacy behaviour and the rollback switch.
    """
    budget = skills_index_token_budget() if max_tokens is None else max_tokens
    if budget <= 0 or not index_lines:
        return index_lines, 0
    budget_chars = budget * _CHARS_PER_TOKEN
    total_chars = sum(len(line) + 1 for line in index_lines)
    if total_chars <= budget_chars:
        return index_lines, 0

    # Phase 1 — the floor: names only. Discovery must survive any budget.
    # A names-only row for a long description is ~30 chars; the floor cost is
    # computed from the REAL names so a small budget is reported honestly
    # rather than silently dropping skills.
    slots: list[dict] = []
    for line in index_lines:
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("- "):
            slots.append({"kind": "category", "line": line, "category": stripped[:-1]})
        elif stripped.startswith("- "):
            name = _entry_name(line)
            slots.append(
                {
                    "kind": "entry",
                    "name": name,
                    "full": line,
                    "name_only": f"    - {name}",
                    "desc_chars": max(0, len(line) - len(name) - 8),
                    "category": "",
                }
            )
    current_category = ""
    for slot in slots:
        if slot["kind"] == "category":
            current_category = slot["category"]
        elif slot["kind"] == "entry":
            slot["category"] = current_category

    floor = sum(
        len(s["line"] if s["kind"] == "category" else s["name_only"]) + 1 for s in slots
    )
    if floor > budget_chars:
        # Even names do not fit: keep the alphabetically first N names and say so.
        kept: list[str] = []
        used = 0
        dropped = 0
        for slot in slots:
            if slot["kind"] != "entry":
                continue
            row = slot["name_only"]
            if used + len(row) + 1 > budget_chars:
                dropped += 1
                continue
            kept.append(row)
            used += len(row) + 1
        footer = (
            f"(Skills index truncated to {len(kept)} of {len(kept) + dropped} names "
            f"to fit the prompt budget — use hub_search to find others.)"
        )
        return kept + [footer], dropped

    # Phase 2 — spend what is left on descriptions, cheapest first within each
    # category, round-robin across categories so no single category monopolises
    # the budget (upstream's demotion tier, finally driven).
    by_category: dict[str, list[int]] = {}
    for idx, slot in enumerate(slots):
        if slot["kind"] == "entry":
            by_category.setdefault(slot["category"], []).append(idx)
    for indices in by_category.values():
        indices.sort(key=lambda i: (slots[i]["desc_chars"], slots[i]["name"]))

    remaining = budget_chars - floor
    promoted: set[int] = set()
    order = sorted(by_category)
    cursors = {category: 0 for category in order}
    progressed = True
    while progressed and remaining > 0:
        progressed = False
        for category in order:
            indices = by_category[category]
            cursor = cursors[category]
            if cursor >= len(indices):
                continue
            slot_idx = indices[cursor]
            cursors[category] = cursor + 1
            progressed = True
            extra = len(slots[slot_idx]["full"]) - len(slots[slot_idx]["name_only"])
            if extra <= remaining:
                promoted.add(slot_idx)
                remaining -= extra

    trimmed = sum(1 for i, s in enumerate(slots) if s["kind"] == "entry" and i not in promoted)
    out: list[str] = []
    for idx, slot in enumerate(slots):
        if slot["kind"] == "category":
            out.append(slot["line"])
        else:
            out.append(slot["full"] if idx in promoted else slot["name_only"])
    if trimmed:
        out.append(
            f"({trimmed} of {trimmed + len(promoted)} skills are listed by name only "
            f"to fit the prompt budget — load one with skill_view(name).)"
        )
    return out, trimmed


def build_skills_system_prompt(
    available_tools: Optional[Iterable[str]] = None,
    available_toolsets: Optional[Iterable[str]] = None,
    compact_categories: Optional[Iterable[str]] = None,
    skills_dir_override: Optional[Path] = None,
    home: Optional[Path] = None,
) -> str:
    """Build the compact skill index that rides the front of the volatile band."""
    from src.prompts.hermes.view import crusor_home

    home = Path(home) if home is not None else crusor_home()
    skills_dir = Path(skills_dir_override) if skills_dir_override is not None else home / "skills"
    tools = None if available_tools is None else {str(t) for t in available_tools}
    toolsets = None if available_toolsets is None else {str(t) for t in available_toolsets}
    demoted = frozenset(compact_categories or ())
    # User/agent-created skills live in SkillManager, not the dir tree — merge
    # them into discovery (name + description) so the model can pull them with
    # skill_view like any bundled SKILL.md. Their tuple also keys the cache so
    # add/remove invalidates the rendered index.
    user_entries = _user_skill_entries()
    cache_key = (
        str(skills_dir),
        None if tools is None else tuple(sorted(tools)),
        None if toolsets is None else tuple(sorted(toolsets)),
        tuple(sorted(demoted)),
        tuple((e["name"], e["description"], e["category"]) for e in user_entries),
        # The rendered text now depends on the budget: an env change must not
        # serve a render produced under the old ceiling.
        skills_index_token_budget(),
    )

    with _SKILLS_PROMPT_CACHE_LOCK:
        cached = _SKILLS_PROMPT_CACHE.get(cache_key)
        if cached is not None:
            _SKILLS_PROMPT_CACHE.move_to_end(cache_key)
            return cached

    if not skills_dir.exists():
        # Crusor-managed skills live in SkillManager's store, not a directory
        # tree; render from it when present so the index reflects the real set.
        return _from_skill_manager(tools, demoted, cache_key)

    entries = [e for e in _collect_skills(skills_dir, home) if e.get("hidden") != "1"]
    if not entries:
        return _from_skill_manager(tools, demoted, cache_key)
    dir_names = {str(e.get("name", "")) for e in entries}
    entries = entries + [e for e in user_entries if e["name"] not in dir_names]

    by_category: Dict[str, List[Tuple[str, str]]] = {}
    for entry in entries:
        by_category.setdefault(entry.get("category") or "general", []).append(
            (entry["name"], entry.get("description", ""))
        )

    index_lines: List[str] = []
    for category in sorted(by_category):
        seen: set = set()
        if category in demoted:
            names = sorted({name for name, _ in by_category[category]})
            index_lines.append(f"  {category} [names only]: {', '.join(names)}")
            continue
        index_lines.append(f"  {category}:")
        for name, desc in sorted(by_category[category], key=lambda x: x[0]):
            if name in seen:
                continue
            seen.add(name)
            index_lines.append(f"    - {name}: {desc}" if desc else f"    - {name}")

    basic_tools = "web_search or terminal"
    if tools is not None and "web_search" not in tools:
        basic_tools = "terminal"

    lead = _skills_lead(tools, basic_tools)

    index_lines, _trimmed = apply_skills_index_budget(
        index_lines, max_tokens=_entries_budget(lead)
    )
    result = (
        "## Skills\n"
        + lead
        + "\n"
        + "<available_skills>\n"
        + "\n".join(index_lines)
        + "\n</available_skills>\n\n"
        + "Only proceed without a skill's guidance when genuinely none is relevant to the task."
        + ("\n(Demoted categories above are names-only to fit the prompt budget.)" if demoted else "")
    )

    with _SKILLS_PROMPT_CACHE_LOCK:
        _SKILLS_PROMPT_CACHE[cache_key] = result
        _SKILLS_PROMPT_CACHE.move_to_end(cache_key)
        while len(_SKILLS_PROMPT_CACHE) > SKILLS_PROMPT_CACHE_MAX:
            _SKILLS_PROMPT_CACHE.popitem(last=False)
    return result


def _from_skill_manager(tools, demoted: frozenset, cache_key: tuple) -> str:
    """Render the same block from Crusor's ``SkillManager`` store (no dir tree)."""
    # The PROCESS SINGLETON, not a fresh constructor: every mutating surface
    # (hub ops, skill_manage, the dashboard) mutates the singleton, so the
    # index must read the same in-memory store. A fresh SkillManager() here
    # depended on a silent file round-trip — _save() is fail-open (D17), so
    # one swallowed write error meant a permanently stale index that even
    # notify_skills_changed() could not fix. (Field 2026-10-01.)
    try:  # pyrefly: ignore [missing-import]
        from src.agents.skill_manager import skill_manager

        manager = skill_manager
    except Exception:
        manager = None
    if manager is None:
        try:  # pyrefly: ignore [missing-import]
            from src.agents.skill_manager import SkillManager

            manager = SkillManager()
        except Exception:
            return ""
    try:
        skills = [s for s in manager.list_skills() if s.get("enabled", True)]
    except Exception:
        return ""
    if not skills:
        return ""

    index_lines: List[str] = []
    for skill in sorted(skills, key=lambda s: str(s.get("name", ""))):
        name = str(skill.get("name", "")).strip()
        if not name:
            continue
        desc = str(skill.get("description", "")).strip()
        if not desc:
            desc = ", ".join(str(t) for t in (skill.get("triggers", []) or [])[:6])
        index_lines.append(f"    - {name}: {desc}" if desc else f"    - {name}")

    basic_tools = "web_search or terminal"
    if tools is not None and "web_search" not in tools:
        basic_tools = "terminal"
    lead = _skills_lead(tools, basic_tools)
    # The real path for an installed catalog (240 entries measured at 19,078
    # tokens) — the budget is applied here, before caching, so the cached
    # value is already trimmed.
    index_lines, _trimmed = apply_skills_index_budget(
        index_lines, max_tokens=_entries_budget(lead)
    )
    result = (
        "## Skills\n"
        + lead
        + "\n"
        + "<available_skills>\n"
        + "\n".join(index_lines)
        + "\n</available_skills>\n\n"
        + "Only proceed without a skill's guidance when genuinely none is relevant to the task."
    )
    with _SKILLS_PROMPT_CACHE_LOCK:
        _SKILLS_PROMPT_CACHE[cache_key] = result
        _SKILLS_PROMPT_CACHE.move_to_end(cache_key)
        while len(_SKILLS_PROMPT_CACHE) > SKILLS_PROMPT_CACHE_MAX:
            _SKILLS_PROMPT_CACHE.popitem(last=False)
    return result


__all__ = [
    "DEFAULT_SKILLS_INDEX_MAX_TOKENS",
    "apply_skills_index_budget",
    "build_skills_system_prompt",
    "skills_index_token_budget",
    "clear_skills_system_prompt_cache",
    "extract_skill_description",
    "parse_frontmatter",
    "skill_matches_platform",
]
