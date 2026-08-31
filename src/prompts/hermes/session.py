"""Session-scoped prompt caching — the half of Law 1 that Pulse needs.

Upstream caches the built prompt on the long-lived ``AIAgent`` instance
(``agent._cached_system_prompt``) so a conversation reuses one byte-identical
prefix every turn. Pulse has no long-lived agent object: its per-session
object is the ``ContextEngine`` chosen by ``thread_id``, and turns arrive as
independent graph invocations. So the cache lives here, keyed by thread id,
with the same rebuild rule:

    build once → reuse every turn → rebuild ONLY on compaction / session reset.

Kill switch: ``PULSEAI_STABLE_PREFIX=off`` returns the legacy single-string
persona, byte-for-byte, so this can be disabled without touching a call site.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

from src.prompts.hermes.system_prompt import (
    build_system_prompt,
    invalidate_system_prompt,
)
from src.prompts.hermes.view import PulsePromptView, view_from_config

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_views: Dict[str, PulsePromptView] = {}
_MAX_SESSIONS = 64  # LRU-ish: an IDE can leave dozens of threads behind


def stable_prefix_enabled() -> bool:
    return os.environ.get("PULSEAI_STABLE_PREFIX", "on").strip().lower() not in {
        "0",
        "off",
        "false",
        "no",
        "disabled",
    }


def _thread_id(config: Any, state: Optional[Dict[str, Any]] = None) -> str:
    configurable: Dict[str, Any] = {}
    if isinstance(config, dict):
        nested = config.get("configurable")
        configurable = nested if isinstance(nested, dict) else config
    for source in (configurable, state or {}):
        for key in ("thread_id", "session_id", "runtime_session_id"):
            value = source.get(key)
            if value:
                return str(value)
    return "default"


def view_for_session(
    config: Any = None,
    state: Optional[Dict[str, Any]] = None,
    *,
    autonomous: bool = False,
    tools: Optional[Any] = None,
) -> PulsePromptView:
    """Return this session's prompt view, building it on first use.

    A rebuild happens when (and only when) the session was invalidated — see
    :func:`invalidate_session`. Everything else is deliberately reused so the
    provider's prompt cache keeps hitting for the whole conversation.
    """
    thread_id = _thread_id(config, state)
    task = str((state or {}).get("current_task") or (state or {}).get("latest_instruction") or "")
    with _lock:
        existing = _views.get(thread_id)
        if existing is not None and getattr(existing, "autonomous", autonomous) == autonomous:
            # Refresh only the per-turn, non-text inputs. Never touch anything
            # that feeds prompt *text*, or the prefix stops being stable.
            existing.valid_tool_names = existing.valid_tool_names | {str(t) for t in (tools or ())}
            return existing

        view = view_from_config(config, state, tools=tools, task=task)
        view.autonomous = autonomous  # type: ignore[attr-defined]
        if autonomous:
            # Headless workspace execution: no interactive surfaces, so the
            # steering note and the persona contract both change (autonomous
            # is its own cache bucket for exactly this reason).
            view.steer_enabled = False
        if stable_prefix_enabled():
            build_system_prompt(view, system_message=view.identity)
        _views[thread_id] = view
        while len(_views) > _MAX_SESSIONS:
            _views.pop(next(iter(_views)), None)
        return view


def system_prompt_for_session(
    config: Any = None,
    state: Optional[Dict[str, Any]] = None,
    *,
    autonomous: bool = False,
    tools: Optional[Any] = None,
) -> str:
    """The session's cached system prompt ("" when disabled / unavailable)."""
    if not stable_prefix_enabled():
        return ""
    try:
        view = view_for_session(config, state, autonomous=autonomous, tools=tools)
        return build_system_prompt(view, system_message=view.identity)
    except Exception as exc:  # a prompt-engine bug must not strand a turn
        logger.warning("stable system prefix unavailable, falling back to persona: %s", exc)
        return ""


def invalidate_session(thread_id: str) -> bool:
    """Drop the cached prompt for one session (compaction / reset boundary)."""
    with _lock:
        view = _views.pop(str(thread_id), None)
    if view is None:
        return False
    invalidate_system_prompt(view)
    return True


def invalidate_all_sessions() -> int:
    with _lock:
        count = len(_views)
        _views.clear()
    return count


def session_stats(config: Any = None, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the dashboard reads: is the prefix cached, and how big is each tier?"""
    from src.prompts.hermes.system_prompt import system_prompt_stats

    thread_id = _thread_id(config, state)
    with _lock:
        view = _views.get(thread_id)
    if view is None:
        return {"session": thread_id, "cached": False, "enabled": stable_prefix_enabled()}
    return {
        "session": thread_id,
        "cached": bool(view._cached_system_prompt),
        "static_bytes": len(view._cached_system_prompt_static or ""),
        "status": list(view.status_sink),
        **system_prompt_stats(view),
    }


__all__ = [
    "invalidate_all_sessions",
    "invalidate_session",
    "session_stats",
    "stable_prefix_enabled",
    "system_prompt_for_session",
    "view_for_session",
]
