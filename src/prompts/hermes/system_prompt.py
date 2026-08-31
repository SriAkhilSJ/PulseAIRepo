"""System-prompt assembly — pin-to-pin port of ``agent/system_prompt.py``.

The rules this module exists to enforce are Hermes's two sacred laws:

1. **The prompt is built once per session and reused across every turn.** Only
   a compaction event rebuilds it (:func:`invalidate_system_prompt`), because
   anything that mutates past context invalidates the provider's prompt cache
   and multiplies the user's cost.
2. **Ordering is the cache.** ``stable`` → ``context`` → ``volatile``; the
   content most likely to change renders last, so a rebuild that only touched
   the tail keeps the reused prefix.

Pulse's backend supplies every input through :class:`PulsePromptView`
(``view.py``); this module never reads settings, the graph, or the tool
registry directly.
"""
from __future__ import annotations

import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from src.prompts.hermes import guidance
from src.prompts.hermes.environment import build_environment_hints, mode_hint, resolve_platform_hint
from src.prompts.hermes.skills_index import build_skills_system_prompt
from src.prompts.hermes.view import PulsePromptView

logger = logging.getLogger(__name__)

# The plugin/skill-section frame: a coarse anchor carried in the volatile tail
# so a resumed process can rebuild the stable prefix without re-running
# producers. Upstream regex-recognises its own frame; Pulse's frame labels the
# producing subsystem so a stale section can be attributed in logs.
_SECTION_FRAME_RE = "^## Pulse Context: (?P<id>[a-z0-9][a-z0-9._-]{0,127})$"


def _has_tools(view: PulsePromptView) -> bool:
    return bool(view.valid_tool_names)


def _skill_view_available(view: PulsePromptView) -> bool:
    return "skill_view" in (view.valid_tool_names or set())


def _execution_guidance_allowed(view: PulsePromptView) -> bool:
    """``auto`` matches the upstream model-family list; True/False force it;
    a list is a user-supplied substring set."""
    setting = view.execution_guidance
    if isinstance(setting, bool):
        return setting
    if isinstance(setting, (list, tuple, set, frozenset)):
        model = (view.model or "").lower()
        return any(str(pattern).lower() in model for pattern in setting)
    if str(setting).strip().lower() in {"", "auto"}:
        return guidance.needs_execution_guidance(view.model)
    return str(setting).strip().lower() not in {"0", "false", "no", "off"}


def _memory_block(view: PulsePromptView, target: str) -> str:
    store = view.memory_store
    if not store:
        return ""
    try:
        return str(store.format_for_system_prompt(target) or "")
    except Exception:
        return ""


def _session_start(view: PulsePromptView) -> datetime.datetime:
    return getattr(view, "session_started_at", None) or datetime.datetime.now()


def build_system_prompt_parts(view: PulsePromptView, system_message: Optional[str] = None) -> Dict[str, str]:
    """Assemble the system prompt as three ordered cache tiers.

    ``stable``   — identity (SOUL.md or the Pulse default), tool guidance,
                   per-model operational guidance, steering note, environment
                   hints, execution-mode posture.
    ``context``  — caller-supplied ``system_message`` plus the project context
                   files discovered under the session cwd.
    ``volatile`` — skills index, memory snapshot, user profile, external memory
                   provider block, timestamp/session/model/provider line.
    """
    context_length = view.context_length
    stable_parts: List[str] = []

    # ── Stable tier ────────────────────────────────────────────────────────
    # 1. Identity slot: SOUL.md wins, else the caller's persona, else default.
    #    (Upstream resolves SOUL.md first and falls back to
    #    DEFAULT_AGENT_IDENTITY; the slot is where a product swaps persona
    #    without touching a single guidance block.)
    _soul_loaded = False
    if view.load_soul_identity:
        try:
            from src.prompts.hermes.context_files import load_soul_md

            soul = load_soul_md(context_length, home_override=view.home)
        except Exception:
            soul = None
        if soul:
            stable_parts.append(soul)
            _soul_loaded = True
    if not _soul_loaded and view.identity:
        stable_parts.append(view.identity)
        _soul_loaded = True
    if not _soul_loaded:
        stable_parts.append(guidance.DEFAULT_AGENT_IDENTITY)

    # 2. Product-pointer block, in the variant the session's toolset can
    #    actually honour. The skill-pointer variant needs BOTH the skill tool
    #    and the skill present in the rendered index, so resolution happens
    #    after the index is built (below) and this slot just holds the position.
    skills_prompt = ""
    if view.skills_enabled:
        try:
            skills_prompt = build_skills_system_prompt(
                available_tools=view.valid_tool_names,
                skills_dir_override=view.skills_dir,
                home=view.home,
            )
        except Exception as exc:  # a broken skills tree must never block a turn
            logger.debug("skills index build failed: %s", exc)
            skills_prompt = ""

    help_slot = len(stable_parts)
    stable_parts.append(guidance.PULSE_AGENT_HELP_GUIDANCE_NO_SKILLS)
    if _skill_view_available(view) and "- pulseai:" in skills_prompt:
        stable_parts[help_slot] = guidance.PULSE_AGENT_HELP_GUIDANCE

    # 3. Universal finish-the-job + batching steering. Gated only on tools
    #    actually being loaded — a model with no tools cannot batch anything.
    if view.task_completion_guidance and _has_tools(view):
        stable_parts.append(guidance.TASK_COMPLETION_GUIDANCE)
    if view.parallel_tool_call_guidance and _has_tools(view):
        stable_parts.append(guidance.PARALLEL_TOOL_CALL_GUIDANCE)

    # 4. Tool-aware guidance: each block appears ONLY when the tool it names is
    #    in this session's waist, which is what keeps a compact toolset from
    #    advertising a capability the model cannot call.
    tool_guidance: List[str] = []
    if "memory" in view.valid_tool_names:
        if view.memory_enabled:
            tool_guidance.append(guidance.build_memory_guidance(True, view.user_profile_enabled) or guidance.MEMORY_GUIDANCE)
        elif view.user_profile_enabled:
            tool_guidance.append(guidance.USER_PROFILE_GUIDANCE)
    if "session_search" in view.valid_tool_names:
        tool_guidance.append(guidance.SESSION_SEARCH_GUIDANCE)
    if "skill_manage" in view.valid_tool_names:
        tool_guidance.append(guidance.SKILLS_GUIDANCE)
    if tool_guidance:
        stable_parts.append(" ".join(tool_guidance))

    # 5. Steering note — only when a steer channel actually exists (Pulse:
    #    bridge protocol v2 client method `steer`), and only when a tool result
    #    can carry it (i.e. there ARE tools).
    if view.steer_enabled and _has_tools(view) and guidance.STEER_CHANNEL_NOTE:
        stable_parts.append(guidance.STEER_CHANNEL_NOTE)

    # 6. Per-model operational guidance.
    if guidance.needs_tool_use_enforcement(view.model):
        stable_parts.append(guidance.TOOL_USE_ENFORCEMENT_GUIDANCE)
        if guidance.is_google_model(view.model):
            stable_parts.append(guidance.GOOGLE_MODEL_OPERATIONAL_GUIDANCE)
    if _execution_guidance_allowed(view):
        stable_parts.append(guidance.execution_guidance_text(view.valid_tool_names))

    # 7. Environment hints + execution-mode posture + platform hint overrides.
    env_hints = build_environment_hints(view.cwd)
    if env_hints:
        stable_parts.append(env_hints)
    platform_hint = resolve_platform_hint("", str(view.platform or ""), view.platform_hint_overrides)
    if platform_hint:
        stable_parts.append(platform_hint)

    # ── Context tier (cwd-dependent; may change between sessions) ──────────
    context_parts: List[str] = []
    if system_message:
        context_parts.append(system_message)
    if not view.skip_context_files:
        try:
            from src.prompts.hermes.context_files import build_context_files_prompt

            context_files_prompt = build_context_files_prompt(
                cwd=str(view.cwd) if view.cwd else None,
                skip_soul=_soul_loaded,
                context_length=context_length,
                home_override=view.home,
            )
        except Exception as exc:
            logger.debug("context-file discovery failed: %s", exc)
            context_files_prompt = ""
        if context_files_prompt:
            context_parts.append(context_files_prompt)
    for extra in getattr(view, "context_sections", ()) or ():
        if extra:
            context_parts.append(str(extra))

    # ── Volatile tier (rebuilt content stays LAST so the prefix stays reusable)
    volatile_parts: List[str] = []
    # The skills index is runtime-mutable, so it rides the FRONT of the volatile
    # band rather than the stable prefix: an unchanged index still falls inside
    # a reused longest-prefix cache, and a changed one re-prefills only from here.
    if skills_prompt:
        volatile_parts.append(skills_prompt)

    if view.memory_store:
        if view.memory_enabled:
            mem_block = _memory_block(view, "memory")
            if mem_block:
                volatile_parts.append(mem_block)
        if view.user_profile_enabled:
            user_block = _memory_block(view, "user")
            if user_block:
                volatile_parts.append(user_block)
    if view.memory_manager is not None:
        try:
            ext_block = str(view.memory_manager.build_system_prompt() or "")
            if ext_block:
                volatile_parts.append(ext_block)
        except Exception:
            pass

    for section in getattr(view, "volatile_sections", ()) or ():
        if section:
            volatile_parts.append(str(section))

    # Execution mode is a PER-TURN fact in Pulse (the composer can switch
    # Agent → Plan → Ask mid-conversation), so unlike upstream's platform hint —
    # fixed for a session — it rides the volatile band. Putting it in the stable
    # tier would make every mode switch bust the whole cached prefix.
    mode_line = mode_hint(getattr(view, "execution_mode", ""))
    if mode_line:
        volatile_parts.append(mode_line)

    volatile_parts.append(_timestamp_line(view))

    return {
        "stable": "\n\n".join(p.strip() for p in stable_parts if p and p.strip()),
        "context": "\n\n".join(p.strip() for p in context_parts if p and p.strip()),
        "volatile": "\n\n".join(p.strip() for p in volatile_parts if p and p.strip()),
    }


def _timestamp_line(view: PulsePromptView) -> str:
    """Date-only (not minute-precision) so the line is byte-stable for the day.

    Minute precision would invalidate the cached prefix on every rebuild
    (compression boundary, session resume, fresh-agent turns). The model can
    still query wall-clock time with a tool when it needs it. Zone and offset
    are included — both are constant for a whole day — because tools that
    accept instants reject naive datetimes.
    """
    now = datetime.datetime.now().astimezone()
    zone_bits: List[str] = []
    try:
        tzname = now.tzname()
        if tzname:
            zone_bits.append(tzname)
    except Exception:
        pass
    offset = now.strftime("%z")
    if offset:
        zone_bits.append(f"UTC{offset[:3]}:{offset[3:]}")
    zone_suffix = f" ({', '.join(zone_bits)})" if zone_bits else ""

    start = _session_start(view)
    line = f"Conversation started: {start.strftime('%A, %B %d, %Y')}{zone_suffix}"
    if now.strftime("%Y%m%d") != start.strftime("%Y%m%d"):
        line += (
            f"\nToday's date (as of the last context rebuild): "
            f"{now.strftime('%A, %B %d, %Y')} — trust this over the start "
            f"date for what day it is now; query tools for exact time."
        )
    if view.pass_session_id and view.session_id:
        line += f"\nSession ID: {view.session_id}"
    if view.model:
        line += f"\nModel: {view.model}"
    if view.provider:
        line += f"\nProvider: {view.provider}"
    if view.platform:
        line += f"\nPlatform: {view.platform}"
    return line


def build_system_prompt(view: PulsePromptView, system_message: Optional[str] = None, *, use_cache: bool = True) -> str:
    """Assemble the full system prompt, cached for the life of the session.

    Called once per session; only a compaction rebuilds it. The stable tier is
    also handed to the prompt-cache boundary registry so the planner can place
    a breakpoint at the exact byte where the volatile tail starts instead of
    caching the whole system message as one atomic block.
    """
    if use_cache and isinstance(view._cached_system_prompt, str) and view._cached_system_prompt:
        return view._cached_system_prompt

    parts = build_system_prompt_parts(view, system_message=system_message)
    joined = "\n\n".join(p for p in (parts["stable"], parts["context"], parts["volatile"]) if p)
    if use_cache:
        view._cached_system_prompt = joined
    view._cached_system_prompt_static = parts["stable"]

    try:  # pyrefly: ignore [missing-import]
        from src.context.prompt_cache_boundary import register_stable_prefix

        register_stable_prefix(parts["stable"])
    except Exception:
        pass

    # Surface context-file truncation on the status channel so the user sees
    # it in the UI instead of only in logs.
    for warning in guidance.drain_truncation_warnings():
        view._emit_status(warning)

    return joined


def invalidate_system_prompt(view: PulsePromptView) -> None:
    """Force a rebuild on the next turn — called after context compression.

    Also reloads memory from disk so the rebuilt prompt captures anything this
    session wrote, and drops the frozen section snapshot so producers re-render
    at the same boundary: freezing a section while memory and guidance refresh
    recreates the stale-block disease inside the frozen region.
    """
    view._cached_system_prompt = None
    view._cached_system_prompt_static = None
    snapshot_attr = "_plugin_system_prompt_sections_snapshot"
    if getattr(view, snapshot_attr, None) is not None:
        view._plugin_system_prompt_sections_previous = getattr(view, snapshot_attr)
        setattr(view, snapshot_attr, None)
    store = view.memory_store
    for loader in ("load_from_disk", "reload", "_load_from_disk"):
        method = getattr(store, loader, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass
            break


def reconstruct_static_prefix(view: PulsePromptView, system_message: Optional[str] = None, *, log_label: str = "restore") -> None:
    """Rebuild ``_cached_system_prompt_static`` for an adopted/stored prompt.

    Only the full prompt is persisted, so any path that adopts a stored prompt
    (session restore, the compaction keep-prompt path, a failover to a
    cache-on provider mid-turn) must rebuild the stable tier to regain the
    two-block ``[static, volatile]`` layout.

    Safety: the rebuilt tier is used ONLY when the stored prompt literally
    starts with it. If any stable input changed since it was persisted, the
    static slot stays ``None`` and requests fall back to the legacy layout with
    the stored bytes untouched — never a rewritten prompt.
    """
    if not view._use_prompt_caching:
        return
    stored = view._cached_system_prompt
    if not isinstance(stored, str) or not stored:
        return
    existing = view._cached_system_prompt_static
    if isinstance(existing, str) and existing and stored.startswith(existing):
        return
    if getattr(view, "_static_rebuild_failed_for", None) == stored:
        return
    try:
        static = build_system_prompt_parts(view, system_message=system_message)["stable"]
        if static and stored.startswith(static):
            view._cached_system_prompt_static = static
            view._static_rebuild_failed_for = None
            return
    except Exception:
        logger.debug("static system-prefix reconstruction failed on %s", log_label, exc_info=True)
    view._cached_system_prompt_static = None
    view._static_rebuild_failed_for = stored


def format_tools_for_system_message(view: PulsePromptView) -> str:
    """Render the bound toolset in trajectory format (for logs/evals, not the wire)."""
    if not view.tools:
        return "[]"
    formatted = []
    for tool in view.tools:
        func = tool.get("function", tool) if isinstance(tool, dict) else tool
        formatted.append(
            {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
                "required": None,
            }
        )
    return json.dumps(formatted, ensure_ascii=False)


def system_prompt_stats(view: PulsePromptView) -> Dict[str, Any]:
    """Tier sizes — the cheap handle the dashboard/audit uses to see whether the
    stable prefix dominates (it should, and it must not move)."""
    parts = build_system_prompt_parts(view)
    return {
        "stable_chars": len(parts["stable"]),
        "context_chars": len(parts["context"]),
        "volatile_chars": len(parts["volatile"]),
        "total_chars": sum(len(v) for v in parts.values()) + 4,
        "tools_bound": len(view.valid_tool_names),
    }


__all__ = [
    "build_system_prompt",
    "build_system_prompt_parts",
    "format_tools_for_system_message",
    "invalidate_system_prompt",
    "reconstruct_static_prefix",
    "system_prompt_stats",
]
