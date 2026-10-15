"""Stop on the parent cascades into running children (OpenCode parity).

OpenCode's task tool blocks on the child job and registers an
interrupt: stopping the parent interrupts the child session and
cancels the job. Here the bridge's Stop is turn_controls.cancel(
parent), which fires aborts registered on the parent's turn; the
delegate registers one that cancels the child's own turn (which in
turn wakes the child's blocking clarify/approval waits and stops
its stream). This drives the real delegate → lifecycle → child
thread chain with only invoke_agent faked: the fake child idles
until its turn is cancelled, exactly like a real child mid-run.
"""

from __future__ import annotations

import threading
import time

from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode

import src.graphs.chat_graph as cg
from src.runtime.turn_control import turn_controls


def _fake_child(**kwargs):
    thread_id = str(kwargs.get("thread_id") or "child")
    turn_controls.begin(thread_id)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if turn_controls.cancelled(thread_id):
                raise RuntimeError("child turn cancelled")
            time.sleep(0.05)
        return "child finished naturally"
    finally:
        turn_controls.end(thread_id)


def test_parent_stop_kills_foreground_child(monkeypatch):
    monkeypatch.setattr(cg, "invoke_agent", _fake_child)
    parent = "parent-cascade-test"
    turn_controls.begin(parent)
    outcome: dict = {}

    def run_delegate():
        from langgraph.graph import END, START, MessagesState, StateGraph

        graph_builder = StateGraph(MessagesState)
        graph_builder.add_node("tools", ToolNode([cg.delegate_to_subagent]))
        graph_builder.add_edge(START, "tools")
        graph_builder.add_edge("tools", END)
        app = graph_builder.compile()
        outcome["result"] = app.invoke(
            {"messages": [{
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "name": "delegate_to_subagent", "id": "delegate-cascade-1",
                    "args": {"mode": "research", "description": "Long research",
                             "task": "Research something slowly"},
                }],
            }]},
            config={"configurable": {"thread_id": parent, "workspace": "."}},
        )

    worker = threading.Thread(target=run_delegate, daemon=True)
    worker.start()
    # Wait until the child is actually running before pressing Stop.
    from src.runtime.subagent_store import get_store

    deadline = time.monotonic() + 15
    running = []
    while time.monotonic() < deadline:
        running = [r for r in get_store().list_by_parent(parent)
                   if getattr(r, "state", "") in ("running", "pending")]
        if running:
            break
        time.sleep(0.05)
    assert running, "child never started running under the parent"

    started = time.monotonic()
    assert turn_controls.cancel(parent) is True
    worker.join(timeout=20)
    elapsed = time.monotonic() - started
    assert not worker.is_alive(), "delegate never returned after parent Stop"
    assert elapsed < 20, f"cascade took {elapsed:.1f}s — child was not interrupted"
    msgs = outcome["result"]["messages"]
    assert "cancelled" in str(msgs[-1].content).lower() or "error" in str(msgs[-1].content).lower()
    turn_controls.end(parent)
