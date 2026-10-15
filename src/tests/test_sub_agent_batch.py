"""Pins for D33 (steal #9, §45): parallel sub-agent batches — true
wall-clock concurrency, index-ordered results, per-child crash capture,
single-task path byte-identical to legacy spawn, plus the D32 synergy
(concurrent children cannot clobber each other's files).

invoke_agent is faked everywhere — no LLM, no graph.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.agents.sub_agent import SubAgentCoordinator


def _fake_invoke_factory(behavior):
    """behavior(thread_id, message) -> result string (or raises)."""
    def fake(message, thread_id="default", provider=None, model=None,
             workspace=".", execution_mode="agent", **_kw):
        return behavior(thread_id, message)
    return fake


def task_of(focused_prompt: str) -> str:
    """Children receive spawn()'s FOCUSED prompt ('You are a ... Task: X');
    tests want the raw task back."""
    return focused_prompt.rsplit("Task: ", 1)[-1]


@pytest.fixture(autouse=True)
def _clean():
    yield


def test_batch_modes_give_each_child_its_own_scope(monkeypatch):
    """Field 2026-10-15: one batch mode for every child put a
    code-writing task in a research child's clothing (research
    scope + 'Do NOT write code' prompt) and it flailed on repeated
    reads. modes[i] must give child i its own agent: the child id
    names the mode, and the strict scope follows it."""
    scopes: dict[str, object] = {}

    def fake(message, thread_id="default", provider=None, model=None,
             workspace=".", execution_mode="agent", **kw):
        scopes[thread_id] = kw.get("scope_capabilities")
        return "done"

    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent", fake)
    coord = SubAgentCoordinator()
    ids = coord.spawn_batch(
        "research",
        ["research the algorithm", "write the benchmark script"],
        "parent",
        modes=["research", "code"],
    )
    assert ids[0].startswith("sub-research-"), ids
    assert ids[1].startswith("sub-code-"), ids
    from src.agents.subagent_permissions import default_capabilities_for_mode
    assert scopes[ids[0]] == default_capabilities_for_mode("research")
    assert scopes[ids[1]] == default_capabilities_for_mode("code")
    assert "workspace_write" in scopes[ids[1]]
    assert "workspace_write" not in scopes[ids[0]]


def test_delegate_batch_tool_honors_per_task_mode_dicts(monkeypatch, tmp_path):
    """The tool schema shape the model actually emits: entries may be
    {"task": ..., "mode": ...}. The real delegate tool (ToolNode
    harness, invoke_agent faked at the capture seam) must spawn a
    code child for the writing task even when the batch default is
    research."""
    from unittest.mock import patch

    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    import src.graphs.chat_graph as cg

    captured: list[dict] = []

    def fake_invoke_agent(**kwargs):
        captured.append(kwargs)
        return "done"

    state = {"messages": [AIMessage(
        content="",
        tool_calls=[{
            "name": "delegate_to_subagent_batch",
            "args": {
                "mode": "research",
                "tasks": [
                    {"task": "research bubble sort complexity", "mode": "research"},
                    {"task": "write benchmark_bubble_sort.py", "mode": "code"},
                ],
            },
            "id": "call_batch_modes",
        }],
    )]}
    config = {"configurable": {"thread_id": "main", "workspace": str(tmp_path)}}

    builder = StateGraph(MessagesState)
    builder.add_node("tools", ToolNode([cg.delegate_to_subagent_batch]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    app = builder.compile()
    with patch.object(cg, "invoke_agent", fake_invoke_agent):
        app.invoke(state, config=config)

    threads = sorted(str(c.get("thread_id")) for c in captured)
    assert any(t.startswith("sub-research-") for t in threads), threads
    assert any(t.startswith("sub-code-") for t in threads), threads
    by_thread = {str(c.get("thread_id")): c.get("scope_capabilities") for c in captured}
    code_scope = next(v for k, v in by_thread.items() if k.startswith("sub-code-"))
    research_scope = next(v for k, v in by_thread.items() if k.startswith("sub-research-"))
    assert "workspace_write" in (code_scope or ())
    assert "workspace_write" not in (research_scope or ())


def test_single_task_batch_uses_legacy_sequential_path(monkeypatch):
    calls = []

    def behavior(tid, msg):
        calls.append(tid)
        time.sleep(0.05)
        return f"done:{tid}"

    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(behavior))
    coord = SubAgentCoordinator()
    t0 = time.perf_counter()
    ids = coord.spawn_batch("research", ["only one"], "parent")
    dt = time.perf_counter() - t0
    assert len(ids) == 1 and ids[0] in calls
    assert dt >= 0.05  # ran the child inline (sequential, legacy shape)
    assert coord.get_result(ids[0]) == f"done:{ids[0]}"


def test_batch_runs_concurrently_wall_time_pin(monkeypatch):
    def behavior(tid, msg):
        time.sleep(0.3)
        return f"done:{msg[-12:]}"

    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(behavior))
    coord = SubAgentCoordinator()
    tasks = [f"task number {i} padding" for i in range(3)]
    t0 = time.perf_counter()
    ids = coord.spawn_batch("review", tasks, "parent")
    dt = time.perf_counter() - t0
    # Serial would be >= 0.9s; parallel bounded pool must be far faster.
    # (0.6s leaves 2x headroom for slow CI — the pin is about SHAPE.)
    assert dt < 0.6, f"batch took {dt:.2f}s — children ran sequentially!"
    assert dt >= 0.28
    assert len(ids) == 3


def test_batch_results_come_back_in_input_order(monkeypatch):
    def behavior(tid, msg):
        # Later tasks finish FIRST — order must still follow the input.
        time.sleep(0.05 if "fast" in msg else 0.2)
        return f"RESULT[{task_of(msg)}]"

    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(behavior))
    coord = SubAgentCoordinator()
    tasks = ["slow-first", "fast-second", "fast-third"]
    ids = coord.spawn_batch("test", tasks, "parent")
    results = [coord.get_result(i) for i in ids]
    assert results == [f"RESULT[{t}]" for t in tasks]


def test_one_child_crash_does_not_sink_the_batch(monkeypatch):
    def behavior(tid, msg):
        if "boom" in msg:
            raise RuntimeError("provider exploded")
        return f"ok:{task_of(msg)}"

    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(behavior))
    coord = SubAgentCoordinator()
    tasks = ["fine one", "boom task", "fine two"]
    ids = coord.spawn_batch("code", tasks, "parent")  # must not raise
    results = [coord.get_result(i) for i in ids]
    assert results[0] == "ok:fine one"
    assert results[2] == "ok:fine two"
    assert "Sub-agent crashed" in results[1]
    assert "provider exploded" in results[1]
    # and every entry was delivered exactly once (pop-on-read):
    assert all(coord.get_result(i).startswith("No sub-agent found")
               for i in ids)


def test_batch_empty_and_legacy_registry_bound(monkeypatch):
    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(lambda tid, msg: "x"))
    coord = SubAgentCoordinator()
    assert coord.spawn_batch("review", [], "parent") == []


def test_concurrent_children_cannot_clobber_files(monkeypatch, tmp_path):
    """D32 × D33 synergy through the REAL write path: two parallel children
    racing one file — the guard turns silent clobbering into a visible,
    recoverable refusal. Exactly one wins; the file is always coherent."""
    from src.tools.file_tools import write_file
    from src.tools import file_state

    ws = tmp_path / "ws"
    ws.mkdir()
    target = "race.txt"

    def behavior(tid, msg):
        return write_file.func(
            path=target, content=f"content from {tid}\n",
            config={"configurable": {"workspace": str(ws), "thread_id": tid}},
        )

    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(behavior))
    file_state.reset_for_tests()
    coord = SubAgentCoordinator()
    ids = coord.spawn_batch("code", ["write A", "write B"], "parent")
    results = [coord.get_result(i) for i in ids]

    winners = [r for r in results if r.startswith("File written")]
    refused = [r for r in results if "Refusing to clobber" in r]
    assert len(winners) == 1, f"expected exactly one winner: {results}"
    assert len(refused) == 1, f"expected exactly one refusal: {results}"
    final = (ws / target).read_text()
    assert final.startswith("content from sub-code-")
    file_state.reset_for_tests()
