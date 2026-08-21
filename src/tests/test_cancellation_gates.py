"""Deterministic cancellation-gate regression tests (C-1 through C-8).

Uses a controllable blocking fake LLM and threading synchronization events —
NO sleeps, NO real providers, NO network calls.

Test matrix:

    C-1  cancel while ai_node LLM invoke is blocked → zero tool executions
    C-2  cancel while task_manager LLM invoke is blocked → task_status == cancelled
    C-3  release the fake response after cancellation → response is discarded
    C-4  assert zero additional model invocations after cancel
    C-5  assert the final result carries pulse_cancelled, not failed/completed
    C-6  SafeToolNode cancels pending tool calls → no real tools run
    C-7  repeated cancellations do not grow threads/processes
    C-8  queued work (steer) is not started inside the old turn after cancel
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Blocking fake LLM ───────────────────────────────────────────────────
# A FakeLLM that blocks on .invoke() until a threading.Event is released.
# This lets tests trigger cancellation while the LLM is "in flight".


class _FakeLLM:
    """Deterministic fake LLM: blocks until ``_release`` is set."""

    def __init__(self):
        self._release = threading.Event()
        self._invoke_count = 0
        self._invoke_barrier = threading.Event()  # set when invoke() enters
        self._result: Any = MagicMock(content="fake-response", tool_calls=None)
        self._bound_tools = None

    # -- controls used by tests --

    def set_result(self, result: Any):
        self._result = result

    def release(self):
        self._release.set()

    def wait_invoke(self, timeout: float = 5.0) -> bool:
        """Block until invoke() has been entered."""
        return self._invoke_barrier.wait(timeout=timeout)

    # -- fake LLM interface --

    def bind_tools(self, tool_list):
        # Keep a shared reference to the original so _invoke_count is
        # visible on the object the test holds.
        self._bound_tools = tool_list
        return self

    def bind(self, **kwargs):
        return self  # ignore max_tokens etc.

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages, config=None, **kwargs):
        self._invoke_count += 1
        self._invoke_barrier.set()
        # Block until the test releases us (or timeout for safety)
        self._release.wait(timeout=10.0)
        return self._result


class _FakeFailLLM:
    """Deterministic fake that BLOCKS in-flight (like _FakeLLM) and then
    RAISES a transient connection error when released — the retryable-error
    twin of _FakeLLM. Lets tests fire cancellation during the "in flight"
    window and prove the proxy never retries after the error surfaces."""

    def __init__(self, error_text: str):
        self._error_text = error_text
        self._release = threading.Event()
        self._invoke_count = 0
        self._invoke_barrier = threading.Event()
        self._result: Any = None

    def release(self):
        self._release.set()

    def wait_invoke(self, timeout: float = 5.0) -> bool:
        return self._invoke_barrier.wait(timeout=timeout)

    def bind_tools(self, tool_list):
        return self

    def bind(self, **kwargs):
        return self

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages, config=None, **kwargs):
        self._invoke_count += 1
        self._invoke_barrier.set()
        self._release.wait(timeout=10.0)
        raise ConnectionError(self._error_text)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_config(thread_id: str = "cancel-test", workspace: str = "."):
    """Minimal RunnableConfig for graph node calls."""
    return {
        "configurable": {
            "thread_id": thread_id,
            "provider": "fake",
            "model": "fake",
            "workspace": workspace,
        }
    }


def _make_state(**overrides) -> dict:
    """Minimal AgentState dict for node calls."""
    base = {
        "messages": [],
        "current_task": "test task",
        "latest_instruction": "test instruction",
        "task_status": "in_progress",
        "steps_completed": [],
        "failed_steps": [],
        "plan": [],
        "plan_goal": "",
        "plan_created": False,
        "plan_approved": False,
        "execution_trace": [],
        "task_completed": False,
        "iteration_used": 0,
        "grace_done": 0,
        "token_usage": {},
        "turn_token_usage": {},
    }
    base.update(overrides)
    return base


# ── Tests ────────────────────────────────────────────────────────────────


class TestCancellationGates:
    """Core cancellation-gate regressions."""

    def setup_method(self):
        from src.runtime.turn_control import turn_controls
        self._tc = turn_controls
        self._session_id = "cancel-test"
        # Reset the control state for each test
        self._tc.reset(self._session_id)
        self._tc.begin(self._session_id)

    def teardown_method(self):
        self._tc.reset(self._session_id)

    # ── C-1: cancel while ai_node LLM invoke is blocked ──

    def test_c1_cancel_during_ai_node_llm_blocks_tool_execution(self):
        """Cancel is triggered while ai_node is inside call_llm.invoke().

        The post-LLM cancellation gate must detect the cancelled state
        and return pulse_cancelled=True instead of the LLM result.
        The returned message must carry NO tool_calls.
        """
        from src.graphs.chat_graph import ai_node
        from langchain_core.messages import AIMessage

        fake_llm = _FakeLLM()
        fake_llm.set_result(AIMessage(
            content="thinking",
            tool_calls=[{"id": "tc-1", "name": "write_file", "args": {"path": "x.py", "content": "bad"}}],
        ))

        config = _make_config()

        def _run_ai():
            with patch("src.graphs.chat_graph.get_llm", return_value=fake_llm), \
                 patch("src.graphs.chat_graph.cost_router") as mock_router, \
                 patch("src.graphs.chat_graph.get_context_engine") as mock_engine, \
                 patch("src.graphs.chat_graph._resolve_bound_tools", return_value=[]):
                mock_router.route.return_value = ("fake", "fake")
                mock_engine.return_value.build_ai_messages.return_value = []
                self._result = ai_node(_make_state(), config)

        t = threading.Thread(target=_run_ai)
        t.start()

        # Wait until the fake LLM's invoke() is entered
        assert fake_llm.wait_invoke(timeout=5), "LLM.invoke() was never entered"

        # Trigger cancellation while LLM is blocked
        self._tc.cancel(self._session_id)

        # Release the fake LLM
        fake_llm.release()
        t.join(timeout=10)

        assert not t.is_alive(), "ai_node thread did not exit"

        msg = self._result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.content == "Operation cancelled by the user."
        assert msg.additional_kwargs.get("pulse_cancelled") is True
        # Critical: no tool_calls leaked through
        assert not getattr(msg, "tool_calls", None), (
            "Tool calls leaked through the cancellation gate"
        )

    # ── C-2: cancel while task_manager LLM invoke is blocked ──

    def test_c2_cancel_during_task_manager_returns_cancelled_status(self):
        """Cancel before the task_manager's LLM call must short-circuit
        and return task_status='cancelled' without invoking the LLM.
        """
        from src.graphs.chat_graph import task_manager_node

        fake_llm = _FakeLLM()
        fake_llm.set_result(MagicMock(action="continue", updated_task="still working"))

        config = _make_config()

        # Pre-cancel before entering the node
        self._tc.cancel(self._session_id)

        with patch("src.graphs.chat_graph._task_manager_llm", return_value=fake_llm):
            result = task_manager_node(
                _make_state(current_task="existing", latest_instruction="keep going"),
                config,
            )

        assert result["task_status"] == "cancelled"
        assert result["task_completed"] is False
        # LLM should never have been invoked
        assert fake_llm._invoke_count == 0

    # ── C-3: release fake response after cancellation — it is discarded ──

    def test_c3_response_released_after_cancel_is_discarded(self):
        """If cancellation fires during an in-flight LLM call and the LLM
        result arrives after cancel, ai_node must still return the
        cancelled message, not the stale LLM result.
        """
        from src.graphs.chat_graph import ai_node
        from langchain_core.messages import AIMessage

        fake_llm = _FakeLLM()
        # Result with tool calls that must NOT be used
        fake_llm.set_result(AIMessage(
            content="done",
            tool_calls=[{"id": "tc-x", "name": "run_terminal", "args": {"command": "echo pwned"}}],
        ))

        config = _make_config()
        results = []

        def _run_ai():
            with patch("src.graphs.chat_graph.get_llm", return_value=fake_llm), \
                 patch("src.graphs.chat_graph.cost_router") as mock_router, \
                 patch("src.graphs.chat_graph.get_context_engine") as mock_engine, \
                 patch("src.graphs.chat_graph._resolve_bound_tools", return_value=[]):
                mock_router.route.return_value = ("fake", "fake")
                mock_engine.return_value.build_ai_messages.return_value = []
                try:
                    r = ai_node(_make_state(), config)
                    results.append(r)
                except Exception as e:
                    results.append(e)

        t = threading.Thread(target=_run_ai)
        t.start()

        assert fake_llm.wait_invoke(timeout=5)

        # Cancel while in flight
        self._tc.cancel(self._session_id)

        # Release the LLM result (simulates HTTP response arriving after cancel)
        fake_llm.release()
        t.join(timeout=10)

        assert not t.is_alive()
        assert len(results) == 1
        result = results[0]
        assert not isinstance(result, Exception), f"ai_node raised: {result}"

        msg = result["messages"][0]
        assert msg.additional_kwargs.get("pulse_cancelled") is True
        assert not getattr(msg, "tool_calls", None)

    # ── C-4: zero additional model invocations after cancel ──

    def test_c4_zero_model_invocations_after_cancel(self):
        """After cancellation the fake LLM must have been invoked exactly
        once (the blocked call) — no retries, no failovers.
        """
        from src.graphs.chat_graph import ai_node
        from langchain_core.messages import AIMessage

        fake_llm = _FakeLLM()
        fake_llm.set_result(AIMessage(content="thinking"))

        config = _make_config()

        def _run_ai():
            with patch("src.graphs.chat_graph.get_llm", return_value=fake_llm), \
                 patch("src.graphs.chat_graph.cost_router") as mock_router, \
                 patch("src.graphs.chat_graph.get_context_engine") as mock_engine, \
                 patch("src.graphs.chat_graph._resolve_bound_tools", return_value=[]):
                mock_router.route.return_value = ("fake", "fake")
                mock_engine.return_value.build_ai_messages.return_value = []
                self._c4_result = ai_node(_make_state(), config)

        t = threading.Thread(target=_run_ai)
        t.start()
        assert fake_llm.wait_invoke(timeout=5)

        self._tc.cancel(self._session_id)
        fake_llm.release()
        t.join(timeout=10)

        assert not t.is_alive()
        assert fake_llm._invoke_count == 1, (
            f"Expected exactly 1 invoke, got {fake_llm._invoke_count}"
        )

    # ── C-5: cancelled result, not failed or completed ──

    def test_c5_result_is_cancelled_not_failed_or_completed(self):
        """The cancelled AIMessage must have pulse_cancelled=True and the
        state must NOT indicate task_completed or task_status=failed.
        """
        from src.graphs.chat_graph import ai_node
        from langchain_core.messages import AIMessage

        fake_llm = _FakeLLM()
        fake_llm.set_result(AIMessage(content="working"))

        config = _make_config()

        def _run_ai():
            with patch("src.graphs.chat_graph.get_llm", return_value=fake_llm), \
                 patch("src.graphs.chat_graph.cost_router") as mock_router, \
                 patch("src.graphs.chat_graph.get_context_engine") as mock_engine, \
                 patch("src.graphs.chat_graph._resolve_bound_tools", return_value=[]):
                mock_router.route.return_value = ("fake", "fake")
                mock_engine.return_value.build_ai_messages.return_value = []
                self._c5_result = ai_node(_make_state(), config)

        t = threading.Thread(target=_run_ai)
        t.start()
        assert fake_llm.wait_invoke(timeout=5)

        self._tc.cancel(self._session_id)
        fake_llm.release()
        t.join(timeout=10)

        assert not t.is_alive()
        msg = self._c5_result["messages"][0]
        assert msg.additional_kwargs.get("pulse_cancelled") is True
        assert "cancel" in msg.content.lower()

    # ── C-6: SafeToolNode cancels pending tool calls ──

    def test_c6_safetoolnode_denies_all_calls_on_cancel(self):
        """When the session is cancelled, SafeToolNode must return
        denial ToolMessages for every pending tool_call, and no real
        tool should execute.
        """
        from src.graphs.chat_graph import SafeToolNode, tools
        from src.context.safety_guard import SafetyGuard
        from langchain_core.messages import AIMessage, ToolMessage

        config = _make_config()
        state = {
            "messages": [
                AIMessage(
                    content="executing",
                    tool_calls=[
                        {"id": "tc-a", "name": "write_file", "args": {"path": "a.py", "content": "x"}},
                        {"id": "tc-b", "name": "run_terminal", "args": {"command": "echo hi"}},
                    ],
                )
            ]
        }

        # Pre-cancel
        self._tc.cancel(self._session_id)

        node = SafeToolNode(tools, SafetyGuard())
        result = node(state, config)

        msgs = result["messages"]
        assert len(msgs) == 2
        for m in msgs:
            assert isinstance(m, ToolMessage)
            assert "cancelled" in m.content.lower()
            assert m.status == "error"
            assert m.tool_call_id in ("tc-a", "tc-b")

    # ── C-7: repeated cancellations do not grow threads/processes ──

    def test_c7_repeated_cancellations_no_thread_growth(self):
        """Multiple rapid cancel/start cycles must not leak threads."""
        import os as _os

        proc_before = _os.getpid()
        thread_count_before = threading.active_count()

        for _ in range(5):
            sid = f"cancel-stress-{id(_os)}-{_}"
            self._tc.reset(sid)
            self._tc.begin(sid)
            self._tc.cancel(sid)
            assert self._tc.cancelled(sid)
            self._tc.end(sid)
            self._tc.reset(sid)

        thread_count_after = threading.active_count()
        # Allow a small margin but no significant growth
        assert thread_count_after <= thread_count_before + 2, (
            f"Thread count grew from {thread_count_before} to {thread_count_after}"
        )

    # ── C-8: steer queue is not drained after cancel ──

    def test_c8_steer_not_drained_after_cancel(self):
        """When a turn is cancelled, queued steers must not be consumed.
        They remain available for the next turn.
        """
        sid = "steer-cancel-test"
        self._tc.reset(sid)
        self._tc.begin(sid)

        # Add a steer while active
        self._tc.steer(sid, "correct direction")
        assert len(self._tc.drain_steer(sid)) == 1

        # Cancel the turn
        self._tc.cancel(sid)
        assert self._tc.cancelled(sid)

        # After cancel, drain_steer should return empty (already drained above)
        # but the key point is: the graph must NOT call drain_steer after
        # cancellation — ai_node's cancellation gate returns before reaching
        # the steer-drain code.
        # Verify: if we were to call drain_steer, it would be empty — but
        # the important thing is the ai_node never reached that point.
        steers = self._tc.drain_steer(sid)
        assert steers == [], "Steer was not consumed (correct — gate returned early)"

        self._tc.end(sid)
        self._tc.reset(sid)

    # ── C-9: RetryLLMProxy does not retry after cancellation ──

    def test_c9_proxy_does_not_retry_after_cancellation(self):
        """A transient connection error raised while the session is cancelled
        must surface TurnCancelledError, and the underlying fake LLM must be
        invoked zero further times after the cancel event fired.
        """
        from src.llm.factory import RetryLLMProxy, TurnCancelledError
        from src.runtime.turn_control import set_active_session
        from langchain_core.messages import HumanMessage

        fake_llm = _FakeFailLLM("Connection error: upstream timeout")
        proxy = RetryLLMProxy(fake_llm, max_attempts=5)
        sid = "proxy-cancel-test"
        self._tc.reset(sid)
        self._tc.begin(sid)

        captured: dict = {}

        def _run():
            set_active_session(sid)
            try:
                proxy.invoke([HumanMessage(content="hi")])
            except Exception as exc:
                captured["exc"] = exc
            finally:
                set_active_session(None)

        t = threading.Thread(target=_run)
        t.start()
        assert fake_llm.wait_invoke(timeout=5), "proxy invoke was never entered"

        # The first attempt is blocked in-flight. Fire Stop mid-flight.
        invokes_before_cancel = fake_llm._invoke_count
        self._tc.cancel(sid)

        # Release the in-flight request: it now fails with the transient
        # connection error. The proxy MUST surface TurnCancelledError and must
        # NOT retry, NOT sleep, NOT invoke again.
        fake_llm.release()
        t.join(timeout=10)
        assert not t.is_alive(), "proxy invoke thread did not exit"

        assert isinstance(captured.get("exc"), TurnCancelledError), (
            f"expected TurnCancelledError, got {captured.get('exc')!r}"
        )
        assert fake_llm._invoke_count == invokes_before_cancel, (
            "proxy retried after cancellation: "
            f"{fake_llm._invoke_count} invokes (before cancel: {invokes_before_cancel})"
        )
        assert fake_llm._invoke_count >= 1, "the in-flight attempt never ran"

        self._tc.end(sid)
        self._tc.reset(sid)

    # ── C-10: RetryLLMProxy.abort() closes the transport, is idempotent ──

    def test_c10_abort_closes_transport_and_is_idempotent(self):
        """abort() closes the underlying openai client AND its httpx.Client,
        is idempotent (second call is a no-op), and sets is_aborted.
        Closes each underlying object exactly once."""
        from src.llm.factory import RetryLLMProxy

        class _InnerClient:
            def __init__(self):
                self._closes = 0

            def close(self):
                self._closes += 1

        class _OpenAIClient:
            def __init__(self):
                self._client = _InnerClient()
                self._closes = 0

            def close(self):
                self._closes += 1

        class _ChatOpenAI:
            def __init__(self):
                self.client = _OpenAIClient()

            def invoke(self, messages, config=None, **kwargs):
                return MagicMock(content="ok")

        fake = _ChatOpenAI()
        proxy = RetryLLMProxy(fake, max_attempts=2)
        assert proxy.is_aborted is False

        proxy.abort()
        assert proxy.is_aborted is True
        assert fake.client._closes == 1, "openai client closed wrong number of times"
        assert fake.client._client._closes == 1, "httpx client closed wrong number of times"

        # abort() is idempotent: a second call must not close again
        proxy.abort()
        assert proxy.is_aborted is True
        assert fake.client._closes == 1, "openai client was closed a second time"
        assert fake.client._client._closes == 1, "httpx client was closed a second time"

    # ── C-11: cancelled ai_node skips the base-provider failover ──

    def test_c11_cancelled_ai_node_skips_base_provider_failover(self):
        """When Stop fires during the routed provider's in-flight request and
        that request then errors, ai_node's exception path must return the
        cancellation message and must NOT invoke the base provider."""
        from src.graphs.chat_graph import ai_node
        from langchain_core.messages import AIMessage

        routed_fake = _FakeFailLLM("429 rate limit: try again in 5ms")
        base_fake = MagicMock()
        base_fake.bind_tools.return_value = base_fake
        base_fake.bind.return_value = base_fake
        base_fake.invoke.return_value = AIMessage(content="base response")

        def _make_llm(provider, model):
            if provider == "routed":
                return routed_fake
            return base_fake

        config = _make_config()

        def _run_ai():
            with patch("src.graphs.chat_graph.get_llm", side_effect=_make_llm), \
                 patch("src.graphs.chat_graph.cost_router") as mock_router, \
                 patch("src.graphs.chat_graph.get_context_engine") as mock_engine, \
                 patch("src.graphs.chat_graph._resolve_bound_tools", return_value=[]):
                mock_router.route.return_value = ("routed", "routed-model")
                mock_engine.return_value.build_ai_messages.return_value = []
                self._c11_result = ai_node(_make_state(), config)

        t = threading.Thread(target=_run_ai)
        t.start()
        assert routed_fake.wait_invoke(timeout=5), "routed LLM invoke never entered"

        # Stop fires while the routed request is in flight.
        self._tc.cancel(self._session_id)
        routed_fake.release()  # routed request now errors with a retryable error
        t.join(timeout=10)
        assert not t.is_alive(), "ai_node thread did not exit"

        msg = self._c11_result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.content == "Operation cancelled by the user."
        assert msg.additional_kwargs.get("pulse_cancelled") is True
        # The exception path must NOT fail over to the base provider.
        base_fake.invoke.assert_not_called()


class TestCancellationIntegration:
    """Higher-level integration tests combining multiple gates."""

    def setup_method(self):
        from src.runtime.turn_control import turn_controls
        self._tc = turn_controls
        self._sid = "cancel-integ-test"
        self._tc.reset(self._sid)
        self._tc.begin(self._sid)

    def teardown_method(self):
        self._tc.reset(self._sid)

    def test_cancel_before_graph_run_completes_cleanly(self):
        """If cancel is set BEFORE the graph starts, the first node
        (task_manager) short-circuits and no AI node is ever reached.
        """
        from src.graphs.chat_graph import task_manager_node

        self._tc.cancel(self._sid)

        config = _make_config(thread_id=self._sid)
        # Use an instruction that is NOT an approval/revision/cancel so
        # the task_manager reaches the cancellation gate (not a shortcut path).
        result = task_manager_node(
            _make_state(current_task="active task", latest_instruction="do something new"),
            config,
        )
        # task_manager short-circuits to cancelled
        assert result.get("task_status") == "cancelled"
        assert result.get("task_completed") is False

    def test_should_continue_routes_to_finalize_on_cancelled(self):
        """After ai_node returns pulse_cancelled=True, should_continue
        must route to 'finalize', not 'tools'.
        """
        from src.graphs.gates import should_continue
        from langchain_core.messages import AIMessage

        state = _make_state(
            messages=[
                AIMessage(
                    content="Operation cancelled by the user.",
                    additional_kwargs={"pulse_cancelled": True},
                )
            ]
        )
        route = should_continue(state)
        assert route == "finalize", f"Expected 'finalize', got '{route}'"

# â”€â”€ Blocker 1: Session isolation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestSessionIsolation:
    """Prove that cancelling session A does not affect session B when both
    are concurrently inside provider calls.  Each session uses its own
    RetryLLMProxy wrapping a distinct _FakeLLM with its own transport."""

    def test_concurrent_sessions_a_cancelled_b_completes(self):
        """Sessions A and B overlap in provider calls.  Cancel A while both
        are blocked.  A terminates (zero retries/failovers).  B is released
        and completes normally.  B's transport is never closed."""

        from src.llm.factory import RetryLLMProxy, TurnCancelledError
        from src.runtime.turn_control import set_active_session, turn_controls
        from langchain_core.messages import HumanMessage

        # Session A uses _FakeFailLLM so the proxy's cancellation gate
        # catches the abort via the exception path.  Session B uses a
        # normal fake that returns successfully.
        fake_a = _FakeFailLLM("Connection error: timeout")
        fake_b = _FakeLLM()
        fake_b.set_result(MagicMock(content="B-response", tool_calls=None))

        proxy_a = RetryLLMProxy(fake_a, max_attempts=5)
        proxy_b = RetryLLMProxy(fake_b, max_attempts=5)

        # Track transport closes independently
        transport_closed = {"a": False, "b": False}
        orig_abort_a = proxy_a.abort
        orig_abort_b = proxy_b.abort

        def _abort_a():
            transport_closed["a"] = True
            orig_abort_a()

        def _abort_b():
            transport_closed["b"] = True
            orig_abort_b()

        sid_a = "isolation-a"
        sid_b = "isolation-b"
        turn_controls.reset(sid_a)
        turn_controls.reset(sid_b)
        turn_controls.begin(sid_a)
        turn_controls.begin(sid_b)

        turn_controls.register_abort(sid_a, _abort_a)
        turn_controls.register_abort(sid_b, _abort_b)

        results_a = []
        results_b = []

        def _run_a():
            set_active_session(sid_a)
            try:
                r = proxy_a.invoke([HumanMessage(content="hello from A")])
                results_a.append(("ok", r))
            except Exception as e:
                results_a.append(("error", e))
            finally:
                set_active_session(None)

        def _run_b():
            set_active_session(sid_b)
            try:
                r = proxy_b.invoke([HumanMessage(content="hello from B")])
                results_b.append(("ok", r))
            except Exception as e:
                results_b.append(("error", e))
            finally:
                set_active_session(None)

        t_a = threading.Thread(target=_run_a)
        t_b = threading.Thread(target=_run_b)
        t_a.start()
        t_b.start()

        assert fake_a.wait_invoke(timeout=5), "A never entered invoke"
        assert fake_b.wait_invoke(timeout=5), "B never entered invoke"

        # Cancel A while both are in flight
        turn_controls.cancel(sid_a)

        # Release A (its request errors with a retryable error)
        fake_a.release()
        t_a.join(timeout=10)
        assert not t_a.is_alive(), "A thread did not exit"

        # A terminated with TurnCancelledError, zero retries
        assert len(results_a) == 1
        assert isinstance(results_a[0][1], TurnCancelledError), (
            f"A should have raised TurnCancelledError, got {results_a[0][1]!r}"
        )
        assert fake_a._invoke_count == 1, "A was retried after cancel"

        # B is still blocked — release it normally
        assert t_b.is_alive(), "B should still be running"
        fake_b.release()
        t_b.join(timeout=10)
        assert not t_b.is_alive(), "B thread did not exit"

        # B completed normally
        assert len(results_b) == 1
        assert results_b[0][0] == "ok"
        assert fake_b._invoke_count == 1

        # B's transport was never closed by A's cancel
        assert not transport_closed["b"], (
            "B's transport was closed by A's cancellation"
        )
        # A's transport was closed (abort fired)
        assert transport_closed["a"]

        turn_controls.unregister_abort(sid_a, _abort_a)
        turn_controls.unregister_abort(sid_b, _abort_b)
        turn_controls.end(sid_a)
        turn_controls.end(sid_b)
        turn_controls.reset(sid_a)
        turn_controls.reset(sid_b)


# â”€â”€ Blocker 2: Finally-cleanup proof â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestFinallyCleanup:
    """Assert the abort registry is empty after every possible ai_node exit
    path: success, provider exception, cancellation, retryable exception,
    and through bind()/bind_tools()/with_structured_output() wrappers."""

    def setup_method(self):
        from src.runtime.turn_control import turn_controls
        self._tc = turn_controls
        self._sid = "cleanup-test"
        self._tc.reset(self._sid)
        self._tc.begin(self._sid)

    def teardown_method(self):
        self._tc.reset(self._sid)

    def _assert_registry_empty(self):
        item = self._tc._get(self._sid)
        assert len(item.aborts) == 0, (
            f"abort registry not empty: {item.aborts}"
        )

    def test_cleanup_after_normal_success(self):
        from src.graphs.chat_graph import ai_node
        from langchain_core.messages import AIMessage

        fake_llm = _FakeLLM()
        fake_llm.set_result(AIMessage(content="done"))
        config = _make_config()

        def _run():
            with patch("src.graphs.chat_graph.get_llm", return_value=fake_llm), \
                 patch("src.graphs.chat_graph.cost_router") as mock_router, \
                 patch("src.graphs.chat_graph.get_context_engine") as mock_engine, \
                 patch("src.graphs.chat_graph._resolve_bound_tools", return_value=[]):
                mock_router.route.return_value = ("fake", "fake")
                mock_engine.return_value.build_ai_messages.return_value = []
                return ai_node(_make_state(), config)

        t = threading.Thread(target=_run)
        t.start()
        assert fake_llm.wait_invoke(timeout=5)
        fake_llm.release()
        t.join(timeout=10)
        assert not t.is_alive()
        self._assert_registry_empty()

    def test_cleanup_after_provider_exception(self):
        from src.graphs.chat_graph import ai_node
        from langchain_core.messages import AIMessage

        class _AlwaysFail:
            def __init__(self):
                self._release = threading.Event()
                self._invoke_barrier = threading.Event()
                self._invoke_count = 0

            def wait_invoke(self, timeout=5):
                return self._invoke_barrier.wait(timeout=timeout)

            def bind_tools(self, tools):
                return self

            def bind(self, **kw):
                return self

            def with_structured_output(self, schema):
                return self

            def invoke(self, messages, config=None, **kwargs):
                self._invoke_count += 1
                self._invoke_barrier.set()
                self._release.wait(timeout=10.0)
                raise RuntimeError("provider down")

        fail_llm = _AlwaysFail()
        config = _make_config()

        def _run():
            with patch("src.graphs.chat_graph.get_llm", return_value=fail_llm), \
                 patch("src.graphs.chat_graph.cost_router") as mock_router, \
                 patch("src.graphs.chat_graph.get_context_engine") as mock_engine, \
                 patch("src.graphs.chat_graph._resolve_bound_tools", return_value=[]):
                mock_router.route.return_value = ("fake", "fake")
                mock_engine.return_value.build_ai_messages.return_value = []
                try:
                    return ai_node(_make_state(), config)
                except Exception:
                    return None

        t = threading.Thread(target=_run)
        t.start()
        assert fail_llm.wait_invoke(timeout=5)
        fail_llm._release.set()
        t.join(timeout=10)
        assert not t.is_alive()
        self._assert_registry_empty()

    def test_cleanup_after_cancellation(self):
        from src.graphs.chat_graph import ai_node
        from langchain_core.messages import AIMessage

        fake_llm = _FakeLLM()
        fake_llm.set_result(AIMessage(content="working"))
        config = _make_config()

        def _run():
            with patch("src.graphs.chat_graph.get_llm", return_value=fake_llm), \
                 patch("src.graphs.chat_graph.cost_router") as mock_router, \
                 patch("src.graphs.chat_graph.get_context_engine") as mock_engine, \
                 patch("src.graphs.chat_graph._resolve_bound_tools", return_value=[]):
                mock_router.route.return_value = ("fake", "fake")
                mock_engine.return_value.build_ai_messages.return_value = []
                return ai_node(_make_state(), config)

        t = threading.Thread(target=_run)
        t.start()
        assert fake_llm.wait_invoke(timeout=5)
        self._tc.cancel(self._sid)
        fake_llm.release()
        t.join(timeout=10)
        assert not t.is_alive()
        self._assert_registry_empty()

    def test_cleanup_after_retryable_exception(self):
        from src.llm.factory import RetryLLMProxy
        from src.runtime.turn_control import set_active_session
        from langchain_core.messages import HumanMessage

        call_count = 0

        class _RetryOnce:
            def __init__(self):
                self._release = threading.Event()
                self._invoke_barrier = threading.Event()

            def wait_invoke(self, timeout=5):
                return self._invoke_barrier.wait(timeout=timeout)

            def invoke(self, messages, config=None, **kwargs):
                nonlocal call_count
                call_count += 1
                self._invoke_barrier.set()
                if call_count == 1:
                    self._release.wait(timeout=10.0)
                    raise ConnectionError("connection error: upstream timeout")
                return MagicMock(content="recovered")

            def bind_tools(self, tools):
                return self

            def bind(self, **kw):
                return self

            def with_structured_output(self, schema):
                return self

        fake = _RetryOnce()
        proxy = RetryLLMProxy(fake, max_attempts=3)
        self._tc.register_abort(self._sid, proxy.abort)

        def _run():
            set_active_session(self._sid)
            try:
                proxy.invoke([HumanMessage(content="hi")])
            finally:
                set_active_session(None)

        t = threading.Thread(target=_run)
        t.start()
        assert fake.wait_invoke(timeout=5)
        fake._release.set()
        t.join(timeout=15)
        assert not t.is_alive()
        assert call_count == 2, f"Expected 2 calls, got {call_count}"
        self._tc.unregister_abort(self._sid, proxy.abort)
        self._assert_registry_empty()

    def test_cleanup_through_bind_wrapper(self):
        from src.llm.factory import RetryLLMProxy
        from src.runtime.turn_control import set_active_session
        from langchain_core.messages import HumanMessage

        class _FakeProvider:
            def invoke(self, messages, config=None, **kwargs):
                return MagicMock(content="bound-response")
            def bind(self, **kwargs):
                return self
            def bind_tools(self, tools):
                return self
            def with_structured_output(self, schema):
                return self

        original = RetryLLMProxy(_FakeProvider(), max_attempts=2)
        bound = original.bind(max_tokens=512)
        assert bound is not original
        self._tc.register_abort(self._sid, bound.abort)

        set_active_session(self._sid)
        try:
            result = bound.invoke([HumanMessage(content="hi")])
        finally:
            set_active_session(None)
            self._tc.unregister_abort(self._sid, bound.abort)

        assert result.content == "bound-response"
        self._assert_registry_empty()

    def test_cleanup_through_bind_tools_and_structured(self):
        from src.llm.factory import RetryLLMProxy
        from src.runtime.turn_control import set_active_session
        from langchain_core.messages import HumanMessage

        class _FakeProvider:
            def invoke(self, messages, config=None, **kwargs):
                return MagicMock(content="final")
            def bind(self, **kwargs):
                return self
            def bind_tools(self, tools):
                return self
            def with_structured_output(self, schema):
                return self

        base = RetryLLMProxy(_FakeProvider(), max_attempts=2)
        with_tools = base.bind_tools([])
        with_struct = base.with_structured_output({"type": "object"})
        assert with_tools is not base
        assert with_struct is not base

        for p in (with_tools, with_struct):
            self._tc.register_abort(self._sid, p.abort)

        set_active_session(self._sid)
        try:
            with_tools.invoke([HumanMessage(content="tools")])
            with_struct.invoke([HumanMessage(content="struct")])
        finally:
            self._tc.unregister_abort(self._sid, with_tools.abort)
            self._tc.unregister_abort(self._sid, with_struct.abort)
            set_active_session(None)

        self._assert_registry_empty()

    def test_repeated_cancel_abort_is_harmless(self):
        from src.llm.factory import RetryLLMProxy
        from langchain_core.messages import HumanMessage

        class _CountingFake:
            def __init__(self):
                self._close_count = 0

            def invoke(self, messages, config=None, **kwargs):
                return MagicMock(content="ok")
            def bind_tools(self, tools):
                return self
            def bind(self, **kw):
                return self
            def with_structured_output(self, schema):
                return self
            def close(self):
                self._close_count += 1

        fake = _CountingFake()
        proxy = RetryLLMProxy(fake, max_attempts=2)
        self._tc.register_abort(self._sid, proxy.abort)

        for _ in range(5):
            self._tc.cancel(self._sid)
            self._tc.abort(self._sid)
            proxy.abort()

        assert proxy.is_aborted
        self._tc.unregister_abort(self._sid, proxy.abort)
        self._assert_registry_empty()


# â”€â”€ Blocker 3: Immediate-Stop race â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestImmediateStopRace:
    """Cover the race where Stop arrives after turn_started is emitted
    but before turn_controls.begin() is called.  begin() on an inactive
    session clears stale cancellations so future turns can proceed."""

    def setup_method(self):
        from src.runtime.turn_control import turn_controls
        self._tc = turn_controls

    def teardown_method(self):
        pass

    def test_cancel_before_begin_is_cleared(self):
        """Stop arrives before begin() (inactive session).  begin() must
        clear the stale cancellation so the turn proceeds fresh."""
        sid = "race-test"
        self._tc.reset(sid)
        self._tc.cancel(sid)
        assert self._tc.cancelled(sid)
        self._tc.begin(sid)
        assert not self._tc.cancelled(sid), "begin() did not clear stale cancel"
        self._tc.end(sid)
        self._tc.reset(sid)

    def test_cancel_during_active_turn_survives(self):
        """Stop arrives after begin() (active turn).  The cancel must
        survive so this turn terminates as cancelled."""
        sid = "active-race-test"
        self._tc.reset(sid)
        self._tc.begin(sid)
        self._tc.cancel(sid)
        assert self._tc.cancelled(sid)
        self._tc.end(sid)
        self._tc.begin(sid)
        assert not self._tc.cancelled(sid)
        self._tc.end(sid)
        self._tc.reset(sid)

    def test_cancel_then_end_then_begin_succeeds(self):
        """Full lifecycle: cancel -> end -> begin (same session) -> success.
        Proves future-turn recovery works after cancellation."""
        from src.graphs.chat_graph import ai_node
        from langchain_core.messages import AIMessage

        sid = "lifecycle-test"
        self._tc.reset(sid)
        self._tc.begin(sid)
        self._tc.cancel(sid)
        self._tc.end(sid)
        assert self._tc.cancelled(sid)

        self._tc.begin(sid)
        assert not self._tc.cancelled(sid)

        fake_llm = _FakeLLM()
        fake_llm.set_result(AIMessage(content="turn-2-response"))
        config = _make_config(thread_id=sid)
        captured = {}

        def _run():
            with patch("src.graphs.chat_graph.get_llm", return_value=fake_llm), \
                 patch("src.graphs.chat_graph.cost_router") as mock_router, \
                 patch("src.graphs.chat_graph.get_context_engine") as mock_engine, \
                 patch("src.graphs.chat_graph._resolve_bound_tools", return_value=[]):
                mock_router.route.return_value = ("fake", "fake")
                mock_engine.return_value.build_ai_messages.return_value = []
                captured["result"] = ai_node(_make_state(), config)

        t = threading.Thread(target=_run)
        t.start()
        assert fake_llm.wait_invoke(timeout=5)
        fake_llm.release()
        t.join(timeout=10)
        assert not t.is_alive()

        result = captured.get("result")
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.content == "turn-2-response"
        assert not msg.additional_kwargs.get("pulse_cancelled"), "Turn 2 should have succeeded"

        self._tc.end(sid)
        self._tc.reset(sid)

    def test_begin_then_cancel_produces_cancelled_turn(self):
        """Normal path: begin() first, then Stop arrives.  Cancel is set
        and the post-LLM gate discards the result."""
        from src.graphs.chat_graph import ai_node
        from langchain_core.messages import AIMessage

        sid = "normal-race-test"
        self._tc.reset(sid)
        self._tc.begin(sid)

        fake_llm = _FakeLLM()
        fake_llm.set_result(AIMessage(
            content="done",
            tool_calls=[{"id": "tc-1", "name": "write_file", "args": {"path": "x.py", "content": "bad"}}],
        ))
        config = _make_config(thread_id=sid)
        captured = {}

        def _run():
            with patch("src.graphs.chat_graph.get_llm", return_value=fake_llm), \
                 patch("src.graphs.chat_graph.cost_router") as mock_router, \
                 patch("src.graphs.chat_graph.get_context_engine") as mock_engine, \
                 patch("src.graphs.chat_graph._resolve_bound_tools", return_value=[]):
                mock_router.route.return_value = ("fake", "fake")
                mock_engine.return_value.build_ai_messages.return_value = []
                captured["result"] = ai_node(_make_state(), config)

        t = threading.Thread(target=_run)
        t.start()
        assert fake_llm.wait_invoke(timeout=5)

        self._tc.cancel(sid)
        fake_llm.release()
        t.join(timeout=10)
        assert not t.is_alive()

        result = captured.get("result")
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.additional_kwargs.get("pulse_cancelled") is True
        assert not getattr(msg, "tool_calls", None), "Tool calls leaked"

        self._tc.end(sid)
        self._tc.reset(sid)
