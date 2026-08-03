# src/context/memory_manager.py
"""
Memory Manager
==============

The librarian for the agent's long-term memory.

Decides:

- WHAT to remember (task completions, replan lessons)
- WHEN to remember it (after success, after failure)
- HOW to retrieve it (search by current task similarity)

This is the layer between the agent's graph and the raw VectorMemory.
"""

from typing import Any

from src.context.vector_memory import VectorMemory



class MemoryManager:
    """
    Manages the agent's episodic memory.

    Episodic = "what happened" memories (like diary entries).
    """

    def __init__(self, embedding_provider=None, db_path: str | None = None):
        """
        Creates the vector memory store.

        db_path: SQLite file location. Defaults to ~/.pulseai/vector_memory.db
        """
        self.vector_memory = VectorMemory(db_path=db_path)

    # =========================================================
    # STORE METHODS: Save memories for later
    # =========================================================

    def store_task_completion(
        self,
        task: str,
        steps_completed: list[str],
        plan: list[dict],
    ):
        """
        Call this when a task finishes successfully.

        Stores: what the task was, what steps worked, what the plan was.
        """
        # Build a summary string.
        steps_text = "; ".join(steps_completed[-5:])  # Last 5 steps

        memory_text = (
            f"COMPLETED TASK: {task}\n"
            f"Successful steps: {steps_text}\n"
            f"Total plan steps: {len(plan)}"
        )

        self.vector_memory.add(
            text=memory_text,
            metadata={
                "type": "task_completion",
                "task": task,
                "step_count": len(steps_completed),
            },
        )

    def store_replan_lesson(
        self,
        task: str,
        old_plan: list[dict],
        failure: str,
        new_strategy: str,
    ):
        """
        Call this when a replan happens.

        Stores: the old plan failed, why it failed, what the new plan is.
        This prevents the agent from trying the same broken strategy twice.
        """
        memory_text = (
            f"REPLAN LESSON - Task: {task}\n"
            f"Failed approach: {len(old_plan)} steps\n"
            f"Failure reason: {failure}\n"
            f"New strategy: {new_strategy}"
        )

        self.vector_memory.add(
            text=memory_text,
            metadata={
                "type": "replan_lesson",
                "task": task,
            },
        )

    def store_recovery_lesson(
        self,
        task: str,
        failed_command: str,
        failure_output: str,
        fix_applied: str,
    ):
        """
        Call this when recovery succeeds.

        Stores: what failed, what error appeared, what fixed it.
        Next time the agent sees the same error, it knows the fix.
        """
        # Keep only the first 200 chars of the error (enough to identify).
        error_snippet = failure_output[:200].replace("\n", " ")

        memory_text = (
            f"RECOVERY LESSON - Task: {task}\n"
            f"Command: {failed_command}\n"
            f"Error: {error_snippet}\n"
            f"Fix: {fix_applied}"
        )

        self.vector_memory.add(
            text=memory_text,
            metadata={
                "type": "recovery_lesson",
                "task": task,
            },
        )

    def store_preference(self, preference: str):
        """
        Store a user preference (coding style, UI choice, etc.).
        """
        self.vector_memory.add(
            text=f"USER PREFERENCE: {preference}",
            metadata={"type": "preference"}
        )

    def store_tool_memory(self, tool_name: str, query: str, summary: str, full_output: str):
        """Store a tool output for semantic retrieval later."""
        text = f"TOOL {tool_name} | QUERY: {query} | SUMMARY: {summary}"
        self.vector_memory.add(
            text=text,
            metadata={"type": "tool_memory", "tool": tool_name, "query": query, "summary": summary},
        )

    def retrieve_tool_memories(self, query: str, top_k: int = 3) -> list[dict]:
        """Find past tool outputs semantically similar to the current task."""
        results = self.vector_memory.search(query, top_k=top_k)
        return [r for r in results if r.get("metadata", {}).get("type") == "tool_memory"]


    def retrieve_preferences(self, query: str = "preference", top_k: int = 5) -> list[str]:
        """
        Retrieve relevant user preferences.
        """
        memories = self.vector_memory.search(query, top_k=top_k)
        return [m["text"] for m in memories if m["metadata"].get("type") == "preference"]

    # =========================================================
    # RETRIEVE METHODS: Find relevant past memories
    # =========================================================

    def retrieve_relevant_memories(
        self,
        query: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Find memories similar to the current task.

        query: Usually the current task description.
        top_k: How many memories to fetch.

        Returns: List of memory dicts with keys: text, metadata, timestamp, score.
        """
        results = self.vector_memory.search(query, top_k=top_k)

        # Add a relevance_score field for debugging.
        enriched = []
        for result in results:
            enriched.append({
                "text": result["text"],
                "metadata": result["metadata"],
                "timestamp": result["timestamp"],
                "relevance_score": result.get("score", 0.0),
            })

        return enriched

    def get_memory_count(self) -> int:
        """How many memories are stored."""
        return self.vector_memory.count()

    def clear_all_memories(self):
        """Nuclear option: delete everything."""
        self.vector_memory.clear()
