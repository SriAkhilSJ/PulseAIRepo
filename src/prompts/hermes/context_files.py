"""Context-file discovery — pin-to-pin port of ``agent/prompt_builder.py``.

Covers: injection scanning, git-root walking, ``.pulse.md`` discovery, YAML
frontmatter stripping, the AGENTS.md directory chain with per-directory
override precedence, CLAUDE.md, ``.cursorrules``/``.cursor/rules/*.mdc``, the
scaled character cap, and head/tail truncation with a recovery pointer.

Two Pulse-side bindings, both mechanical:

* the scanner is Pulse's own threat library (``src/context/threat_patterns.py``,
  scope ``context``) rather than upstream's copy;
* ``.hermes.md`` becomes ``.pulse.md``, and Pulse's ``.pulseai/instructions.md``
  loader rides the same section list (deduplicated by content, so a file that
  is also discovered by the chain can never appear twice).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from src.prompts.hermes import guidance

logger = logging.getLogger(__name__)

try:  # pyrefly: ignore [missing-import]
    from src.context.threat_patterns import scan_for_threats as _scan_for_threats
except Exception:  # bare environment / partial install: fail open like upstream's guard
    _scan_for_threats = None


# =========================================================================
# Scanning and path helpers
# =========================================================================


def _scan_context_content(content: str, filename: str) -> str:
    """Scan context file content for injection. Returns sanitized content.

    Uses the "context" scope from the shared threat-pattern library, which
    covers classic injection + promptware/C2 patterns + role-play hijack.
    Strict-scope patterns (SSH backdoor, persistence, exfil-URL) are NOT
    applied here — those are too aggressive for a context file in a cloned
    repo. When a match is found the content is BLOCKED with a placeholder: it
    never reaches the model, and the user still sees why.
    """
    # Editors (Windows Notepad, PowerShell Out-File without -Encoding
    # utf8NoBOM, some VS Code profiles) prefix a UTF-8 BOM as an encoding
    # artifact, not a prompt injection. Strip a leading U+FEFF silently so a
    # context file is not blocked wholesale; BOMs elsewhere stay subject to
    # the scan below.
    if content.startswith("\ufeff"):
        content = content[1:]

    if _scan_for_threats is None:
        return content

    findings = _scan_for_threats(content, scope="context")
    if findings:
        logger.warning("Context file %s blocked: %s", filename, ", ".join(findings))
        return (
            f"[BLOCKED: {filename} contained potential prompt injection "
            f"({', '.join(findings)}). Content not loaded.]"
        )
    return content


def find_git_root(start: Path) -> Optional[Path]:
    """Walk *start* and its parents for a ``.git`` directory; None at the root."""
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return None


PULSE_MD_NAMES = (".pulse.md", "PULSE.md")


def find_pulse_md(cwd: Path) -> Optional[Path]:
    """Discover the nearest ``.pulse.md`` / ``PULSE.md``.

    Search order: *cwd* first, then each parent up to (and including) the git
    repository root. With no git root only *cwd* is checked — walking parents
    could pick up a planted file in ``/tmp`` or ``/home``.
    """
    stop_at = find_git_root(cwd)
    current = cwd.resolve()
    search_dirs = [current, *current.parents] if stop_at else [current]

    for directory in search_dirs:
        for name in PULSE_MD_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        if stop_at and directory == stop_at:
            break
    return None


def strip_yaml_frontmatter(content: str) -> str:
    """Remove optional YAML frontmatter (``---`` delimited) from *content*."""
    content = content.lstrip("\ufeff")  # tolerate UTF-8 BOM (Windows editors)
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            body = content[end + 4:].lstrip("\n")
            return body if body else content
    return content


def truncate_content(
    content: str,
    filename: str,
    max_chars: Optional[int] = None,
    context_length: Optional[int] = None,
    read_path: Optional[str] = None,
) -> str:
    """Head/tail truncation with a marker in the middle (upstream's shape)."""
    if max_chars is None:
        max_chars = guidance.get_context_file_max_chars(context_length)
    if len(content) <= max_chars:
        return content
    target = read_path or filename
    msg = (
        f"⚠️  Context file {filename} TRUNCATED: "
        f"{len(content)} chars exceeds limit of {max_chars} — "
        f"trim the file, pin a larger context_file_max_chars, or use a "
        f"larger-context model!"
    )
    logger.warning(msg)
    guidance.record_truncation_warning(msg)
    head_chars = int(max_chars * guidance.CONTEXT_TRUNCATE_HEAD_RATIO)
    tail_chars = int(max_chars * guidance.CONTEXT_TRUNCATE_TAIL_RATIO)
    head = content[:head_chars]
    tail = content[-tail_chars:]
    marker = (
        f"\n\n[...truncated {filename}: kept {head_chars}+{tail_chars} of "
        f"{len(content)} chars. The middle is omitted — if you need the full "
        f"instructions, read the complete file with the read_file tool: "
        f"{target}]\n\n"
    )
    return head + marker + tail


# =========================================================================
# Per-source loaders
# =========================================================================


def load_pulse_md(cwd_path: Path, context_length: Optional[int] = None) -> str:
    """``.pulse.md`` / ``PULSE.md`` — walk to git root."""
    path = find_pulse_md(cwd_path)
    if not path:
        return ""
    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return ""
        content = strip_yaml_frontmatter(content)
        rel = path.name
        try:
            rel = str(path.relative_to(cwd_path))
        except ValueError:
            pass
        content = _scan_context_content(content, rel)
        result = f"## {rel}\n\n{content}"
        return truncate_content(result, ".pulse.md", context_length=context_length, read_path=str(path))
    except Exception as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return ""


def agents_md_directory_chain(cwd_path: Path) -> List[Path]:
    """Directories to check for AGENTS.md: git root first, cwd last."""
    git_root = find_git_root(cwd_path)
    resolved = cwd_path.resolve()
    if git_root is None:
        return [resolved]
    chain: List[Path] = []
    current = resolved
    while True:
        chain.append(current)
        if current == git_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return list(reversed(chain))


def load_agents_md(cwd_path: Path, context_length: Optional[int] = None) -> str:
    """AGENTS.md — merged directory chain from git root down to cwd.

    Each directory contributes its ``AGENTS.override.md`` / ``AGENTS.md`` /
    ``agents.md`` (first name wins per directory) as its own provenance-labelled
    section. The override file wins so a developer can keep a personal,
    gitignored override beside the tracked project instructions. Identical
    content further down the chain is deduplicated.
    """
    cwd_resolved = cwd_path.resolve()
    sections: List[str] = []
    seen_content: set = set()
    for directory in agents_md_directory_chain(cwd_resolved):
        for name in ["AGENTS.override.md", "AGENTS.md", "agents.md"]:
            candidate = directory / name
            if not candidate.exists():
                continue
            try:
                content = candidate.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.debug("Could not read %s: %s", candidate, exc)
                continue
            if not content:
                continue
            if content in seen_content:
                break
            seen_content.add(content)
            label = name if directory == cwd_resolved else os.path.relpath(candidate, cwd_resolved)
            scanned = _scan_context_content(content, label)
            section = f"## {label}\n\n{scanned}"
            sections.append(
                truncate_content(section, label, context_length=context_length, read_path=str(candidate))
            )
            break
    if not sections:
        return ""
    if len(sections) == 1:
        return sections[0]
    merged = "\n\n".join(sections)
    return truncate_content(
        merged,
        "AGENTS.md (directory chain)",
        context_length=context_length,
        read_path=str(cwd_resolved / "AGENTS.md"),
    )


def load_claude_md(cwd_path: Path, context_length: Optional[int] = None) -> str:
    """CLAUDE.md / claude.md — cwd only."""
    for name in ["CLAUDE.md", "claude.md"]:
        candidate = cwd_path / name
        if candidate.exists():
            try:
                content = candidate.read_text(encoding="utf-8").strip()
                if content:
                    content = _scan_context_content(content, name)
                    result = f"## {name}\n\n{content}"
                    return truncate_content(result, "CLAUDE.md", context_length=context_length, read_path=str(candidate))
            except Exception as exc:
                logger.debug("Could not read %s: %s", candidate, exc)
    return ""


def load_cursorrules(cwd_path: Path, context_length: Optional[int] = None) -> str:
    """.cursorrules + .cursor/rules/*.mdc — cwd only."""
    cursorrules_content = ""
    cursorrules_file = cwd_path / ".cursorrules"
    if cursorrules_file.exists():
        try:
            content = cursorrules_file.read_text(encoding="utf-8").strip()
            if content:
                content = _scan_context_content(content, ".cursorrules")
                cursorrules_content += f"## .cursorrules\n\n{content}\n\n"
        except Exception as exc:
            logger.debug("Could not read .cursorrules: %s", exc)

    cursor_rules_dir = cwd_path / ".cursor" / "rules"
    if cursor_rules_dir.exists() and cursor_rules_dir.is_dir():
        for mdc_file in sorted(cursor_rules_dir.glob("*.mdc")):
            try:
                content = mdc_file.read_text(encoding="utf-8").strip()
                if content:
                    content = _scan_context_content(content, f".cursor/rules/{mdc_file.name}")
                    cursorrules_content += f"## .cursor/rules/{mdc_file.name}\n\n{content}\n\n"
            except Exception as exc:
                logger.debug("Could not read %s: %s", mdc_file, exc)

    if not cursorrules_content:
        return ""
    return truncate_content(
        cursorrules_content,
        ".cursorrules",
        context_length=context_length,
        read_path=str(cwd_path / ".cursorrules"),
    )


def load_soul_md(context_length: Optional[int] = None, home_override: Optional[Path] = None) -> Optional[str]:
    """Load ``SOUL.md`` from the Pulse home and return its content, or None.

    Slot #1 of the system prompt (the identity). When this returns content,
    :func:`build_context_files_prompt` runs with ``skip_soul=True`` so the file
    is not injected twice. Scoping to an explicit home matters: ambient
    resolution on a worker thread can read the *launch* profile's SOUL.md.
    """
    from src.prompts.hermes.view import pulse_home

    home = Path(home_override) if home_override is not None else pulse_home()
    soul_path = home / "SOUL.md"
    if not soul_path.exists():
        return None
    try:
        content = soul_path.read_text(encoding="utf-8").strip()
        if not content:
            return None
        content = _scan_context_content(content, "SOUL.md")
        return truncate_content(content, "SOUL.md", context_length=context_length, read_path=str(soul_path))
    except Exception as exc:
        logger.debug("Could not read SOUL.md: %s", exc)
        return None


def _is_install_tree(path: Path) -> bool:
    """True when *path* is the PulseAIRepo checkout itself (source tree)."""
    marker = Path(__file__).resolve().parents[3]
    try:
        return path.resolve() == marker
    except Exception:
        return False


def _pulseai_instructions(
    cwd_path: Path,
    context_length: Optional[int] = None,
    already_loaded: Optional[set] = None,
) -> List[str]:
    """Pulse's ``.pulseai/instructions.md`` loader, as labelled sections.

    Pulse's own loader also folds in ``AGENTS.md``, which the upstream priority
    chain may already have injected — so each file is emitted separately and any
    path or content already present is skipped. Double-injecting one instruction
    file is both a token tax and a cache hazard.
    """
    seen_paths = {str(p) for p in (already_loaded or ())}
    seen_content: set = set()
    try:  # pyrefly: ignore [missing-import]
        from src.context.custom_instructions import get_custom_instructions_loader

        files = list(get_custom_instructions_loader().load_instructions(str(cwd_path)))
    except Exception as exc:
        logger.debug("Custom instructions unavailable: %s", exc)
        return []

    sections: List[str] = []
    for instr in files:
        path = str(getattr(instr, "path", "") or "")
        content = str(getattr(instr, "content", "") or "").strip()
        if not content or path in seen_paths or content in seen_content:
            continue
        seen_content.add(content)
        try:
            label = os.path.relpath(path, cwd_path)
        except Exception:
            label = os.path.basename(path)
        scanned = _scan_context_content(content, label)
        sections.append(
            truncate_content(
                f"## {label}\n\n{scanned}",
                label,
                context_length=context_length,
                read_path=path,
            )
        )
    return sections


def _find_project_context(cwd_path: Path, context_length: Optional[int]) -> tuple:
    """Run the upstream priority chain, reporting which file satisfied it."""
    for loader in (load_pulse_md, load_agents_md, load_claude_md, load_cursorrules):
        if loader is load_pulse_md:
            found = find_pulse_md(cwd_path)
            if found is None:
                continue
            return loader(cwd_path, context_length), {str(found)}
        text = loader(cwd_path, context_length)
        if text:
            return text, _paths_for(loader, cwd_path)
    return "", set()


def _paths_for(loader, cwd_path: Path) -> set:
    """Real paths a chain loader consumed — for dedupe against Pulse's loader."""
    names: List[str] = []
    if loader is load_agents_md:
        names = ["AGENTS.override.md", "AGENTS.md", "agents.md"]
    elif loader is load_claude_md:
        names = ["CLAUDE.md", "claude.md"]
    elif loader is load_cursorrules:
        names = [".cursorrules"]
    found = set()
    for name in names:
        candidate = cwd_path / name
        if candidate.exists():
            found.add(str(candidate))
    if loader is load_agents_md:
        for directory in agents_md_directory_chain(cwd_path):
            for name in names:
                candidate = directory / name
                if candidate.exists():
                    found.add(str(candidate))
                    break
    return found


_CHAIN_CANDIDATE_NAMES = (
    ".pulse.md", "PULSE.md",
    "AGENTS.override.md", "AGENTS.md", "agents.md",
    "CLAUDE.md", "claude.md", ".cursorrules",
)


def _chain_candidate_paths(cwd_path: Path) -> set:
    """Every path the priority chain owns — Pulse's loader must not re-add them."""
    paths = {str(cwd_path / name) for name in _CHAIN_CANDIDATE_NAMES}
    for directory in agents_md_directory_chain(cwd_path):
        for name in ("AGENTS.override.md", "AGENTS.md", "agents.md"):
            paths.add(str(directory / name))
    paths.add(str(cwd_path / ".cursor" / "rules"))
    return paths


def build_context_files_prompt(
    cwd: Optional[str] = None,
    skip_soul: bool = False,
    context_length: Optional[int] = None,
    allow_install_tree_fallback: bool = False,
    home_override: Optional[Path] = None,
) -> str:
    """Discover and load context files for the system prompt.

    Priority (first found wins — only ONE project context type is loaded):
      1. ``.pulse.md`` / ``PULSE.md``  (walk to git root)
      2. AGENTS.md / agents.md         (merged chain: git root → cwd)
      3. CLAUDE.md / claude.md         (cwd only)
      4. .cursorrules / .cursor/rules/*.mdc (cwd only)

    ``SOUL.md`` from the Pulse home is independent and always included when
    present. Pulse's ``.pulseai/instructions.md`` rides the same section list
    after the project context, deduplicated by content so a file the chain
    already produced can never be injected twice.
    """
    if cwd is None:
        cwd = os.getcwd()
        cwd_is_fallback = True
    else:
        cwd_is_fallback = False

    cwd_path = Path(cwd).resolve()
    sections: List[str] = []

    # A FALLBACK-picked directory inside the source tree must not gain
    # system-prompt authority (upstream #64590): a backend that self-spawns
    # there would otherwise load this repo's contributor AGENTS.md as if it
    # were the user's project. An explicit cwd is honored verbatim.
    if cwd_is_fallback and not allow_install_tree_fallback and _is_install_tree(cwd_path):
        logger.warning(
            "skipping project-context discovery: working directory resolved to the "
            "Pulse source tree (%s) — point the session at your project directory",
            cwd_path,
        )
        project_context = ""
        instructions_allowed = False
    else:
        project_context = ""
        matched_chain = _find_project_context(cwd_path, context_length)
        project_context, consumed = matched_chain
        instructions_allowed = True

    if project_context:
        sections.append(project_context)

    if instructions_allowed:
        # Upstream's contract is ONE project-context type per prompt, so the
        # chain's candidate files are excluded from Pulse's loader regardless of
        # which of them (if any) won — the loader may only add .pulseai files.
        blocked = set(consumed) | _chain_candidate_paths(cwd_path)
        sections.extend(_pulseai_instructions(cwd_path, context_length, already_loaded=blocked))

    if not skip_soul:
        soul_content = load_soul_md(context_length, home_override=home_override)
        if soul_content:
            sections.append(soul_content)

    if not sections:
        return ""
    return (
        "# Project Context\n\nThe following project context files have been "
        "loaded and should be followed:\n\n" + "\n".join(sections)
    )


__all__ = [
    "agents_md_directory_chain",
    "build_context_files_prompt",
    "find_git_root",
    "find_pulse_md",
    "load_agents_md",
    "load_claude_md",
    "load_cursorrules",
    "load_pulse_md",
    "load_soul_md",
    "strip_yaml_frontmatter",
    "truncate_content",
]
