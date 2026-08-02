# src/context/context_engine.py
"""
Context Engine for PulseCodeAI
================================

Think of this as the agent's "memory organizer."

Before the AI makes any decision, the Context Engine:

1. Looks at the current state (what's happening right now)
2. Picks the most relevant information
3. Organizes it into clean layers
4. Makes sure it fits within the token budget
5. Hands it to the AI

This prevents:

- Token overflow (saving money)
- Confusion (AI only sees what it needs)
- Lost information (important stuff is preserved)
"""

from typing import Any

from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    HumanMessage,
    ToolMessage,
    AIMessage,
)

from src.context.token_budget import count_tokens, trim_messages_to_budget
from src.context.summarizer import SmartSummarizer
from src.context.memory_manager import MemoryManager
from src.context.repo_map import get_repo_map
from src.config.settings import CONTEXT_MODEL


class ContextEngine:
    """
    The Context Engine class.

    You create ONE of these when your agent starts.
    It lives for the whole conversation.
    """

    def __init__(
        self,
        max_tokens: int = 8000,
        model: str | None = None,
        llm=None,
        memory_manager: MemoryManager | None = None,
    ):
        """
        max_tokens: How many tokens the AI can handle total.
                    (Check your model context window before raising this.)
        model: Which model you're using (affects token counting).
        """
        self.max_tokens = max_tokens
        self.model = model or CONTEXT_MODEL

        # We reserve some tokens for "context" (the stuff we build)
        # and leave the rest for "history" (past conversation)
        self.context_budget = 3000   # Tokens for our organized context
        self.history_budget = max_tokens - self.context_budget  # Rest for chat history

        # SmartSummarizer compresses long tool outputs before they reach the AI
        # llm=None means: use only free heuristics (recommended for budget)
        # Pass an LLM if you want AI-powered summarization for massive outputs
        self.summarizer = SmartSummarizer(llm=llm)

        # Long-term memory: retrieves relevant past tasks/lessons.
        # If None, the agent has no long-term memory (like before).
        self.memory_manager = memory_manager

    # =========================================================
    # MAIN METHOD: Build messages for the AI node
    # =========================================================

    def build_ai_messages(
        self,
        state: dict[str, Any],
        system_message: SystemMessage,
    ) -> list[BaseMessage]:
        """
        Build the complete message list for the main AI node.

        This replaces the giant manual string-building in ai_node.
        """
        # Step 1: Build our organized context layers
        context_messages = self._build_context_layers(state)

        # Step 2: Get the raw conversation history
        raw_history = list(state.get("messages", []))

        # Step 2.5: SUMMARIZE long tool outputs before the AI sees them
        # This prevents giant file reads / terminal dumps from filling the context
        raw_history = self._summarize_tool_messages(raw_history)

        # Step 3: Trim history to fit our budget
        # We always keep system_message first
        available_for_history = self.history_budget

        # Count how many tokens our context uses
        context_token_count = count_tokens(context_messages, self.model)

        # If context is using more than expected, steal from history budget
        if context_token_count > self.context_budget:
            available_for_history = self.max_tokens - context_token_count

        # Trim the history
        trimmed_history = self._trim_history(raw_history, available_for_history)

        # Step 4: Assemble final message list
        # Order matters! System first, then context, then history
        final_messages = [system_message] + context_messages + trimmed_history

        return final_messages

    # =========================================================
    # CONTEXT LAYERS (This is the magic)
    # =========================================================

    def _build_context_layers(self, state: dict[str, Any]) -> list[BaseMessage]:
        """
        Build organized layers of context.

        Instead of one giant text blob, we create separate messages.
        This helps the AI understand the structure better.
        """
        layers = []

        # ---- LAYER 0: Repo Map (codebase structure) ----
        repo_map_msg = self._repo_map_layer(state)
        if repo_map_msg:
            layers.append(repo_map_msg)

        # ---- LAYER 1: What is the current task? ----
        layers.append(self._task_layer(state))

        # ---- LAYER 2: What is our current plan? ----
        layers.append(self._plan_layer(state))

        # ---- LAYER 3: What have we accomplished? ----
        layers.append(self._progress_layer(state))

        # ---- LAYER 4: Are we in recovery mode? ----
        recovery_msg = self._recovery_layer(state)
        if recovery_msg:
            layers.append(recovery_msg)

        # ---- LAYER 5: Have we replanned? ----
        replan_msg = self._replan_layer(state)
        if replan_msg:
            layers.append(replan_msg)

        # ---- LAYER 6: Past attempts summary (current task only) ----
        history_msg = self._attempt_history_layer(state)
        if history_msg:
            layers.append(history_msg)

        # ---- LAYER 7: Long-term memory (cross-task learning) ----
        memory_msg = self._long_term_memory_layer(state)
        if memory_msg:
            layers.append(memory_msg)

        # ---- LAYER 8: Ambiguity detection ----
        ambiguity_msg = self._ambiguity_layer(state)
        if ambiguity_msg:
            layers.append(ambiguity_msg)

        # ---- LAYER 9: Tone adaptation ----
        tone_msg = self._tone_layer(state)
        if tone_msg:
            layers.append(tone_msg)

        # ---- LAYER 10: Quality standards reminder ----
        layers.append(self._quality_layer())

        # ---- LAYER 11: Project conventions ----
        convention_msg = self._convention_layer(state)
        if convention_msg:
            layers.append(convention_msg)

        # ---- LAYER 12: Memory validation ----
        validation_msg = self._memory_validation_layer(state)
        if validation_msg:
            layers.append(validation_msg)

        # ---- LAYER 13: Past reflections & lessons ----
        reflection_msg = self._reflection_layer(state)
        if reflection_msg:
            layers.append(reflection_msg)

        # ---- LAYER 14: User-defined skills ----
        skills_msg = self._skills_layer(state)
        if skills_msg:
            layers.append(skills_msg)

        return layers

    def _reflection_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 13: Inject lessons learned from past reflections."""
        from src.context.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        lessons = engine.get_recent_lessons(n=2)
        if not lessons:
            return None
        lines = ["=== LESSONS FROM PAST TASKS ==="]
        lines.append("Based on previous work, keep these in mind:\n")
        for lesson in lessons:
            lines.append(f"- {lesson}")
        lines.append("\nApply these lessons to avoid repeating past mistakes.")
        return SystemMessage(content="\n".join(lines))

    def _skills_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 14: Inject user-defined skills relevant to the task."""
        from src.agents.skill_manager import skill_manager
        task = state.get("current_task", "")
        if not task:
            return None
        text = skill_manager.get_skills_text(task)
        if not text:
            return None
        return SystemMessage(content=text)

    def _preferences_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 8: Relevant user preferences."""
        if self.memory_manager is None:
            return None
            
        prefs = self.memory_manager.retrieve_preferences()
        if not prefs:
            return None
            
        content = "=== USER PREFERENCES ===\n" + "\n".join(f"- {p}" for p in prefs)
        return SystemMessage(content=content)

    def _quality_layer(self) -> SystemMessage:
        """Layer 8: Claude-quality response standards reminder."""
        return SystemMessage(content=(
            "=== QUALITY STANDARDS ===\n"
            "As you work, remember to:\n"
            "- Explain your reasoning before taking action\n"
            "- Use markdown formatting for readability\n"
            "- Be honest about uncertainty rather than guessing\n"
            "- Summarize tool results in plain English\n"
            "- Ask clarifying questions when tasks are ambiguous\n"
            "- Verify your work before claiming success\n"
            "- Handle errors gracefully with root-cause analysis\n"
        ))

    def _convention_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 11: Inject learned project conventions."""
        from src.context.convention_learner import ConventionLearner
        workspace = state.get("workspace", ".")
        learner = ConventionLearner()
        text = learner.get_conventions_text(workspace)
        if not text:
            return None
        return SystemMessage(content=text)

    def _memory_validation_layer(
        self,
        state: dict[str, Any],
    ) -> SystemMessage | None:
        """Layer 12: Warn about stale memories."""
        from src.context.memory_validator import MemoryValidator

        # Only run if we actually have memories in context
        query = state.get("current_task", "")
        if not query or not self.memory_manager:
            return None

        memories = self.memory_manager.retrieve_relevant_memories(query, top_k=3)
        if not memories:
            return None

        validator = MemoryValidator(workspace=state.get("workspace", "."))
        validated = validator.validate_memories(memories)

        stale = [m for m in validated if m.get("confidence") == "low"]
        if not stale:
            return None

        lines = ["=== MEMORY STALENESS WARNING ==="]
        lines.append(
            "The following past memories may be outdated. "
            "Verify before relying on them:\n"
        )

        for mem in stale:
            warning = mem.get("stale_warning", "Potentially outdated")
            task_preview = mem.get("task", mem.get("text", "Unknown task"))[:100]
            lines.append(f"- **{task_preview}...**")
            lines.append(f"  ⚠️ {warning}")

        lines.append(
            "\nIf these memories no longer apply, focus on the current "
            "codebase state rather than past solutions."
        )
        return SystemMessage(content="\n".join(lines))

    def _tone_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 9: Adapt tone based on task complexity."""
        from src.context.tone_adapter import ToneAdapter

        task = state.get("current_task", "")
        if not task:
            return None

        adapter = ToneAdapter()
        guidelines = adapter.get_tone_guidelines(task)
        return SystemMessage(content=guidelines)

    def _repo_map_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """
        Layer 0: Structural map of the codebase.

        This helps the agent know WHERE files are without burning tokens on
        recursive directory listings.
        """
        # Only include repo map for coding tasks.
        current_task = state.get("current_task", "")
        if not current_task:
            return None

        # Get workspace from state or default to current dir.
        workspace = state.get("workspace", ".")

        try:
            repo_map_text = get_repo_map(workspace, max_tokens=1200)
        except Exception:
            # If repo map fails, don't break the agent.
            return None

        if not repo_map_text:
            return None

        content = (
            "=== CODEBASE STRUCTURE (Repo Map) ===\n"
            "Use this map to locate files without listing directories.\n"
            "When a task mentions a file or module, check this map first.\n\n"
            f"{repo_map_text}"
        )

        return SystemMessage(content=content)

    def _task_layer(self, state: dict[str, Any]) -> SystemMessage:
        """Layer 1: What is the user trying to do?"""
        current_task = state.get("current_task", "")
        latest_instruction = state.get("latest_instruction", "")

        content = "=== CURRENT TASK ===\n"

        if current_task:
            content += f"Overall goal: {current_task}\n"
        if latest_instruction:
            content += f"Latest instruction: {latest_instruction}\n"

        return SystemMessage(content=content)

    def _plan_layer(self, state: dict[str, Any]) -> SystemMessage:
        """Layer 2: What is our execution plan?"""
        plan = state.get("plan", [])
        plan_goal = state.get("plan_goal", "")

        if not plan:
            return SystemMessage(content="=== PLAN ===\nNo active plan.")

        lines = [f"Plan goal: {plan_goal}"]
        lines.append("")

        for step in plan:
            status = step.get("status", "pending")
            desc = step.get("description", "")
            step_id = step.get("id", "?")
            lines.append(f"{step_id}. [{status}] {desc}")

        lines.append("")
        lines.append(f"All steps completed: {self._is_plan_complete(plan)}")

        return SystemMessage(content="=== PLAN ===\n" + "\n".join(lines))

    def _progress_layer(self, state: dict[str, Any]) -> SystemMessage:
        """Layer 3: What have we done so far?"""
        completed = state.get("steps_completed", [])
        failed = state.get("failed_steps", [])

        lines = ["=== PROGRESS ==="]

        lines.append("\nSuccessful steps:")
        if completed:
            for step in completed[-5:]:  # Only last 5 (keep it short)
                lines.append(f"  ✓ {step}")
        else:
            lines.append("  (none yet)")

        lines.append("\nFailed attempts:")
        if failed:
            for step in failed[-3:]:  # Only last 3 failures
                lines.append(f"  ✗ {step}")
        else:
            lines.append("  (none)")

        return SystemMessage(content="\n".join(lines))

    def _recovery_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 4: Recovery mode info (only if active)."""
        recovery_mode = state.get("recovery_mode", False)
        recovery_attempts = state.get("recovery_attempts", 0)
        recovery_command = state.get("recovery_command")
        failed_steps = state.get("failed_steps", [])

        if not recovery_mode and recovery_attempts == 0:
            return None

        lines = ["=== RECOVERY STATUS ==="]

        if recovery_mode:
            latest_failure = failed_steps[-1] if failed_steps else "Unknown"
            lines.append("RECOVERY MODE IS ACTIVE")
            lines.append(f"Original failed operation: {recovery_command}")
            lines.append(f"Recovery failures: {recovery_attempts}/3")
            lines.append(f"Latest failure: {latest_failure}")
            lines.append("")
            lines.append("Diagnose the root cause before retrying.")
            lines.append("Do NOT repeat the identical failed command.")
        else:
            lines.append(f"Recovery failures during this task: {recovery_attempts}/3")
            lines.append("Recovery mode is not active.")

        return SystemMessage(content="\n".join(lines))

    def _replan_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 5: Replan info (only if we've replanned)."""
        replan_count = state.get("replan_count", 0)

        if replan_count == 0:
            return None

        content = (
            f"=== REPLAN STATUS ===\n"
            f"Automatic replans during this task: {replan_count}/2.\n"
            f"This is separate from recovery attempts.\n"
        )

        # Add a warning if we're close to the limit
        if replan_count >= 2:
            content += "WARNING: Replan limit reached. No more replans allowed.\n"

        return SystemMessage(content=content)

    def _attempt_history_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 6: Summarized history of past attempts (learning memory)."""
        prior_attempts = state.get("prior_attempts", [])

        if not prior_attempts:
            return None

        lines = ["=== PAST ATTEMPTS (LEARN FROM THESE) ==="]

        # Only show last 2 attempts
        for i, attempt in enumerate(prior_attempts[-2:], 1):
            lines.append(f"\nAttempt {i}:")
            lines.append(f"  Strategy: {attempt.get('strategy_summary', 'N/A')}")
            lines.append(f"  Why it failed: {attempt.get('failure_reason', 'N/A')}")
            lines.append(f"  Lesson: {attempt.get('lesson', 'N/A')}")

        lines.append("\nUse these lessons to avoid repeating the same mistakes.")

        return SystemMessage(content="\n".join(lines))

    def _long_term_memory_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """
        Layer 7: Retrieve relevant memories from PAST tasks.

        This is how the agent learns across conversations.
        If the user asked for an API last week, and asks for a server today,
        the agent remembers what worked.
        """
        # If no memory manager is attached, skip this layer.
        if self.memory_manager is None:
            return None

        # Use the current task as the search query.
        query = state.get("current_task", "")

        if not query:
            return None

        # Search for similar past memories.
        memories = self.memory_manager.retrieve_relevant_memories(
            query=query,
            top_k=2,  # Don't overwhelm the AI with too many memories.
        )

        if not memories:
            return None

        lines = ["=== LONG-TERM MEMORY (Relevant Past Tasks) ==="]
        lines.append("The following similar tasks were completed in the past.")
        lines.append("Use these lessons to avoid repeating mistakes.\n")

        for i, memory in enumerate(memories, 1):
            lines.append(f"--- Memory {i} ---")
            lines.append(memory["text"])
            lines.append("")

        return SystemMessage(content="\n".join(lines))

    def _ambiguity_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """
        Layer 8: Detect vague tasks and warn the agent to ask for clarification.
        """
        task = state.get("current_task", "")
        if not task:
            return None

        vague_signals = [
            "fix it", "make it better", "improve", "update", "refactor",
            "optimize", "clean up", "debug", "solve", "handle this",
            "do it", "change it", "check it", "look at it",
        ]

        specific_signals = [
            "file", "function", "class", "method", "module",
            "create", "add ", "delete", "rename", "move ",
            "test", "bug", "error", "line ", "import ",
            "path", "directory", "folder", "install",
        ]

        has_vague = any(v in task.lower() for v in vague_signals)
        has_specific = any(s in task.lower() for s in specific_signals)

        if not has_vague or has_specific:
            return None

        return SystemMessage(content=(
            "=== AMBIGUITY ALERT ===\n"
            "The current task appears vague or underspecified.\n\n"
            "Before acting, the agent should consider:\n"
            "- Which specific file, function, or module needs attention?\n"
            "- What does 'better' or 'fixed' mean in this context?\n"
            "- Are there tests, examples, or docs that clarify the goal?\n\n"
            "If the task remains unclear after checking available context, "
            "use ask_user() to get clarification rather than making assumptions."
        ))

    def _tone_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 9: Adapt tone based on task complexity."""
        from src.context.tone_adapter import ToneAdapter

        task = state.get("current_task", "")
        if not task:
            return None

        adapter = ToneAdapter()
        guidelines = adapter.get_tone_guidelines(task)
        return SystemMessage(content=guidelines)

    # =========================================================
    # HISTORY TRIMMING
    # =========================================================

    def _summarize_tool_messages(
        self,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """
        Run every ToolMessage through the SmartSummarizer.

        If a tool output is long, replace it with a short summary.
        If it's short, leave it alone.
        """
        result = []

        for message in messages:
            if isinstance(message, ToolMessage):
                # This might return the same message (if short) or a compressed one
                summarized = self.summarizer.summarize_message(message)
                result.append(summarized)
            else:
                # Not a tool message — leave it alone
                result.append(message)

        return result

    def _trim_history(
        self,
        history: list[BaseMessage],
        budget: int,
    ) -> list[BaseMessage]:
        """
        Trim conversation history to fit budget using smart compression.
        Strategy: Score messages by importance and keep the most valuable ones.
        Errors, user corrections, and recent decisions are preserved.
        Fluff and old successful steps are summarized or dropped.
        """
        if not history:
            return []

        # Use smart compressor for semantic importance-based trimming
        from src.context.smart_compressor import SmartCompressor
        compressor = SmartCompressor(model=self.model)
        compressed = compressor.compress(
            history,
            budget=budget,
            token_counter=lambda msgs, model: count_tokens(msgs, model),
        )

        # If we still couldn't fit everything, fall back to simple trim
        if count_tokens(compressed, self.model) > budget:
            return trim_messages_to_budget(history, budget, self.model)

        return compressed

    def _compress_history(
        self,
        history: list[BaseMessage],
        budget: int,
    ) -> list[BaseMessage]:
        """
        Compress old conversation turns into a summary.
        Keeps recent messages intact and summarizes older ones.
        """
        keep_recent = 4
        recent = history[-keep_recent:] if len(history) >= keep_recent else list(history)
        older = history[:-keep_recent] if len(history) > keep_recent else []

        if older:
            summary_lines = ["=== PREVIOUS CONVERSATION SUMMARY ==="]

            for message in older:
                if isinstance(message, ToolMessage):
                    content = (
                        message.content[:150]
                        if isinstance(message.content, str)
                        else str(message.content)[:150]
                    )
                    summary_lines.append(
                        f"- Used tool '{message.name or 'unknown'}': {content}..."
                    )

                elif isinstance(message, AIMessage):
                    tool_calls = getattr(message, "tool_calls", None)
                    if tool_calls:
                        calls = [call.get("name", "unknown") for call in tool_calls]
                        summary_lines.append(
                            f"- Agent decided to use: {', '.join(calls)}"
                        )
                    elif message.content:
                        content = (
                            message.content[:150]
                            if isinstance(message.content, str)
                            else str(message.content)[:150]
                        )
                        summary_lines.append(f"- Agent said: {content}...")

                elif isinstance(message, HumanMessage):
                    content = (
                        message.content[:150]
                        if isinstance(message.content, str)
                        else str(message.content)[:150]
                    )
                    summary_lines.append(f"- User said: {content}...")

            summary = SystemMessage(content="\n".join(summary_lines))
            compressed = [summary] + recent

            if count_tokens(compressed, self.model) <= budget:
                return compressed

        return trim_messages_to_budget(history, budget, self.model)

    # =========================================================
    # HELPER METHODS
    # =========================================================

    @staticmethod
    def _is_plan_complete(plan: list[dict]) -> bool:
        """Check if all plan steps are done."""
        if not plan:
            return False
        return all(step.get("status") == "completed" for step in plan)

    # =========================================================
    # PLANNER CONTEXT METHODS
    # =========================================================

    @staticmethod
    def _planner_prompt(planner_prompt: str) -> str:
        """Add strict output rules so reasoning models return parseable plans."""
        return (
            planner_prompt
            + "\n\nReturn ONLY the final plan as a numbered list."
            + "\nStart every line with a number like `1.`."
            + "\nDo not include analysis, reasoning, headings, examples, markdown, commentary, or duplicate steps."
            + "\nDo not include unrelated filler steps."
            + "\nKeep the plan concise: usually 3-8 steps."
        )

    def build_planner_messages(self, task: str, planner_prompt: str) -> list[BaseMessage]:
        """
        Build messages for the planner node.
        This is simpler — just the prompt + the task.
        """
        return [
            SystemMessage(content=self._planner_prompt(planner_prompt)),
            HumanMessage(content=task),
        ]

    def build_replanner_messages(
        self,
        task: str,
        plan: list[dict],
        failed_steps: list[str],
        planner_prompt: str,
        prior_attempts: list[dict] | None = None,
    ) -> list[BaseMessage]:
        """
        Build messages for the replanner node.
        This includes the original task, completed work, failures,
        and lessons from past attempts.
        """
        completed = [
            step["description"]
            for step in plan
            if step.get("status") == "completed"
        ]

        remaining = [
            step["description"]
            for step in plan
            if step.get("status") != "completed"
        ]

        lines = [
            f"Original task:\n{task}\n",
            "Already completed:",
        ]
        for step in completed:
            lines.append(f"  - {step}")

        lines.append("\nRemaining or blocked work:")
        for step in remaining:
            lines.append(f"  - {step}")

        lines.append("\nFailures:")
        for failure in failed_steps[-3:]:
            lines.append(f"  - {failure}")

        # Add lessons from past attempts
        if prior_attempts:
            lines.append("\n=== LESSONS FROM PAST ATTEMPTS ===")
            for attempt in prior_attempts[-2:]:
                lines.append(f"  - {attempt.get('lesson', 'No lesson recorded')}")

        lines.append("\nCreate a revised plan for ONLY the remaining work.")
        lines.append("Do not repeat completed work.")
        lines.append("Learn from past failures and choose a different approach.")

        return [
            SystemMessage(content=self._planner_prompt(planner_prompt)),
            HumanMessage(content="\n".join(lines)),
        ]

    def build_reviser_messages(
        self,
        task: str,
        plan: list[dict],
        revision: str,
        planner_prompt: str,
    ) -> list[BaseMessage]:
        """Build messages for the plan reviser node."""
        plan_text = "\n".join(
            f"{step.get('id', i)}. {step.get('description', '')}"
            for i, step in enumerate(plan, start=1)
        )

        content = (
            f"Original task:\n{task}\n\n"
            f"Current plan:\n{plan_text}\n\n"
            f"User requested this plan change:\n{revision}\n\n"
            "Revise the current plan according to the user's request.\n"
            "Preserve steps that do not need to change.\n"
            "Return the complete revised plan.\n"
            "Do not execute anything."
        )

        return [
            SystemMessage(content=self._planner_prompt(planner_prompt)),
            HumanMessage(content=content),
        ]
