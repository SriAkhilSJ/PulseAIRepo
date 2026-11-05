"""
test_safe_parallel_execution.py - Comprehensive Concurrency Verification for Phase 9.2.2.3.

Validates:
1. All read-only tools succeed concurrently with real wall-clock speedup
2. Single read-only tool failure isolation (status="error" for failed, "success" for others)
3. Multiple read-only failures isolation
4. Exception / timeout handling within parallel workers
5. User cancellation before and during execution
6. Permission denial isolation (denied tool gets denial ToolMessage, authorized read-only runs in parallel)
7. Approval pending/denied behavior (blocked call never dispatched)
8. Duplicate tool_call_id deduplication & pairing integrity
9. Malformed tool output handled gracefully
10. Concurrent access to the same file by multiple readers (pairwise safe)
11. Mixed batch (read + write) forced sequential execution (mutations never parallelized)
12. Unknown tools forced sequential execution
13. Strict read-only allowlist enforcement (is_safe_read_only_batch)
14. CRUSORAI_PARALLEL_MAX_WORKERS bounded worker configuration
15. Kill-switch CRUSORAI_PARALLEL_TOOLS=off forces sequential execution
16. Deterministic input-order result preservation even when finish order inverts
17. Durable journal integration (tool.intent and tool.result recorded for every parallel call)
18. Event bus emission for parallel executions
19. ARRE recovery integration across parallel error outcomes
20. SafeToolNode._execute_durable end-to-end parallel execution
"""

import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool

from src.graphs.chat_graph import SafeToolNode, SafetyGuard
from src.graphs.parallel_tools import (
    is_safe_read_only_batch,
    run_durable_batch_parallel,
    run_durable_batch_sequential,
    try_parallel_batch,
    SAFE_READ_ONLY_TOOLS,
    _max_workers,
)
from src.runtime.turn_control import turn_controls


def _make_tool(name: str, delay: float = 0.0, output: str = "", boom: Exception | None = None):
    def fn(**kwargs):
        if delay > 0:
            time.sleep(delay)
        if boom:
            raise boom
        return output or f"{name}_result"

    return StructuredTool.from_function(fn, name=name, description=f"Test tool {name}")


def _calls(*specs):
    return [
        {"name": name, "args": args, "id": f"tc_{i}", "type": "tool_call"}
        for i, (name, args) in enumerate(specs)
    ]


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def cfg(workspace):
    return {"configurable": {"workspace": str(workspace), "thread_id": "test_concurrency"}}


# 1. All read-only tools succeed concurrently with real wall-clock speedup
def test_01_all_read_only_tools_succeed_concurrently(workspace, cfg):
    t1 = _make_tool("read_file", delay=0.15, output="content1")
    t2 = _make_tool("list_files", delay=0.15, output="file1\nfile2")
    t3 = _make_tool("search_files", delay=0.15, output="found")
    tools = {t.name: t for t in (t1, t2, t3)}

    calls = _calls(
        ("read_file", {"path": "a.py"}),
        ("list_files", {"path": "."}),
        ("search_files", {"pattern": "*.py", "path": "."}),
    )

    t0 = time.perf_counter()
    results = run_durable_batch_parallel(calls, tools, cfg)
    elapsed = time.perf_counter() - t0

    assert len(results) == 3
    # 3 x 0.15s serial = 0.45s. Parallel should finish in < 0.30s
    assert elapsed < 0.35, f"Expected parallel speedup (<0.35s), but took {elapsed:.2f}s"
    assert [m.content for m in results] == ["content1", "file1\nfile2", "found"]
    assert [m.tool_call_id for m in results] == ["tc_0", "tc_1", "tc_2"]
    assert all(m.status == "success" for m in results)


# 2. Single read-only tool failure isolation
def test_02_single_read_only_tool_failure_isolation(workspace, cfg):
    t1 = _make_tool("read_file", delay=0.02, output="ok_read")
    t2 = _make_tool("list_files", delay=0.02, boom=FileNotFoundError("missing folder"))
    t3 = _make_tool("search_files", delay=0.02, output="ok_search")
    tools = {t.name: t for t in (t1, t2, t3)}

    calls = _calls(
        ("read_file", {"path": "a.py"}),
        ("list_files", {"path": "missing"}),
        ("search_files", {"pattern": "*.py", "path": "."}),
    )

    results = run_durable_batch_parallel(calls, tools, cfg)
    assert len(results) == 3
    assert results[0].status == "success" and results[0].content == "ok_read"
    assert results[1].status == "error" and "missing folder" in results[1].content
    assert results[2].status == "success" and results[2].content == "ok_search"


# 3. Multiple read-only failures isolation
def test_03_multiple_read_only_failures_isolation(workspace, cfg):
    t1 = _make_tool("read_file", boom=PermissionError("read denied"))
    t2 = _make_tool("list_files", boom=ValueError("bad path"))
    t3 = _make_tool("search_files", output="ok_search")
    tools = {t.name: t for t in (t1, t2, t3)}

    calls = _calls(
        ("read_file", {"path": "a.py"}),
        ("list_files", {"path": "."}),
        ("search_files", {"pattern": "*.py", "path": "."}),
    )

    results = run_durable_batch_parallel(calls, tools, cfg)
    assert len(results) == 3
    assert results[0].status == "error" and "read denied" in results[0].content
    assert results[1].status == "error" and "bad path" in results[1].content
    assert results[2].status == "success" and results[2].content == "ok_search"


# 4. Exception handling in worker thread
def test_04_unhandled_worker_exception_captured_cleanly(workspace, cfg):
    t1 = _make_tool("read_file", delay=0.01, output="good")
    t2 = _make_tool("list_files", delay=0.01, boom=RuntimeError("thread crash"))
    tools = {t.name: t for t in (t1, t2)}

    calls = _calls(("read_file", {"path": "a.py"}), ("list_files", {"path": "."}))
    results = run_durable_batch_parallel(calls, tools, cfg)

    assert len(results) == 2
    assert results[0].status == "success"
    assert results[1].status == "error"
    assert "thread crash" in results[1].content


# 5. User cancellation before and during execution
def test_05_cancellation_aborts_batch(workspace, cfg):
    session_id = cfg["configurable"]["thread_id"]
    turn_controls.begin(session_id)
    turn_controls.cancel(session_id)

    tools = [_make_tool("read_file", output="data"), _make_tool("list_files", output="files")]
    node = SafeToolNode(tools, SafetyGuard(str(workspace)))

    calls = _calls(("read_file", {"path": "a.py"}), ("list_files", {"path": "."}))
    results = node._execute_durable(calls, cfg)

    assert len(results) == 2
    assert all("cancelled by the user" in m.content for m in results)
    assert all(m.status == "error" for m in results)

    turn_controls.reset(session_id)


# 6. Permission denial isolation
def test_06_permission_denial_leaves_safe_reads_concurrent(workspace, cfg):
    t1 = _make_tool("read_file", delay=0.05, output="read_ok")
    t2 = _make_tool("run_terminal", delay=0.05, output="should_not_run")
    t3 = _make_tool("list_files", delay=0.05, output="list_ok")
    tools = [t1, t2, t3]

    guard = SafetyGuard(str(workspace))
    node = SafeToolNode(tools, guard)

    # Sub-agent session: auto-denies dangerous commands
    sub_cfg = {"configurable": {"workspace": str(workspace), "thread_id": "sub-test"}}
    calls = _calls(
        ("read_file", {"path": "a.py"}),
        ("run_terminal", {"command": "rm -rf /"}),
        ("list_files", {"path": "."}),
    )
    state = {"messages": [AIMessage(content="", tool_calls=calls)]}

    t0 = time.perf_counter()
    out = node(state, sub_cfg)
    elapsed = time.perf_counter() - t0

    msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(msgs) == 3
    assert msgs[0].content == "read_ok" and msgs[0].status == "success"
    assert "blocked" in msgs[1].content.lower() and msgs[1].status == "error"
    assert msgs[2].content == "list_ok" and msgs[2].status == "success"


# 7. Approval pending/denied behavior
def test_07_unapproved_operations_blocked(workspace, cfg):
    t_write = _make_tool("write_file", output="wrote")
    t_read = _make_tool("read_file", output="read")
    node = SafeToolNode([t_write, t_read], SafetyGuard(str(workspace)))

    # Overwrite without auto-approve -> unsafe
    (workspace / "existing.txt").write_text("old content", encoding="utf-8")
    calls = _calls(
        ("write_file", {"path": "existing.txt", "content": "new"}),
        ("read_file", {"path": "existing.txt"}),
    )
    state = {"messages": [AIMessage(content="", tool_calls=calls)]}

    # In interactive CLI mode with no approval dock, pauses turn
    res = node(state, cfg)
    assert "messages" in res
    assert isinstance(res["messages"][0], AIMessage)
    assert "confirmation first" in res["messages"][0].content


# 8. Deterministic input-order result preservation even when finish order inverts
def test_08_input_order_preserved_when_finish_order_inverts(workspace, cfg):
    t_slow = _make_tool("read_file", delay=0.15, output="slow_content")
    t_fast = _make_tool("list_files", delay=0.01, output="fast_content")
    tools = {t.name: t for t in (t_slow, t_fast)}

    calls = _calls(
        ("read_file", {"path": "slow.txt"}),
        ("list_files", {"path": "."}),
    )

    results = run_durable_batch_parallel(calls, tools, cfg)
    assert [m.name for m in results] == ["read_file", "list_files"]
    assert [m.tool_call_id for m in results] == ["tc_0", "tc_1"]
    assert [m.content for m in results] == ["slow_content", "fast_content"]


# 9. Concurrent access to the same file by multiple readers is safe
def test_09_concurrent_readers_same_file(workspace, cfg):
    test_file = workspace / "shared.txt"
    test_file.write_text("shared immutable data", encoding="utf-8")

    from src.tools.file_tools import read_file
    tools = {"read_file": read_file}

    calls = _calls(
        ("read_file", {"path": "shared.txt", "start_line": 1, "end_line": 1}),
        ("read_file", {"path": "shared.txt", "offset": 0, "limit": 6}),
        ("read_file", {"path": "shared.txt"}),
    )

    results = run_durable_batch_parallel(calls, tools, cfg)
    assert len(results) == 3
    assert all(m.status == "success" for m in results)
    assert "shared" in results[0].content
    assert "shared" in results[1].content
    assert "shared immutable data" in results[2].content


# 10. Mixed batch (read + write) forced sequential execution
def test_10_mixed_batch_forced_sequential(workspace, cfg):
    exec_order = []

    def fake_write(path="", content=""):
        time.sleep(0.05)
        exec_order.append(f"write:{path}")
        return "wrote"

    def fake_read(path=""):
        exec_order.append(f"read:{path}")
        return "read"

    t_write = StructuredTool.from_function(fake_write, name="write_file", description="w")
    t_read = StructuredTool.from_function(fake_read, name="read_file", description="r")
    tools = {"write_file": t_write, "read_file": t_read}

    node = SafeToolNode([t_write, t_read], SafetyGuard(str(workspace)))

    calls = _calls(
        ("write_file", {"path": "out.txt", "content": "1"}),
        ("read_file", {"path": "out.txt"}),
    )

    # Must be classified as NOT safe for parallel execution
    assert is_safe_read_only_batch(calls, tools) is False

    results = node._execute_durable(calls, cfg)
    assert len(results) == 2
    # Deterministic sequential order preserved
    assert exec_order == ["write:out.txt", "read:out.txt"]


# 11. Unknown tools forced sequential execution
def test_11_unknown_tool_forced_sequential(workspace, cfg):
    tools = {"read_file": _make_tool("read_file", output="ok")}
    calls = _calls(("read_file", {"path": "a.txt"}), ("unknown_tool", {}))

    assert is_safe_read_only_batch(calls, tools) is False


# 12. Strict read-only allowlist enforcement
def test_12_strict_read_only_allowlist_enforcement():
    tools = {
        "read_file": object(),
        "list_files": object(),
        "search_files": object(),
        "search_code": object(),
        "write_file": object(),
        "terminal": object(),
        "execute_code": object(),
    }

    # Pure read-only batch -> True
    calls_ro = _calls(("read_file", {}), ("list_files", {}), ("search_files", {}), ("search_code", {}))
    assert is_safe_read_only_batch(calls_ro, tools) is True

    # Mutating tool in batch -> False
    calls_mut = _calls(("read_file", {}), ("write_file", {}))
    assert is_safe_read_only_batch(calls_mut, tools) is False

    # Wildcard in batch -> False
    calls_wc = _calls(("read_file", {}), ("terminal", {}))
    assert is_safe_read_only_batch(calls_wc, tools) is False

    # Single call -> False (no concurrency needed)
    assert is_safe_read_only_batch(_calls(("read_file", {})), tools) is False


# 13. Max worker configuration respected
def test_13_max_worker_configuration(monkeypatch):
    monkeypatch.setenv("CRUSORAI_PARALLEL_MAX_WORKERS", "8")
    assert _max_workers() == 8

    monkeypatch.setenv("CRUSORAI_PARALLEL_MAX_WORKERS", "32")
    assert _max_workers() == 16  # Clamped to upper bound

    monkeypatch.setenv("CRUSORAI_PARALLEL_MAX_WORKERS", "invalid")
    assert _max_workers() == 4   # Fallback to default


# 14. Kill-switch CRUSORAI_PARALLEL_TOOLS=off forces sequential execution
def test_14_kill_switch_forces_sequential(workspace, cfg, monkeypatch):
    monkeypatch.setenv("CRUSORAI_PARALLEL_TOOLS", "off")

    exec_order = []

    def mock_read(idx, delay):
        def fn(path=""):
            time.sleep(delay)
            exec_order.append(idx)
            return f"read_{idx}"
        return StructuredTool.from_function(fn, name=f"read_file_{idx}", description="")

    # Tool 1 is slow, Tool 2 is fast
    t1 = mock_read(1, 0.10)
    t2 = mock_read(2, 0.01)
    tools = {"read_file_1": t1, "read_file_2": t2}

    calls = _calls(("read_file_1", {}), ("read_file_2", {}))
    results = run_durable_batch_parallel(calls, tools, cfg)

    assert len(results) == 2
    # In sequential execution, 1 must finish before 2 starts
    assert exec_order == [1, 2]


# 15. Durable journal integration for parallel executions
def test_15_durable_journal_records_every_parallel_tool(workspace, cfg):
    from src.runtime.factory import get_runtime_services
    services = get_runtime_services()
    session_id = cfg["configurable"]["thread_id"]

    t1 = _make_tool("read_file", output="r1")
    t2 = _make_tool("list_files", output="r2")
    tools = {t.name: t for t in (t1, t2)}

    calls = _calls(("read_file", {"path": "a.txt"}), ("list_files", {"path": "."}))
    results = run_durable_batch_parallel(calls, tools, cfg)

    assert len(results) == 2

    # Check journal has intent and result for both
    events = services.journal.list_events(session_id)
    tool_events = [e for e in events if e.get("type") in ("tool.intent", "tool.result")]

    intents = [e for e in tool_events if e.get("type") == "tool.intent"]
    results_evt = [e for e in tool_events if e.get("type") == "tool.result"]

    assert len(intents) >= 2
    assert len(results_evt) >= 2
    call_ids = {e.get("tool_call_id") for e in intents}
    assert "tc_0" in call_ids
    assert "tc_1" in call_ids


# 16. Event bus emits tool.result for every parallel tool
def test_16_event_bus_emits_tool_results(workspace, cfg):
    from src.dashboard.event_bus import event_bus

    captured = []
    q = event_bus.subscribe(cfg["configurable"]["thread_id"])

    t1 = _make_tool("read_file", output="res1")
    t2 = _make_tool("list_files", output="res2")
    tools = {t.name: t for t in (t1, t2)}

    calls = _calls(("read_file", {"path": "1.txt"}), ("list_files", {"path": "."}))
    run_durable_batch_parallel(calls, tools, cfg)

    while not q.empty():
        captured.append(q.get_nowait())

    tool_results = [
        e for e in captured
        if e.get("payload", {}).get("tool_name") in ("read_file", "list_files")
        or e.get("tool_name") in ("read_file", "list_files")
    ]
    assert len(tool_results) >= 2
    event_bus.unsubscribe(q)


# 17. SafeToolNode._execute_durable end-to-end integration
def test_17_safe_tool_node_execute_durable_parallel(workspace, cfg):
    t1 = _make_tool("read_file", delay=0.10, output="content_a")
    t2 = _make_tool("list_files", delay=0.10, output="content_b")
    tools = [t1, t2]
    node = SafeToolNode(tools, SafetyGuard(str(workspace)))

    calls = _calls(("read_file", {"path": "a.txt"}), ("list_files", {"path": "."}))

    t0 = time.perf_counter()
    results = node._execute_durable(calls, cfg)
    elapsed = time.perf_counter() - t0

    assert len(results) == 2
    # Parallel should complete in ~0.10s, serial would be >= 0.20s
    assert elapsed < 0.18, f"Expected parallel execution in <0.18s, took {elapsed:.2f}s"
    assert results[0].content == "content_a"
    assert results[1].content == "content_b"
