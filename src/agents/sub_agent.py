
"""
Sub-Agent Coordinator for PulseCodeAI
=====================================
Spawns specialized child agents for focused work.
Each sub-agent gets a narrow task and reports back.

Modes:
- research: Web search + fetch to gather information
- code: File tools to implement a specific function
- test: Terminal tools to run and verify tests
- review: Read-only tools to audit code

What this changes:
- Complex tasks are split across specialized agents
- Research happens in parallel with coding (sequentially for now)
- The main agent coordinates instead of doing everything itself
"""
import uuid
from typing import Literal, Any
from src.config.settings import LLM_PROVIDER, LLM_MODEL

class SubAgentCoordinator:
    """
    Spawns and manages sub-agents for specialized tasks.
    """
    def __init__(self):
        self._active_agents: dict[str, dict] = {}

    def spawn(
        self,
        mode: Literal["research", "code", "test", "review"],
        task: str,
        parent_thread_id: str,
        provider: str = LLM_PROVIDER,
        model: str = LLM_MODEL,
    ) -> str:
        """
        Spawn a sub-agent with a focused task.
        Returns the sub-agent's thread ID.
        """
        from src.graphs.chat_graph import invoke_agent
        agent_id = f"sub-{mode}-{uuid.uuid4().hex[:6]}"

        # Build a focused prompt based on mode
        prompts = {
            "research": (
                "You are a research specialist. Your job is to gather information "
                "from the web and codebase. Do NOT write code. Do NOT run commands. "
                "Just search, read, and summarize findings clearly.\n\n"
                f"Task: {task}"
            ),
            "code": (
                "You are a coding specialist. Your job is to write or edit code. "
                "Use file tools carefully. Verify your changes compile or parse correctly. "
                "Do NOT do web research — assume the requirements are clear.\n\n"
                f"Task: {task}"
            ),
            "test": (
                "You are a testing specialist. Your job is to run tests, verify behavior, "
                "and report results. Use terminal tools. Do NOT modify source code unless "
                "fixing a broken test.\n\n"
                f"Task: {task}"
            ),
            "review": (
                "You are a code reviewer. Your job is to read code and provide feedback. "
                "Do NOT write or edit files. Just read and critique.\n\n"
                f"Task: {task}"
            ),
        }

        focused_task = prompts.get(mode, task)

        # Run the sub-agent synchronously
        result = invoke_agent(
            message=focused_task,
            thread_id=agent_id,
            provider=provider,
            model=model,
        )

        self._active_agents[agent_id] = {
            "mode": mode,
            "task": task,
            "result": result,
            "parent": parent_thread_id,
        }

        return agent_id

    def get_result(self, agent_id: str) -> str:
        agent = self._active_agents.get(agent_id)
        if not agent:
            return f"No sub-agent found with ID: {agent_id}"
        return agent["result"]

    def list_active(self) -> list[dict]:
        return [
            {
                "id": aid,
                "mode": info["mode"],
                "task_preview": info["task"][:50],
            }
            for aid, info in self._active_agents.items()
        ]

    def clear(self) -> None:
        self._active_agents.clear()

# Global singleton
subagent_coordinator = SubAgentCoordinator()
