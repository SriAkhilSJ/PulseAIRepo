"""Skills index for the system prompt — port of ``build_skills_system_prompt``.

Keeps upstream's machinery exactly: a two-layer cache (in-process LRU keyed by
``(skills_dir, tools, toolsets, hidden)`` + a disk snapshot validated by an
mtime/size manifest), per-skill frontmatter parsing, platform/environment
gating, category grouping with a names-only demotion tier, and the rendered
``<available_skills>`` block.

One Pulse deviation, documented in ``PROVENANCE.md``: upstream tells the model
to *pull* a skill with ``skill_view(name)``. Pulse has no skill tool — its
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


def build_skills_system_prompt(
    available_tools: Optional[Iterable[str]] = None,
    available_toolsets: Optional[Iterable[str]] = None,
    compact_categories: Optional[Iterable[str]] = None,
    skills_dir_override: Optional[Path] = None,
    home: Optional[Path] = None,
) -> str:
    """Build the compact skill index that rides the front of the volatile band."""
    from src.prompts.hermes.view import pulse_home

    home = Path(home) if home is not None else pulse_home()
    skills_dir = Path(skills_dir_override) if skills_dir_override is not None else home / "skills"
    tools = None if available_tools is None else {str(t) for t in available_tools}
    toolsets = None if available_toolsets is None else {str(t) for t in available_toolsets}
    demoted = frozenset(compact_categories or ())
    cache_key = (str(skills_dir), None if tools is None else tuple(sorted(tools)), None if toolsets is None else tuple(sorted(toolsets)), tuple(sorted(demoted)))

    with _SKILLS_PROMPT_CACHE_LOCK:
        cached = _SKILLS_PROMPT_CACHE.get(cache_key)
        if cached is not None:
            _SKILLS_PROMPT_CACHE.move_to_end(cache_key)
            return cached

    if not skills_dir.exists():
        # Pulse-managed skills live in SkillManager's store, not a directory
        # tree; render from it when present so the index reflects the real set.
        return _from_skill_manager(tools, demoted, cache_key)

    entries = [e for e in _collect_skills(skills_dir, home) if e.get("hidden") != "1"]
    if not entries:
        return _from_skill_manager(tools, demoted, cache_key)

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

    basic_tools = "web_search or run_terminal"
    if tools is not None and "web_search" not in tools:
        basic_tools = "run_terminal"

    has_skill_view = bool(tools) and "skill_view" in (tools or set())
    if has_skill_view:
        lead = _UPSTREAM_LOAD_SENTENCE + (
            f"even if you think you could handle the task with basic tools like {basic_tools}. "
            "Skills also encode the user's preferred approach, conventions, and quality standards "
            "for tasks like code review, planning, and testing — load them even for tasks you "
            "already know how to do, because the skill defines how it should be done here.\n"
            + (_PATCH_SENTENCE if tools is not None and "skill_manage" in tools else "")
        )
    else:
        lead = (
            _injected_load_sentence(basic_tools)
            + "Skills also encode the user's preferred approach, conventions, and quality "
            "standards — the runtime injects the body of any skill relevant to the current "
            "task later in this prompt, so treat the index as the map of what is known here.\n"
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
    """Render the same block from Pulse's ``SkillManager`` store (no dir tree)."""
    try:  # pyrefly: ignore [missing-import]
        from src.agents.skill_manager import SkillManager

        manager = SkillManager()
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
        index_lines.append(f"    - {name}: {desc}" if desc else f"    - {name}")

    basic_tools = "web_search or run_terminal"
    if tools is not None and "web_search" not in tools:
        basic_tools = "run_terminal"
    result = (
        "## Skills\n"
        + _injected_load_sentence(basic_tools)
        + "The runtime injects the body of any skill relevant to the current task later in this "
        "prompt; treat the index below as the map of what is known about this workspace.\n\n"
        "<available_skills>\n"
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
    "build_skills_system_prompt",
    "clear_skills_system_prompt_cache",
    "extract_skill_description",
    "parse_frontmatter",
    "skill_matches_platform",
]
