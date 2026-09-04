"""Lazy, failure-isolated construction of optional long-term memory.

Importing the agent graph must never download an embedding model or open the
memory database. The wrapped manager is created only when memory is actually
used; initialization failure degrades the optional feature for the process.

Hermes discipline (conversation_loop.py treats memory saves as HOUSEKEEPING —
never on the turn's critical path): construction runs in a background thread,
and every memory call waits at most PULSEAI_MEMORY_WARMUP_BUDGET_S (default
2.0, clamped 0..120, read per call) before degrading to the method's default
for that call. Field proof this boundary needs owning: Attempt 8 wedged >10
minutes between tool_call_end and the second provider request when the first
tool memory write triggered a synchronous embedding-model download.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Callable

_WARMUP_BUDGET_ENV = "PULSEAI_MEMORY_WARMUP_BUDGET_S"


def _warmup_budget() -> float:
    """Per-call budget for waiting on a cold memory backend. Env-driven,
    read every call — a running process may tighten it without a restart."""
    raw = os.environ.get(_WARMUP_BUDGET_ENV, "").strip()
    try:
        value = float(raw) if raw else 2.0
    except (TypeError, ValueError):
        value = 2.0
    return max(0.0, min(value, 120.0))


class LazyMemoryManager:
    """Thread-safe lazy proxy for an optional memory manager.

    The factory runs once, in a daemon thread, triggered by the first memory
    call. Callers never block longer than the warm-up budget; while the
    backend is still loading, calls degrade to their defaults (no memories,
    nothing stored) and the turn goes on. A best-effort housekeeping layer
    must never be able to stall the turn it serves.
    """

    def __init__(self, factory: Callable[[], Any]):
        self._factory = factory
        self._instance: Any | None = None
        self._disabled = False
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._started = False
        self._warned_slow = False

    def warmup(self) -> None:
        """Start background construction. Idempotent, never raises."""
        with self._lock:
            if self._started or self._disabled:
                return
            self._started = True
        threading.Thread(
            target=self._construct, name="pulseai-memory-warmup", daemon=True
        ).start()

    def _construct(self) -> None:
        try:
            instance = self._factory()
            with self._lock:
                self._instance = instance
        except Exception as exc:
            with self._lock:
                self._disabled = True
            print(
                "[memory] Long-term memory disabled after lazy "
                f"initialization failed: {type(exc).__name__}: {exc}",
                flush=True,
            )
        finally:
            self._ready.set()

    def _get(self, timeout: float) -> Any | None:
        if self._instance is not None:
            return self._instance
        if self._disabled:
            return None
        self.warmup()
        if self._ready.wait(timeout):
            return None if self._disabled else self._instance
        # Budget blown: degrade THIS call; construction keeps running.
        if not self._warned_slow:
            self._warned_slow = True
            print(
                f"[memory] backend not warm after {_warmup_budget()}s "
                f"({_WARMUP_BUDGET_ENV}); serving defaults for memory calls "
                "while it loads in the background",
                flush=True,
            )
        return None

    @property
    def initialized(self) -> bool:
        return self._instance is not None

    @property
    def disabled(self) -> bool:
        return self._disabled

    def __bool__(self) -> bool:
        # Optional memory is configured even before construction. This allows
        # existing `if memory_manager:` call sites to enter the lazy method.
        return not self._disabled

    def _call(self, name: str, fallback: Any, *args, **kwargs):
        instance = self._get(_warmup_budget())
        if instance is None:
            return fallback
        return getattr(instance, name)(*args, **kwargs)

    # Explicit methods are intentional. LangGraph inspects function nonlocals
    # while compiling the graph and resolves attributes named in node bodies.
    # If these went through __getattr__, compilation itself would initialize
    # embeddings even though no memory operation had run.
    def store_task_completion(self, *args, **kwargs):
        return self._call("store_task_completion", None, *args, **kwargs)

    def store_replan_lesson(self, *args, **kwargs):
        return self._call("store_replan_lesson", None, *args, **kwargs)

    def store_recovery_lesson(self, *args, **kwargs):
        return self._call("store_recovery_lesson", None, *args, **kwargs)

    def store_preference(self, *args, **kwargs):
        return self._call("store_preference", None, *args, **kwargs)

    def store_tool_memory(self, *args, **kwargs):
        return self._call("store_tool_memory", None, *args, **kwargs)

    def retrieve_tool_memories(self, *args, **kwargs):
        return self._call("retrieve_tool_memories", [], *args, **kwargs)

    def retrieve_preferences(self, *args, **kwargs):
        return self._call("retrieve_preferences", [], *args, **kwargs)

    def retrieve_relevant_memories(self, *args, **kwargs):
        return self._call("retrieve_relevant_memories", [], *args, **kwargs)

    def get_memory_count(self, *args, **kwargs):
        return self._call("get_memory_count", 0, *args, **kwargs)

    def clear_all_memories(self, *args, **kwargs):
        return self._call("clear_all_memories", None, *args, **kwargs)

    def __getattr__(self, name: str):
        # Unknown/protocol attributes are not a memory operation.
        raise AttributeError(name)
