
"""
Sub-Agent Coordinator for CrusorCodeAI
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
        allowed_capabilities: tuple[str, ...] | None = None,
        description: str = "",
        background: bool = False,
        tool_call_id: str | None = None,
        emit_events: bool = True,
        agent_id: str | None = None,
        workspace: str | None = None,
    ) -> str:
        """
        Spawn a sub-agent with a focused task.
        Returns the sub-agent's thread ID.

        NOTE: the result payload lives in _active_agents ONLY until
        get_result() reads it (pop-on-read — before that fix the dict grew
        by one full result string per spawn for the process's whole life).
        """
        from src.graphs.chat_graph import invoke_agent
        # One id per child, everywhere (OpenCode: the child SESSION id
        # is the conversation id is the navigation target). A caller
        # that already minted the child's identity — the lifecycle —
        # passes it in so the graph thread, the store rows, the bus
        # events and the desktop's navigation all name the SAME child.
        # Previously the lifecycle child ran on a private coordinator
        # id while every surface pointed at the lifecycle id, so
        # opening the child read an empty checkpoint.
        agent_id = agent_id or f"sub-{mode}-{uuid.uuid4().hex[:6]}"

        # Visibility contract (OpenCode parity): a spawned child is
        # announced BEFORE it runs and again when it settles, on the
        # same subagent.updated bus event the lifecycle emits, so the
        # desktop learns the child session exists while it works —
        # delegate_to_subagent_batch previously registered children
        # only AFTER they finished and never emitted, leaving the
        # batch card with nothing to navigate to. The lifecycle owns
        # its own event stream for the same child and passes
        # emit_events=False so one child never speaks twice.
        def _emit(state: str, result_text: str | None = None,
                  error_text: str | None = None) -> None:
            if not emit_events:
                return
            try:
                from src.dashboard.event_bus import event_bus
                event_bus.emit("subagent.updated", {
                    "thread_id": parent_thread_id,
                    "subagent_id": agent_id,
                    "child_thread_id": agent_id,
                    "parent_session_id": parent_thread_id,
                    "state": state,
                    "goal": task[:200],
                    "description": (description or task[:50])[:200],
                    "mode": mode,
                    "agent_name": mode,
                    "tool_call_id": tool_call_id,
                    "tool_calls": 0,
                    "background": background,
                    "result": (result_text or "")[:2000] if result_text else None,
                    "error": (error_text or "")[:500] if error_text else None,
                })
            except Exception:
                pass

        # Register in the store at START (state running) so resume and
        # list_by_parent see the child while it works; the completion
        # block below updates the same row. Only create if absent (the
        # lifecycle pre-creates its own row under its handle id).
        try:
            from src.runtime.subagent_store import get_store, SubagentSessionRow
            import time as _t0
            _store0 = get_store()
            if not _store0.get(agent_id):
                _store0.create(SubagentSessionRow(
                    subagent_id=agent_id,
                    parent_session_id=parent_thread_id,
                    child_thread_id=agent_id,
                    mode=mode,
                    goal=task,
                    description=(description or task[:50])[:200],
                    agent_name=mode,
                    state="running",
                    created_at=_t0.time(),
                    updated_at=_t0.time(),
                    tool_call_id=tool_call_id,
                    tool_calls=0,
                    background=background,
                    result="",
                ))
        except Exception:
            pass
        # The child is a first-class session row (OpenCode: children
        # live in the same session table, linked by parentID) so the
        # session list, resume and titling see it like any session.
        # Only when the caller knows the parent's workspace — a row
        # minted workspace-less would sort into no folder at all.
        if workspace is not None:
            try:
                from src.runtime.session_store import get_session_store
                from src.runtime.session_titling import ensure_unique_title, shorten_title
                _sessions = get_session_store()
                if _sessions.get_session(agent_id) is None:
                    _sessions.create_session(
                        agent_id, workspace,
                        title=ensure_unique_title(
                            _sessions, workspace,
                            shorten_title(task) or "Sub-agent task"),
                        parent_session_id=(parent_thread_id
                                           if parent_thread_id != "main" else None),
                    )
            except Exception:
                pass
        _emit("running")

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

        _crashed = False
        # Run the sub-agent synchronously. Crash boundary: a child failure
        # (provider errors after retries, nested bugs) must degrade to a
        # sentence the parent can reason about — NEVER an exception climbing
        # the tool stack, because langgraph>=1.1's default ToolNode handler
        # re-raises non-validation exceptions, killing the parent's turn.
        try:
            invoke_kwargs = {
                "message": focused_task,
                "thread_id": agent_id,
                "provider": provider,
                "model": model,
                # Children work where the parent works (OpenCode: the
                # child session shares the parent's location) — the
                # old default ran them in the engine's cwd (".").
                "workspace": workspace if workspace else ".",
            }
            # Preserve the legacy call shape for ordinary delegation and test
            # doubles. Managed lifecycle launches pass an explicit tuple and
            # therefore activate strict child capability binding.
            if allowed_capabilities is not None:
                invoke_kwargs["scope_capabilities"] = allowed_capabilities
            result = invoke_agent(**invoke_kwargs)
        except Exception as exc:
            _crashed = True
            result = (
                f"⛔ Sub-agent crashed: {exc!r}\n"
                "The main conversation is unaffected. Possible causes: provider "
                "outage/rate-limit, or a bug in the delegated step. You can retry "
                "with a narrower task or complete it directly here."
            )
        final_state = "failed" if _crashed else "succeeded"

        with self._lock:
            self._active_agents[agent_id] = {
                "mode": mode,
                "task": task,
                "description": (description or task[:50])[:200],
                "result": result,
                "parent": parent_thread_id,
                "child_thread_id": agent_id,
                "tool_call_id": tool_call_id,
                "background": background,
                "agent_name": mode,
            }
            # Belt-and-braces bound: if an invoke raises mid-delegation (the
            # entry then never gets popped), cap the registry at the newest
            # 50 — dicts keep insertion order, oldest orphans evicted first.
            while len(self._active_agents) > _MAX_COMPLETED_AGENTS:
                self._active_agents.pop(next(iter(self._active_agents)))

        # Persist to store as well (OpenCode parity): update the row
        # opened at spawn start (create only as a fallback if the start
        # registration failed), then announce the settled state.
        try:
            from src.runtime.subagent_store import get_store, SubagentSessionRow
            import time
            store = get_store()
            if store.get(agent_id):
                store.update(agent_id, result=result[:32000], state=final_state, updated_at=time.time())
            else:
                store.create(SubagentSessionRow(
                    subagent_id=agent_id,
                    parent_session_id=parent_thread_id,
                    child_thread_id=agent_id,
                    mode=mode,
                    goal=task,
                    description=(description or task[:50])[:200],
                    agent_name=mode,
                    state=final_state,
                    created_at=time.time(),
                    updated_at=time.time(),
                    tool_call_id=tool_call_id,
                    tool_calls=0,
                    background=background,
                    result=result[:32000],
                ))
        except Exception:
            pass
        _emit(final_state, result_text=result,
              error_text=result if _crashed else None)

        return agent_id

    def spawn_batch(
        self,
        mode: "Literal['research', 'code', 'test', 'review']",
        tasks: list[str],
        parent_thread_id: str,
        provider: str = LLM_PROVIDER,
        model: str = LLM_MODEL,
        max_workers: int = 4,
        workspace: str | None = None,
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
                               provider=provider, model=model,
                               workspace=workspace)]

        import contextvars
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: list[Optional[str]] = [None] * len(tasks)
        workers = max(1, min(max_workers, len(tasks)))

        def _one(index: int, task: str) -> str:
            return self.spawn(mode=mode, task=task,
                              parent_thread_id=parent_thread_id,
                              provider=provider, model=model,
                              description=task[:50],
                              background=False,
                              workspace=workspace)

        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="crusorai-sub") as pool:
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
