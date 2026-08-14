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
             workspace=".", execution_mode="agent"):
        return behavior(thread_id, message)
    return fake


def task_of(focused_prompt: str) -> str:
    """Children receive spawn()'s FOCUSED prompt ('You are a ... Task: X');
    tests want the raw task back."""
    return focused_prompt.rsplit("Task: ", 1)[-1]


@pytest.fixture(autouse=True)
def _clean():
    yield


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
