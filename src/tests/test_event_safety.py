"""
Every event running safely — P6 contract suite
===============================================
Run: python -m pytest src/tests/test_event_safety.py -q

The event pipeline (EventBus + ApprovalQueue + engine receipts + tool-event
pairing) is the wire between the agent and every consumer (dashboard SSE,
bridge, per-session subscriptions). These tests pin the SAFETY invariants —
behavior contracts, not snapshots:

1. SESSION ISOLATION — a session subscription can never observe another
   session's events, live or on history replay; only the explicit
   ``thread_id=None`` (admin/compat) subscription sees all sessions.
   Events that cannot be attributed to a session are never pushed to one.
2. BOUNDED MEMORY — history and subscriber queues are capped; a dead
   (full, non-draining) subscriber is evicted and the bus keeps delivering
   to healthy ones; event ids are unique.
3. TOOL-EVENT PAIRING — after any compaction/trim, no ToolMessage is
   orphaned, no AIMessage keeps tool_calls without results, and no result
   stream starts on a ToolMessage (the P4 guard, pinned at both enforcers
   and at the engine's trim path).
4. LATCHED, SCOPED RECEIPTS — engine→bus receipts (``runtime.cache_break``,
   ``runtime.degraded``) fire at most once per session and carry a
   thread-scoped, key-bounded payload (no message bodies in events).
5. APPROVAL SAFETY — cross-session resolution is rejected; timeout denies
   by default; pending lists are session-scoped.

Provider-free, network-free, zero LLM spend.
"""
import queue
import time
import uuid

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)

from src.context.bounded_scan import ContextBudget
from src.context.context_engine import ContextEngine
from src.context.smart_compressor import SmartCompressor
from src.context.token_budget import count_tokens, trim_messages_to_budget
from src.dashboard.event_bus import ApprovalQueue, EventBus, event_bus


def _drain(q: queue.Queue, settle: float = 0.05) -> list:
    """Collect every event currently queued (settle for in-flight puts)."""
    time.sleep(settle)
    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except queue.Empty:
            return events


def _unique_session(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _tool_round(call_ids: list[str]) -> list:
    """One AIMessage(tool_calls) + its ToolMessages — a clean atomic pair."""
    ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "read_file", "args": {"path": f"p/{cid}"}, "id": cid}
            for cid in call_ids
        ],
    )
    return [ai] + [
        ToolMessage(content=f"result for {cid}", tool_call_id=cid) for cid in call_ids
    ]


# --------------------------------------------------------------------------- #
# 1. Session isolation                                                        #
# --------------------------------------------------------------------------- #

class TestSessionIsolation:
    def test_live_delivery_never_crosses_sessions(self):
        bus = EventBus()
        qa = bus.subscribe("sess-a")
        qb = bus.subscribe("sess-b")
        bus.emit("tool.executed", {"thread_id": "sess-a", "tool": "read_file"})
        bus.emit("tool.executed", {"thread_id": "sess-b", "tool": "write_file"})
        bus.emit("tool.executed", {"thread_id": "sess-a", "tool": "edit_file"})

        a_events, b_events = _drain(qa), _drain(qb)
        assert len(a_events) == 2
        assert all(e["payload"]["thread_id"] == "sess-a" for e in a_events)
        assert len(b_events) == 1
        assert all(e["payload"]["thread_id"] == "sess-b" for e in b_events)

    def test_late_session_replay_contains_only_own_history(self):
        bus = EventBus()
        bus.emit("x", {"thread_id": "sess-a"})
        bus.emit("y", {"thread_id": "sess-b"})
        bus.emit("z", {"thread_id": "sess-a"})

        qb = bus.subscribe("sess-b")
        events = _drain(qb)
        assert [e["type"] for e in events] == ["y"]

    def test_admin_subscription_sees_all_sessions(self):
        """The documented compat surface: only thread_id=None is global."""
        bus = EventBus()
        q_admin = bus.subscribe()
        bus.emit("x", {"thread_id": "sess-a"})
        bus.emit("y", {"thread_id": "sess-b"})
        events = _drain(q_admin)
        assert {e["type"] for e in events} == {"x", "y"}

    def test_unscoped_event_never_reaches_a_session_subscription(self):
        """An event with no session attribution is safe-default: invisible
        to every session subscription (admin still sees it)."""
        bus = EventBus()
        q_session = bus.subscribe("sess-a")
        q_admin = bus.subscribe()
        bus.emit("misc.unscoped", {"foo": 1})

        assert _drain(q_session) == []
        assert [e["type"] for e in _drain(q_admin)] == ["misc.unscoped"]

    def test_clear_is_session_scoped(self):
        bus = EventBus()
        bus.emit("a", {"thread_id": "sess-a"})
        bus.emit("b", {"thread_id": "sess-b"})
        bus.clear("sess-a")

        assert _drain(bus.subscribe("sess-a")) == []
        assert [e["type"] for e in _drain(bus.subscribe("sess-b"))] == ["b"]


# --------------------------------------------------------------------------- #
# 2. Bounded memory + identity                                                #
# --------------------------------------------------------------------------- #

class TestBoundedEvents:
    def test_history_and_replay_are_bounded(self):
        """Memory is capped at the history bound, and a late subscriber
        replays the NEWEST events that fit its queue — a reconnected
        session never loses the latest state to an overflow of its own."""
        bus = EventBus()
        total = bus._max_history + 200
        for i in range(total):
            bus.emit("flood", {"thread_id": "s", "i": i})

        assert len(bus._history) == bus._max_history  # internal cap
        events = _drain(bus.subscribe("s"))
        assert len(events) == 200  # replay window = queue capacity
        assert events[0]["payload"]["i"] == total - 200  # newest 200
        assert events[-1]["payload"]["i"] == total - 1

    def test_dead_subscriber_is_evicted_and_others_keep_receiving(self):
        bus = EventBus()
        q_dead = bus.subscribe("s")  # maxsize 200, never drained
        q_ok = bus.subscribe("s")
        for i in range(300):
            bus.emit("flood", {"thread_id": "s", "i": i})
            try:
                q_ok.get_nowait()
            except queue.Empty:
                pass

        _drain(q_dead, settle=0.0)  # buffer whatever it holds
        bus.emit("after", {"thread_id": "s", "i": 999})
        got = _drain(q_ok)
        assert any(e["type"] == "after" for e in got)
        # evicted: receives nothing new (the bus must not crash either)
        got_dead = _drain(q_dead)
        assert all(e["type"] != "after" for e in got_dead)

    def test_event_ids_are_unique(self):
        bus = EventBus()
        ids = {
            bus.emit("t", {"thread_id": "s", "i": i})["event_id"]
            for i in range(500)
        }
        assert len(ids) == 500


# --------------------------------------------------------------------------- #
# 3. Tool-event pairing (P4 guard, pinned at both enforcers + engine path)   #
# --------------------------------------------------------------------------- #

def _assert_stream_never_starts_on_tool_result(msgs: list) -> None:
    assert not msgs or not isinstance(msgs[0], ToolMessage), (
        "result stream starts on an unattributed ToolMessage"
    )


def _assert_loose_pairing(msgs: list) -> None:
    """trim_messages_to_budget contract: every ToolMessage is attributable
    to a preceding AI tool-call, and an AI keeps tool_calls only when at
    least one of its results survived."""
    seen_ai_call_ids: list[set] = []
    for m in msgs:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            ids = {
                tc.get("id") for tc in m.tool_calls if isinstance(tc, dict)
            }
            seen_ai_call_ids.append(ids)
            any_result = any(
                isinstance(n, ToolMessage) and n.tool_call_id in ids
                for n in msgs
            )
            assert any_result, (
                f"AIMessage kept tool_calls {ids} with no surviving result"
            )
        elif isinstance(m, ToolMessage):
            assert any(
                m.tool_call_id in ids for ids in seen_ai_call_ids
            ), f"orphan ToolMessage {m.tool_call_id} — no preceding tool_calls"


def _assert_strict_pairing(msgs: list) -> None:
    """SmartCompressor contract (bidirectional): every result maps to a kept
    call AND every kept call has its result."""
    kept_call_ids: set = set()
    result_ids: set = set()
    for m in msgs:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            kept_call_ids.update(
                tc.get("id") for tc in m.tool_calls if isinstance(tc, dict)
            )
        elif isinstance(m, ToolMessage):
            result_ids.add(m.tool_call_id)
    # order-aware forward check: a result must follow its answering call
    pending: set = set()
    for m in msgs:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            pending.update(
                tc.get("id") for tc in m.tool_calls if isinstance(tc, dict)
            )
        elif isinstance(m, ToolMessage):
            assert m.tool_call_id in pending, (
                f"ToolMessage {m.tool_call_id} without its answering call"
            )
            pending.discard(m.tool_call_id)
    assert kept_call_ids == result_ids, (
        f"kept calls {kept_call_ids} != surviving results {result_ids}"
    )


class TestToolEventPairing:
    def test_compress_is_strictly_pairing_even_on_pretrimmed_input(self):
        """Corrupt/pre-trimmed history (orphan result first, one call's
        result missing) must come out of compaction fully paired."""
        compressor = SmartCompressor(model="gpt-4o", allow_embedding_compute=False)
        history = [
            ToolMessage(content="orphan result", tool_call_id="ghost-1"),
            *_tool_round(["a1", "a2"]),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "x", "args": {}, "id": "b1"},
                    {"name": "y", "args": {}, "id": "b2"},
                ],
            ),
            ToolMessage(content="only b1 survived", tool_call_id="b1"),
            HumanMessage(content="next user turn"),
            AIMessage(content="final answer"),
        ]
        out = compressor.compress(
            history,
            budget=100_000,
            token_counter=lambda msgs, model: count_tokens(msgs, model),
            task="safety",
        )
        _assert_stream_never_starts_on_tool_result(out)
        _assert_strict_pairing(out)
        assert "ghost-1" not in {
            m.tool_call_id for m in out if isinstance(m, ToolMessage)
        }
        assert "b2" not in {
            tc.get("id")
            for m in out
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
            for tc in m.tool_calls
            if isinstance(tc, dict)
        }

    @pytest.mark.parametrize("budget", [100, 250, 500, 1_000, 2_500, 100_000])
    def test_trim_is_pairing_at_every_budget(self, budget):
        history = (
            [HumanMessage(content="first ask")]
            + _tool_round(["c1", "c2", "c3"])
            + [HumanMessage(content="second ask")]
            + _tool_round(["d1", "d2"])
            + [AIMessage(content="done")]
        )
        out = trim_messages_to_budget(history, budget, model="gpt-4o")
        _assert_stream_never_starts_on_tool_result(out)
        _assert_loose_pairing(out)

    def test_engine_trim_history_keeps_pairs(self):
        engine = ContextEngine(
            max_tokens=8_192, model="gpt-4o", probe_window=False,
            thread_id=_unique_session("evt-trim"),
        )
        history = (
            [HumanMessage(content="first ask")]
            + _tool_round(["c1", "c2"])
            + [HumanMessage(content="second ask")]
            + _tool_round(["d1", "d2", "d3"])
            + [AIMessage(content="done")]
        )
        out = engine._trim_history(history, budget=200)
        _assert_stream_never_starts_on_tool_result(out)
        _assert_loose_pairing(out)


# --------------------------------------------------------------------------- #
# 4. Latched, scoped receipts (engine -> bus)                                 #
# --------------------------------------------------------------------------- #

class TestEngineReceipts:
    def test_cache_break_receipt_is_thread_scoped_and_key_bounded(self):
        """The receipt names the breaker owner and carries only bounded
        metadata — never message bodies."""
        tid = _unique_session("evt-cb")
        engine = ContextEngine(
            max_tokens=8_192, model="gpt-4o", probe_window=False, thread_id=tid,
        )
        q = event_bus.subscribe(tid)
        engine._emit_cache_break_receipt({
            "turn": 3,
            "breaker": "persona",
            "break_msg_idx": 0,
            "cache_break_dropped_chars": 9_000,
            "stable_ratio": 0.41,
        })
        events = _drain(q)
        assert len(events) == 1
        payload = events[0]["payload"]
        assert events[0]["type"] == "runtime.cache_break"
        assert set(payload) == {
            "thread_id", "turn", "breaker", "break_msg_idx",
            "dropped_chars", "stable_ratio",
        }
        assert payload["thread_id"] == tid
        assert payload["breaker"] == "persona"

    def test_degraded_receipt_latched_once_per_session(self):
        """A bounded build emits EXACTLY ONE runtime.degraded receipt per
        session, scoped to the session, regardless of how many times the
        build path re-enters."""
        tid = _unique_session("evt-deg")
        engine = ContextEngine(
            max_tokens=8_192, model="gpt-4o", probe_window=False, thread_id=tid,
        )
        q = event_bus.subscribe(tid)
        pool = ContextBudget()
        pool._shared.truncated = True
        engine._active_pool = pool
        engine._active_thread_id = tid
        engine._active_workspace = "/tmp"
        engine._emit_build_receipt()
        engine._emit_build_receipt()
        engine._emit_build_receipt()

        degraded = [
            e for e in _drain(q) if e["type"] == "runtime.degraded"
        ]
        assert len(degraded) == 1
        assert degraded[0]["payload"]["thread_id"] == tid
        assert degraded[0]["payload"]["reason"] == "context scan bounded"


# --------------------------------------------------------------------------- #
# 5. Approval safety                                                           #
# --------------------------------------------------------------------------- #

class TestApprovalSafety:
    def test_cross_session_resolve_is_rejected(self):
        q = ApprovalQueue()
        q.request("tool-1", "write_file", {"path": "x"}, session_id="s-a")

        assert q.resolve("tool-1", approved=True, session_id="s-b") is False
        assert [p["id"] for p in q.get_pending("s-a")] == ["tool-1"]

        assert q.resolve("tool-1", approved=True, session_id="s-a") is True
        result = q.wait_for_decision("tool-1", timeout=1.0)
        assert result["decision"] is True

    def test_timeout_denies_by_default(self):
        """An unanswered request cannot stall a turn forever and cannot
        drift into an implicit approval: it resolves to DENY."""
        q = ApprovalQueue()
        q.request("tool-2", "run_terminal", {"cmd": "ls"}, session_id="s-a")
        result = q.wait_for_decision("tool-2", timeout=0.3)
        assert result is not None
        assert result["decision"] is False
        assert result.get("timeout") is True
        assert q.get_pending("s-a") == []

    def test_pending_lists_are_session_scoped(self):
        q = ApprovalQueue()
        q.request("tool-a", "write_file", {}, session_id="s-a")
        q.request("tool-b", "edit_file", {}, session_id="s-b")

        assert [p["id"] for p in q.get_pending("s-a")] == ["tool-a"]
        assert [p["id"] for p in q.get_pending("s-b")] == ["tool-b"]
        assert {p["id"] for p in q.get_pending(None)} == {"tool-a", "tool-b"}
