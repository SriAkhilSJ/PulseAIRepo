"""Lazy, failure-isolated construction of optional long-term memory.

Importing the agent graph must never download an embedding model or open the
memory database. The wrapped manager is created only when memory is actually
used; initialization failure degrades the optional feature for the process.
"""
from __future__ import annotations

import threading
from typing import Any, Callable


class LazyMemoryManager:
    """Thread-safe lazy proxy for an optional memory manager."""

    def __init__(self, factory: Callable[[], Any]):
        self._factory = factory
        self._instance: Any | None = None
        self._disabled = False
        self._lock = threading.Lock()

    def _get(self) -> Any | None:
        if self._instance is not None:
            return self._instance
        if self._disabled:
            return None
        with self._lock:
            if self._instance is not None:
                return self._instance
            if self._disabled:
                return None
            try:
                self._instance = self._factory()
            except Exception as exc:
                self._disabled = True
                print(
                    "[memory] Long-term memory disabled after lazy "
                    f"initialization failed: {type(exc).__name__}: {exc}",
                    flush=True,
                )
            return self._instance

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
        instance = self._get()
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
