"""Round-12 reviewer self-verification — pinned verdicts (ARCHITECTURE_REVIEW.md §18).

A reviewer re-asserted three claims against a stale (pre-patch) tree:

  (a) nested sub-agent ``graph.invoke`` on the same graph + same SqliteSaver
      connection "deadlocks or corrupts state"  -> refuted live; pinned here.
  (b) a shared checkpointer connection across threads is unsafe -> the real
      access path (``SqliteSaver``) serializes internally with a
      ``threading.Lock``; concurrent session puts lose nothing. (Raw
      concurrent ``conn.execute`` on the connection DOES break -- that is
      precisely why all access must go through the saver.)
  (c) the plan-approval matcher is "too narrow" and should accept fuzzy
      natural approvals ("yep", "ok", "sure")  -> REJECTED as unsafe: an
      approval gate must fail CLOSED.

Pure CI tests: no LLM, no network.
"""

import sqlite3
import threading
import uuid
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from src.graphs.chat_graph import is_plan_approval


class _DepthState(TypedDict, total=False):
    depth: int


def test_nested_graph_invoke_same_checkpointer_does_not_deadlock(tmp_path):
    """The reviewer's exact 'deadlock' scenario: synchronous nested invoke,
    same compiled graph, same SqliteSaver, same connection, same thread."""
    conn = sqlite3.connect(str(tmp_path / "cp.db"), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    seen: list[str] = []

    def node(state: _DepthState, config) -> _DepthState:
        d = state["depth"]
        seen.append(config["configurable"]["thread_id"])
        if d < 2:
            app.invoke(
                {"depth": d + 1},
                {"configurable": {"thread_id": f"main/sub{d}"}},
            )
        return {"depth": d + 1}

    g = StateGraph(_DepthState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    app = g.compile(checkpointer=saver)

    out = app.invoke({"depth": 0}, {"configurable": {"thread_id": "main"}})

    assert out["depth"] == 1  # outer invoke returns its own node's update
    # no hang, no SQLITE_BUSY, every nesting level actually executed:
    assert seen == ["main", "main/sub0", "main/sub1"]


def test_checkpointer_concurrent_sessions_zero_loss(tmp_path):
    """Concurrent dashboard-style sessions checkpointing through the shared
    saver simultaneously: zero errors, zero lost checkpoints."""
    conn = sqlite3.connect(str(tmp_path / "cp.db"), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    errors: list[str] = []
    n_sessions, n_puts = 4, 50

    def worker(w: int) -> None:
        try:
            for i in range(n_puts):
                cid = str(uuid.uuid4())
                cfg = {
                    "configurable": {
                        "thread_id": f"s{w}",
                        "checkpoint_ns": "",
                        "checkpoint_id": cid,
                    }
                }
                saver.put(
                    cfg,
                    {
                        "v": 1,
                        "id": cid,
                        "ts": "2026-08-05T00:00:00+00:00",
                        "channel_values": {},
                        "channel_versions": {},
                        "versions_seen": {},
                        "pending_sends": [],
                    },
                    {"source": "loop", "step": i, "writes": {}},
                    {},
                )
        except Exception as exc:  # pragma: no cover - asserted empty below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(n_sessions)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    for w in range(n_sessions):
        count = sum(1 for _ in saver.list({"configurable": {"thread_id": f"s{w}"}}))
        assert count == n_puts


def test_plan_approval_fails_closed_by_design():
    """False negative costs a re-typed 'approve'; false positive executes a
    destructive plan against a non-approval. Narrow is the correct posture."""
    assert is_plan_approval("approve") is True
    assert is_plan_approval("yes") is True
    for not_an_approval in (
        "yep",
        "yeah",
        "ok",
        "sure",
        "k",
        "execute it",
        "approved, with changes",
        "yes, but don't delete anything",
    ):
        assert is_plan_approval(not_an_approval) is False
