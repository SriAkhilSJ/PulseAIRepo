"""Compression commit fence — simplified port of hermes-agent conversation_compression.py

Hermes uses CompressionCommitFence with lock, progress hook, heartbeat, deadlock detection.
For Pulse IDE (Electron utility process, not gateway), we need a lightweight version that:
- Prevents concurrent compaction on same thread_id
- Provides progress callback for UI
- Has idle timeout + total ceiling (env-driven)
- Supports fallback chain pin via ContextVar (simplified)

Env (from .env via settings.py load_dotenv, also loaded defensively here):
- PULSEAI_COMPRESSION_IDLE_TIMEOUT=120s
- PULSEAI_COMPRESSION_CEILING=600s
- PULSEAI_COMPRESSION_FALLBACK_CHAIN=json list or comma-separated models
- PULSEAI_COMPRESSION_LOCK_TTL=300s
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import contextvars
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

_IDLE_TIMEOUT = 120
_CEILING_TIMEOUT = 600
_LOCK_TTL = 300

def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default

# ContextVar for pinned fallback route (Hermes parity)
_SUMMARY_ROUTE_PIN: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("pulse_summary_route_pin", default=None)

def pin_summary_route(route: Optional[Dict[str, Any]]):
    import contextlib
    @contextlib.contextmanager
    def _mgr():
        token = _SUMMARY_ROUTE_PIN.set(route if isinstance(route, dict) else None)
        try:
            yield
        finally:
            _SUMMARY_ROUTE_PIN.reset(token)
    return _mgr()

def take_pinned_summary_route() -> Optional[Dict[str, Any]]:
    route = _SUMMARY_ROUTE_PIN.get()
    if route is not None:
        _SUMMARY_ROUTE_PIN.set(None)
    return route

class CompressionLock:
    """In-memory lock with TTL, holder-qualified lease release (Hermes parity simplified)."""

    def __init__(self):
        self._locks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def try_acquire(self, session_id: str, holder: str = "", ttl: int = _LOCK_TTL) -> bool:
        now = time.monotonic()
        with self._lock:
            existing = self._locks.get(session_id)
            if existing:
                if now - existing["acquired_at"] < existing["ttl"]:
                    # Still held
                    return False
                # Expired
            self._locks[session_id] = {"holder": holder or f"pid:{os.getpid()}:{uuid.uuid4().hex[:8]}", "acquired_at": now, "ttl": ttl}
            return True

    def release(self, session_id: str, holder: str = "") -> bool:
        with self._lock:
            existing = self._locks.get(session_id)
            if not existing:
                return False
            if holder and existing["holder"] != holder:
                # Only holder can release (holder-qualified)
                return False
            self._locks.pop(session_id, None)
            return True

    def is_locked(self, session_id: str) -> bool:
        with self._lock:
            existing = self._locks.get(session_id)
            if not existing:
                return False
            if time.monotonic() - existing["acquired_at"] >= existing["ttl"]:
                self._locks.pop(session_id, None)
                return False
            return True

_global_lock = CompressionLock()

def try_acquire_compression_lock(session_id: str, holder: str = "", ttl: int = _LOCK_TTL) -> bool:
    return _global_lock.try_acquire(session_id, holder, ttl)

def release_compression_lock(session_id: str, holder: str = "") -> bool:
    return _global_lock.release(session_id, holder)

class CompressionCommitFence:
    """Fence timeout vs commit boundary, progress hook, heartbeat (simplified).

    Usage:
        fence = CompressionCommitFence(session_id, on_progress=...)
        with fence:
            # do compression
            fence.touch_progress()
    """

    def __init__(
        self,
        session_id: str,
        *,
        idle_timeout: int | None = None,
        ceiling_timeout: int | None = None,
        on_progress: Callable[[Dict[str, Any]], None] | None = None,
        holder: str = "",
    ):
        self.session_id = session_id
        self.idle_timeout = idle_timeout if idle_timeout is not None else _env_int("PULSEAI_COMPRESSION_IDLE_TIMEOUT", _IDLE_TIMEOUT)
        self.ceiling_timeout = ceiling_timeout if ceiling_timeout is not None else _env_int("PULSEAI_COMPRESSION_CEILING", _CEILING_TIMEOUT)
        self.on_progress = on_progress
        self.holder = holder or f"pulse:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._acquired = False
        self._start = time.monotonic()
        self._last_progress = self._start
        self._commit_phase = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_heartbeat = threading.Event()

    def __enter__(self):
        self._acquired = try_acquire_compression_lock(self.session_id, self.holder, ttl=_env_int("PULSEAI_COMPRESSION_LOCK_TTL", _LOCK_TTL))
        if not self._acquired:
            raise RuntimeError(f"Compression lock held for session {self.session_id}")
        self._start_heartbeat()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_heartbeat.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=1)
        if self._acquired:
            release_compression_lock(self.session_id, self.holder)

    def _start_heartbeat(self):
        def _hb():
            while not self._stop_heartbeat.is_set():
                self._stop_heartbeat.wait(60)
                if self._stop_heartbeat.is_set():
                    break
                # Emit heartbeat
                if self.on_progress:
                    try:
                        self.on_progress({"phase": "heartbeat", "elapsed": int(time.monotonic() - self._start), "session_id": self.session_id})
                    except Exception:
                        pass
        t = threading.Thread(target=_hb, daemon=True, name="compression-heartbeat")
        t.start()
        self._heartbeat_thread = t

    def touch_progress(self, info: Dict[str, Any] | None = None):
        self._last_progress = time.monotonic()
        if self.on_progress:
            try:
                self.on_progress({"phase": "progress", "elapsed": int(self._last_progress - self._start), **(info or {})})
            except Exception:
                pass

    def check_timeout(self) -> bool:
        """Return True if should abort due to timeout."""
        now = time.monotonic()
        if now - self._start > self.ceiling_timeout:
            return True
        if now - self._last_progress > self.idle_timeout:
            return True
        return False

    def enter_commit_phase(self):
        self._commit_phase.set()
        self.touch_progress({"phase": "commit"})

def load_fallback_chain_from_env() -> List[Dict[str, Any]]:
    """Parse PULSEAI_COMPRESSION_FALLBACK_CHAIN.

    Supports JSON list [{"provider":"openrouter","model":"claude-3-5-sonnet"}]
    or comma-separated "model1,model2" -> [{"model": m}].
    """
    import json
    raw = os.environ.get("PULSEAI_COMPRESSION_FALLBACK_CHAIN", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except Exception:
        pass
    # comma-separated
    chain = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            chain.append({"model": part})
    return chain

def run_compress_with_fence(
    session_id: str,
    compress_fn: Callable[[], Any],
    *,
    on_progress: Callable[[Dict[str, Any]], None] | None = None,
) -> Any:
    """Run compress_fn inside fence with timeout handling."""
    fence = CompressionCommitFence(session_id, on_progress=on_progress)
    try:
        with fence:
            # Simple run — real Hermes uses bounded executor with admission cap
            result = compress_fn()
            fence.enter_commit_phase()
            return result
    except Exception as e:
        # If timeout, try fallback chain once
        chain = load_fallback_chain_from_env()
        if chain:
            fallback = chain[0]
            with pin_summary_route(fallback):
                try:
                    with CompressionCommitFence(session_id, on_progress=on_progress) as fence2:
                        result = compress_fn()
                        fence2.enter_commit_phase()
                        return result
                except Exception:
                    pass
        raise e

__all__ = [
    "CompressionCommitFence",
    "CompressionLock",
    "load_fallback_chain_from_env",
    "pin_summary_route",
    "release_compression_lock",
    "run_compress_with_fence",
    "take_pinned_summary_route",
    "try_acquire_compression_lock",
]
