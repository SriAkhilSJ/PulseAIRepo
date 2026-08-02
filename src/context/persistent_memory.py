
"""
Persistent Memory Wrapper for PulseCodeAI
==========================================
Wraps the existing MemoryManager with JSON disk persistence.
Memories survive across terminal sessions and restarts.

What this changes:
- The agent remembers past tasks even after you close and reopen it
- Replan lessons accumulate over time
- The agent gets smarter the more you use it
"""

import json
import os
from datetime import datetime
from typing import Any

class PersistentMemoryWrapper:
    """
    Wraps a MemoryManager instance with disk persistence.

    Usage:
        from src.context.memory_manager import MemoryManager
        from src.context.persistent_memory import PersistentMemoryWrapper
        base_manager = MemoryManager()
        memory_manager = PersistentMemoryWrapper(base_manager)
    """

    def __init__(self, base_manager, storage_path: str | None = None):
        self._base = base_manager
        if storage_path is None:
            home = os.path.expanduser("~")
            pulse_dir = os.path.join(home, ".pulseai")
            os.makedirs(pulse_dir, exist_ok=True)
            self.storage_path = os.path.join(pulse_dir, "memories.json")
        else:
            self.storage_path = storage_path

        self._persistent_memories: list[dict] = []
        self._load_from_disk()

    def __getattr__(self, name: str):
        """Delegate unknown attributes to the base manager."""
        return getattr(self._base, name)

    def store_task_completion(self, task: str, steps_completed: list[str], plan: list[dict]) -> None:
        """Store completion in base manager AND persist to disk."""
        self._base.store_task_completion(task, steps_completed, plan)
        self._persistent_memories.append({
            "type": "task_completion",
            "task": task,
            "steps_completed": steps_completed,
            "plan": plan,
            "timestamp": datetime.now().isoformat(),
        })
        self._save_to_disk()

    def store_replan_lesson(self, task: str, old_plan: list[dict], failure: str, new_strategy: str) -> None:
        """Store lesson in base manager AND persist to disk."""
        self._base.store_replan_lesson(task, old_plan, failure, new_strategy)
        self._persistent_memories.append({
            "type": "replan_lesson",
            "task": task,
            "failure": failure,
            "new_strategy": new_strategy,
            "timestamp": datetime.now().isoformat(),
        })
        self._save_to_disk()

    def retrieve_relevant_memories(self, query: str, top_k: int = 2) -> list[dict]:
        """
        Retrieve memories from base manager, plus inject persistent ones.
        """
        base_results = self._base.retrieve_relevant_memories(query, top_k)

        # Also search persistent memories (simple text match fallback)
        query_lower = query.lower()
        persistent_hits = [
            m for m in self._persistent_memories
            if query_lower in m.get("task", "").lower()
            or query_lower in str(m.get("failure", "")).lower()
        ]

        # Combine, deduplicate by task+type, limit to top_k
        combined = base_results + persistent_hits
        seen = set()
        unique = []
        for mem in combined:
            key = f"{mem.get('task', '')}:{mem.get('type', '')}"
            if key not in seen:
                seen.add(key)
                unique.append(mem)
            if len(unique) >= top_k:
                break

        return unique

    def get_memory_count(self) -> int:
        """Return total memory count from base + persistent."""
        base_count = getattr(self._base, "get_memory_count", lambda: 0)()
        return base_count + len(self._persistent_memories)

    def _save_to_disk(self) -> None:
        """Write persistent memories to JSON."""
        try:
            data = {
                "memories": self._persistent_memories,
                "metadata": {
                    "last_saved": datetime.now().isoformat(),
                    "version": "1.0",
                },
            }
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        except Exception:
            pass

    def _load_from_disk(self) -> None:
        """Read persistent memories from JSON."""
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._persistent_memories = data.get("memories", [])
        except Exception:
            self._persistent_memories = []
