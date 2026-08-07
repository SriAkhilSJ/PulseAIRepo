
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

Execution model (honest): spawn() invokes the child graph SYNCHRONOUSLY
inside the parent's tool call — one delegation blocks the parent's turn.
D33 added spawn_batch(): several children run CONCURRENTLY in a bounded
thread pool (hermes steal #9, §45) with index-ordered results; the batch
tool is delegate_to_subagent_batch in chat_graph.py. Structural safety
(verified, ARCHITECTURE_REVIEW.md §27):
- depth cap = 1 (prefix check on the caller's thread_id)
- recursion_limit=50 on every invoke; 60s LLM call timeouts
- a crashed child is caught at THIS boundary (spawn returns a graceful
  failure string the parent model can recover from). Measured against
  langgraph 1.2.10: its DEFAULT ToolNode handler converts only
  ToolInvocationError and RE-RAISES anything else — earlier belief that
  "ToolNode converts tool crashes" held only under pre-1.x langgraph
  (suite caught the drift; ARCHITECTURE_REVIEW.md §27).
- results are capped at 2000 chars before entering the parent's context

What this changes:
- Complex tasks are split across specialized agents
- The main agent coordinates instead of doing everything itself
"""
import uuid
from typing import Literal, Any
from src.config.settings import LLM_PROVIDER, LLM_MODEL

# Orphaned entries (crash between spawn and get_result) never exceed this.
_MAX_COMPLETED_AGENTS = 50

class SubAgentCoordinator:
    """
    Spawns and manages sub-agents for specialized tasks.
    """
    def __init__(self):
        self._active_agents: dict[str, dict] = {}
        # D33: batches mutate the registry from worker THREADS — dict ops
        # are GIL-atomic, but insert+evict is a two-step sequence, so the
        # mutation itself takes a lock (never held across child invokes).
        import threading
        self._lock = threading.Lock()

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

        NOTE: the result payload lives in _active_agents ONLY until
        get_result() reads it (pop-on-read — before that fix the dict grew
        by one full result string per spawn for the process's whole life).
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

        # Run the sub-agent synchronously. Crash boundary: a child failure
        # (provider errors after retries, nested bugs) must degrade to a
        # sentence the parent can reason about — NEVER an exception climbing
        # the tool stack, because langgraph>=1.1's default ToolNode handler
        # re-raises non-validation exceptions, killing the parent's turn.
        try:
            result = invoke_agent(
                message=focused_task,
                thread_id=agent_id,
                provider=provider,
                model=model,
            )
        except Exception as exc:
            result = (
                f"⛔ Sub-agent crashed: {exc!r}\n"
                "The main conversation is unaffected. Possible causes: provider "
                "outage/rate-limit, or a bug in the delegated step. You can retry "
                "with a narrower task or complete it directly here."
            )

        with self._lock:
            self._active_agents[agent_id] = {
                "mode": mode,
                "task": task,
                "result": result,
                "parent": parent_thread_id,
            }
            # Belt-and-braces bound: if an invoke raises mid-delegation (the
            # entry then never gets popped), cap the registry at the newest
            # 50 — dicts keep insertion order, oldest orphans evicted first.
            while len(self._active_agents) > _MAX_COMPLETED_AGENTS:
                self._active_agents.pop(next(iter(self._active_agents)))

        return agent_id

    def spawn_batch(
        self,
        mode: "Literal['research', 'code', 'test', 'review']",
        tasks: list[str],
        parent_thread_id: str,
        provider: str = LLM_PROVIDER,
        model: str = LLM_MODEL,
        max_workers: int = 4,
    ) -> list[str]:
        """D33 (steal #9, §45): run several sub-agents CONCURRENTLY.

        Pattern lifted from hermes delegate_tool.py:3208-3299:
        ThreadPoolExecutor with one contextvars.Context per child, futures
        mapped to task INDEX so results come back in input order, and a
        per-child crash captured at its own slot (a dead child never takes
        the batch down). Honest deltas from upstream, by design:
        - their wait(FIRST_COMPLETED, 0.5s) loop exists to honor a PARENT
          INTERRUPT signal; our graph has no such signal today, so plain
          as_completed is used (the loop is reintroduced with interrupts).
        - single-task batches take the legacy synchronous spawn() path —
          byte-identical behavior for the common case (pinned).

        Returns agent ids in the SAME order as `tasks` (pop with
        get_result). With the D32 file-state guard armed, concurrent code
        sub-agents cannot silently clobber each other's files.
        """
        if not tasks:
            return []
        if len(tasks) == 1:
            return [self.spawn(mode, tasks[0], parent_thread_id,
                               provider=provider, model=model)]

        import contextvars
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: list[Optional[str]] = [None] * len(tasks)
        workers = max(1, min(max_workers, len(tasks)))

        def _one(index: int, task: str) -> str:
            return self.spawn(mode=mode, task=task,
                              parent_thread_id=parent_thread_id,
                              provider=provider, model=model)

        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="pulseai-sub") as pool:
            future_to_index = {}
            for index, task in enumerate(tasks):
                ctx = contextvars.copy_context()
                future_to_index[pool.submit(ctx.run, _one, index, task)] = index
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    results[index] = future.result()
                except Exception as exc:  # spawn has its own crash net; this
                    # is paranoia-grade — a batch entry must NEVER go missing.
                    results[index] = (
                        f"⛔ Sub-agent batch worker {index} failed before "
                        f"registering: {exc!r}"
                    )
        return [str(r) for r in results]

    def get_result(self, agent_id: str) -> str:
        # Pop-on-read: a result has exactly one consumer (the delegating tool
        # call) — the entry must die the moment it is delivered, or the
        # singleton accumulates every sub-agent result for the process's life.
        agent = self._active_agents.pop(agent_id, None)
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
