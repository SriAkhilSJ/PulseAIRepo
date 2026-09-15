"""Session-scoped prompt caching — the half of Law 1 that Crusor needs.

Upstream caches the built prompt on the long-lived ``AIAgent`` instance
(``agent._cached_system_prompt``) so a conversation reuses one byte-identical
prefix every turn. Crusor has no long-lived agent object: its per-session
object is the ``ContextEngine`` chosen by ``thread_id``, and turns arrive as
independent graph invocations. So the cache lives here, keyed by thread id,
with the same rebuild rule:

    build once → reuse every turn → rebuild ONLY on compaction / session reset.

Kill switch: ``CRUSORAI_STABLE_PREFIX=off`` returns the legacy single-string
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
from src.prompts.hermes.view import CrusorPromptView, view_from_config

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_views: Dict[str, CrusorPromptView] = {}
_MAX_SESSIONS = 64  # LRU-ish: an IDE can leave dozens of threads behind


def stable_prefix_enabled() -> bool:
    return os.environ.get("CRUSORAI_STABLE_PREFIX", "on").strip().lower() not in {
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


def _resolve_cwd(state: Optional[Dict[str, Any]] = None) -> str:
    """Resolve workspace cwd from state, env, or os.getcwd()."""
    if state:
        ws = state.get("workspace") or state.get("cwd") or ""
        if ws:
            return str(ws)
    env_cwd = os.environ.get("CRUSORAI_WORKSPACE") or os.environ.get("PWD") or ""
    if env_cwd:
        return str(env_cwd)
    try:
        return os.getcwd()
    except Exception:
        return "."

def _view_cache_key(thread_id: str, cwd: str, autonomous: bool) -> str:
    # Pin per thread_id + cwd + autonomous for prompt-cache stability (Hermes parity)
    # cwd normalized to avoid duplicate entries for same dir with trailing slash
    norm_cwd = os.path.normpath(cwd) if cwd else "."
    return f"{thread_id}:{norm_cwd}:{'auto' if autonomous else 'interactive'}"

# Frozen workspace snapshot cache — mirrors coding_context.build_coding_workspace_block
# but stored per view cache key so same thread_id + different cwd gets different snapshot
_frozen_snapshots: Dict[str, str] = {}

def get_frozen_workspace_snapshot(thread_id: str, cwd: str) -> str:
    key = _view_cache_key(thread_id, cwd, False)
    # Also try without autonomous distinction
    return _frozen_snapshots.get(key, "") or _frozen_snapshots.get(f"{thread_id}:{os.path.normpath(cwd) if cwd else '.'}:interactive", "")

def freeze_workspace_snapshot(thread_id: str, cwd: str, snapshot: str) -> None:
    key = _view_cache_key(thread_id, cwd, False)
    _frozen_snapshots[key] = snapshot
    # Also store with other autonomous variant for reuse
    _frozen_snapshots[_view_cache_key(thread_id, cwd, True)] = snapshot

def view_for_session(
    config: Any = None,
    state: Optional[Dict[str, Any]] = None,
    *,
    autonomous: bool = False,
    tools: Optional[Any] = None,
) -> CrusorPromptView:
    """Return this session's prompt view, building it on first use.

    A rebuild happens when (and only when) the session was invalidated — see
    :func:`invalidate_session`. Everything else is deliberately reused so the
    provider's prompt cache keeps hitting for the whole conversation.

    Frozen workspace snapshot: cache keyed by thread_id + cwd + autonomous
    (Hermes parity — build_coding_workspace_block once per session start,
    replay on every later build for cache safety).
    """
    thread_id = _thread_id(config, state)
    cwd = _resolve_cwd(state)
    cache_key = _view_cache_key(thread_id, cwd, autonomous)
    task = str((state or {}).get("current_task") or (state or {}).get("latest_instruction") or "")
    with _lock:
        existing = _views.get(cache_key)
        # Also check legacy key for backward compat
        if existing is None:
            existing = _views.get(thread_id)
        if existing is not None and getattr(existing, "autonomous", autonomous) == autonomous:
            # Refresh only the per-turn, non-text inputs. Never touch anything
            # that feeds prompt *text*, or the prefix stops being stable.
            existing.valid_tool_names = existing.valid_tool_names | {str(t) for t in (tools or ())}
            # Ensure new cache key also points to same view
            if cache_key not in _views:
                _views[cache_key] = existing
            return existing

        view = view_from_config(config, state, tools=tools, task=task)
        view.autonomous = autonomous  # type: ignore[attr-defined]
        # Attach frozen workspace snapshot if available — try ContextEngine first, then local cache
        try:
            # Try to get frozen snapshot from ContextEngine registry
            from src.agents.chat_graph import get_context_engine  # lazy to avoid circular
            eng = get_context_engine(thread_id)
            if eng and hasattr(eng, "get_frozen_workspace_snapshot"):
                frozen = eng.get_frozen_workspace_snapshot(cwd)
                if frozen:
                    _frozen_snapshots[cache_key] = frozen
                    # Inject into view if it has workspace block attr
                    if hasattr(view, "workspace_snapshot"):
                        view.workspace_snapshot = frozen  # type: ignore[attr-defined]
        except Exception:
            pass
        # Fallback: use local frozen cache
        if cache_key in _frozen_snapshots:
            frozen = _frozen_snapshots[cache_key]
            try:
                if hasattr(view, "workspace_snapshot"):
                    view.workspace_snapshot = frozen  # type: ignore[attr-defined]
            except Exception:
                pass
        else:
            # First time for this cwd — build and freeze snapshot
            try:
                from src.context.git_context import build_git_context_layer
                git_ctx = build_git_context_layer({"workspace": cwd})
                if git_ctx:
                    snap = str(getattr(git_ctx, "content", "") or "")
                    if snap:
                        _frozen_snapshots[cache_key] = snap
                        # Also push to ContextEngine if available
                        try:
                            from src.agents.chat_graph import get_context_engine
                            eng = get_context_engine(thread_id)
                            if eng and hasattr(eng, "freeze_workspace_snapshot"):
                                eng.freeze_workspace_snapshot(cwd, snap)
                        except Exception:
                            pass
            except Exception:
                pass

        if autonomous:
            # Headless workspace execution: no interactive surfaces, so the
            # steering note and the persona contract both change (autonomous
            # is its own cache bucket for exactly this reason).
            view.steer_enabled = False
        if stable_prefix_enabled():
            build_system_prompt(view, system_message=view.identity)
        _views[cache_key] = view
        # Keep legacy key for old callers
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


def invalidate_session(thread_id: str, cwd: str = "") -> bool:
    """Drop the cached prompt for one session (compaction / reset boundary).

    If cwd provided, only invalidate that cwd variant; otherwise all variants for thread_id.
    """
    tid = str(thread_id)
    invalidated = False
    with _lock:
        # Collect keys to remove
        keys_to_remove = [k for k in list(_views.keys()) if k == tid or k.startswith(f"{tid}:")]
        if cwd:
            norm = os.path.normpath(cwd)
            # Only remove keys matching this cwd
            keys_to_remove = [k for k in keys_to_remove if norm in k or k == tid]
            # If specific cwd requested but not found, still try legacy
            if not keys_to_remove:
                keys_to_remove = [tid]
        for k in keys_to_remove:
            view = _views.pop(k, None)
            if view is not None:
                try:
                    invalidate_system_prompt(view)
                except Exception:
                    pass
                invalidated = True
                # Also clear frozen snapshot
                _frozen_snapshots.pop(k, None)
        # Clear any frozen snapshots for this thread_id if full invalidate
        if not cwd:
            for k in list(_frozen_snapshots.keys()):
                if k.startswith(f"{tid}:") or k == tid:
                    _frozen_snapshots.pop(k, None)
    return invalidated


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
