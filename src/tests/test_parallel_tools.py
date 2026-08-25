"""Pins for D34 (steal #10, §46): the tool-BATCH GATE — safe batches keep
concurrent execution, REFUSED batches (path conflict / wildcard blast
radius) are forced sequential in input order, unknown tools fall through
to ToolNode's canonical error, kill-switch restores TRUE legacy.

HONEST PREMISE pinned loudly: langgraph's ToolNode ALREADY runs batches
concurrently (D34v1 assumed serial; the measure script's serial-floor
assert caught the lie, §46). Legacy "off" therefore pins CONCURRENCY +
the stale-read race — not serial.

Fakes via StructuredTool (registry identity), mini-graph fixture for
end-to-end pins (bare ToolNode.invoke dies outside compile, §27).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph

from src.context.safety_guard import SafetyGuard
from src.graphs.chat_graph import SafeToolNode
from src.graphs.parallel_tools import (
    is_eligible,
    try_parallel_batch,
    try_sequential_batch,
)


def _mk(name: str, delay: float, out: str | None = None, boom: Exception | None = None):
    def fn(x: str = "") -> str:
        time.sleep(delay)
        if boom is not None:
            raise boom
        return out if out is not None else f"{name}:{x}"
    return StructuredTool.from_function(fn, name=name, description=f"fake {name}")


def _calls(*specs):
    return [
        {"name": n, "args": a, "id": f"tc{i}", "type": "tool_call"}
        for i, (n, a) in enumerate(specs)
    ]


def _state(calls):
    return {"messages": [AIMessage(content="", tool_calls=calls)]}


def _cfg(ws):
    return {"configurable": {"workspace": str(ws), "thread_id": "main",
                             "provider": "x", "model": "y"}}


# ------------------------------------------------------------ eligibility

def test_conflicting_writer_blocks_parallel(tmp_path):
    from src.tools.file_tools import read_file, write_file  # noqa
    registry = {t.name: t for t in (read_file, write_file)}
    assert is_eligible(
        _calls(("write_file", {"path": "a.txt", "content": "x"}),
               ("read_file", {"path": "a.txt"})),
        registry, str(tmp_path),
    ) is False, "writer+reader on the SAME file must stay sequential"
    assert is_eligible(
        _calls(("write_file", {"path": "a.txt", "content": "x"}),
               ("read_file", {"path": "b.txt"})),
        registry, str(tmp_path),
    ) is True, "disjoint paths are parallelizable"


def test_wildcard_unknown_and_singleton_blocked(tmp_path):
    registry = {"read_file": object()}
    assert is_eligible(_calls(("execute_code", {"code": "1"}),
                            ("read_file", {"path": "a"})),
                       registry, str(tmp_path)) is False
    assert is_eligible(_calls(("mystery_tool", {}), ("read_file", {"path": "a"})),
                       registry, str(tmp_path)) is False
    assert is_eligible(_calls(("read_file", {"path": "a"})),
                       registry, str(tmp_path)) is False


# ------------------------------------------------------------ execution

def test_results_follow_input_order_even_when_finish_order_inverts(tmp_path):
    tools = {t.name: t for t in (
        _mk("a_slow", 0.20), _mk("b_fast", 0.03), _mk("c_mid", 0.10))}
    out = try_parallel_batch(
        _calls(("a_slow", {"x": "1"}), ("b_fast", {"x": "2"}), ("c_mid", {"x": "3"})),
        tools, _cfg(tmp_path), str(tmp_path),
    )
    assert [m.name for m in out] == ["a_slow", "b_fast", "c_mid"]
    assert [m.tool_call_id for m in out] == ["tc0", "tc1", "tc2"]
    assert [m.content for m in out] == ["a_slow:1", "b_fast:2", "c_mid:3"]


def test_error_slot_pairs_and_never_raises(tmp_path):
    tools = {t.name: t for t in (
        _mk("fine_a", 0.01), _mk("doom", 0.01, boom=ValueError("disk died")),
        _mk("fine_b", 0.01))}
    out = try_parallel_batch(
        _calls(("fine_a", {}), ("doom", {}), ("fine_b", {})),
        tools, _cfg(tmp_path), str(tmp_path),
    )
    assert len(out) == 3
    assert out[1].status == "error"
    assert "doom" in out[1].content and "disk died" in out[1].content
    assert out[1].tool_call_id == "tc1"
    assert out[0].status != "error" and out[2].status != "error"


def test_outputs_match_sequential_toolnode_shape(tmp_path):
    """Equivalence on content+order: parallel == what a sequential pass
    yields (same fake funcs, deterministic outputs)."""
    tools = {t.name: t for t in (_mk("one", 0.01), _mk("two", 0.01))}
    calls = _calls(("one", {"x": "a"}), ("two", {"x": "b"}))
    seq = [tools["one"].invoke({"x": "a"}), tools["two"].invoke({"x": "b"})]
    par = try_parallel_batch(calls, tools, _cfg(tmp_path), str(tmp_path))
    assert [m.content for m in par] == seq


def test_kill_switch_returns_none(tmp_path, monkeypatch):
    tools = {t.name: t for t in (_mk("x", 0.01), _mk("y", 0.01))}
    calls = _calls(("x", {}), ("y", {}))
    monkeypatch.setenv("PULSEAI_PARALLEL_TOOLS", "off")
    assert try_parallel_batch(calls, tools, _cfg(tmp_path), str(tmp_path)) is None
    assert try_sequential_batch(calls, tools, _cfg(tmp_path), str(tmp_path)) is None


# ------------------------------------------- the gate's sequential half

def _order_tools(log: list, w_delay=0.30):
    """write_file (slow) + read_file (instant) fakes that record order."""
    def write_file(path: str = "", content: str = "") -> str:
        time.sleep(w_delay)
        log.append("w")
        return f"wrote:{path}"
    def read_file(path: str = "") -> str:
        log.append("r")
        return f"read:{path}"
    return [
        StructuredTool.from_function(write_file, name="write_file",
                                     description="fake writer"),
        StructuredTool.from_function(read_file, name="read_file",
                                     description="fake reader"),
    ]


def test_conflicting_batch_forced_sequential_deterministic(
        tmp_path, monkeypatch):
    """write+read the SAME path in one batch => sequential, input order,
    ALWAYS (this shape raced before D34: concurrent reader won)."""
    monkeypatch.delenv("PULSEAI_PARALLEL_TOOLS", raising=False)
    log: list = []
    node = SafeToolNode(_order_tools(log), SafetyGuard(str(tmp_path)))
    st = _state(_calls(("write_file", {"path": "x.txt", "content": "NEW"}),
                       ("read_file", {"path": "x.txt"})))
    t0 = time.perf_counter()
    out = _reach_node(node, st, _cfg(tmp_path))
    dt = time.perf_counter() - t0
    assert log == ["w", "r"], "conflicting batch must run in INPUT order"
    assert dt >= 0.28, f"wall {dt:.2f}s too small — it ran concurrently"
    msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.name for m in msgs] == ["write_file", "read_file"]
    assert msgs[0].content == "wrote:x.txt"
    assert msgs[1].content == "read:x.txt"


def test_killswitch_restores_true_legacy_concurrency(
        tmp_path, monkeypatch):
    """LOUD pin of the honest premise: with the gate OFF, ToolNode runs
    the SAME conflicting batch CONCURRENTLY — the instant reader logs
    FIRST. 'off' = true legacy, races included; never mistake it for
    serial."""
    monkeypatch.setenv("PULSEAI_PARALLEL_TOOLS", "off")
    log: list = []
    node = SafeToolNode(_order_tools(log), SafetyGuard(str(tmp_path)))
    st = _state(_calls(("write_file", {"path": "x.txt", "content": "NEW"}),
                       ("read_file", {"path": "x.txt"})))
    t0 = time.perf_counter()
    out = _reach_node(node, st, _cfg(tmp_path))
    dt = time.perf_counter() - t0
    # The ORDER is the discriminator (writer 0.3s slow, reader instant):
    # concurrent => reader logs first. (Wall can't discriminate here —
    # both shapes cost ~max(calls); a serial signature would be sum().)
    assert log == ["r", "w"], "legacy concurrency receipt: reader beats slow writer"
    assert dt < 0.6, f"wall {dt:.2f}s — sanity bound blown, inspect above"


def test_fresh_content_vs_missing_read_race_receipt(tmp_path, monkeypatch):
    """The user-visible consequence, both sides in one pin: gate ON, the
    read returns the fresh content the batch just wrote; gate OFF
    (legacy), the SAME batch's read runs BEFORE the write and reports
    the file missing. Same-class race as write+read of an existing file —
    that shape is intercepted by the overwrite approval guard upstream,
    so the fresh-create shape is the clean deterministic harness here.
    Deterministic: writer is 0.3s slow, reader instant."""
    target = tmp_path / "x.txt"

    def write_file(path: str = "", content: str = "") -> str:
        time.sleep(0.30)
        (tmp_path / path).write_text(content)
        return "wrote"

    def read_file(path: str = "") -> str:
        p = tmp_path / path
        return p.read_text() if p.exists() else "MISSING"

    tools = [
        StructuredTool.from_function(write_file, name="write_file",
                                     description="fake writer"),
        StructuredTool.from_function(read_file, name="read_file",
                                     description="fake reader"),
    ]

    def run_once():
        node = SafeToolNode(tools, SafetyGuard(str(tmp_path)))
        st = _state(_calls(
            ("write_file", {"path": "x.txt", "content": "NEW"}),
            ("read_file", {"path": "x.txt"})))
        out = _reach_node(node, st, _cfg(tmp_path))
        return [m for m in out["messages"] if isinstance(m, ToolMessage)][1]

    monkeypatch.delenv("PULSEAI_PARALLEL_TOOLS", raising=False)
    reader_msg = run_once()
    assert target.read_text() == "NEW"
    assert reader_msg.content == "NEW", \
        "gate ON: create-then-read of one file must read the FRESH content"

    target.unlink()
    monkeypatch.setenv("PULSEAI_PARALLEL_TOOLS", "off")
    reader_msg = run_once()
    assert target.read_text() == "NEW"
    assert reader_msg.content == "MISSING", \
        "legacy receipt: the concurrent reader finished before the writer"


def test_wildcard_batch_forced_sequential(tmp_path, monkeypatch):
    monkeypatch.delenv("PULSEAI_PARALLEL_TOOLS", raising=False)
    log: list = []

    def execute_code(code: str = "") -> str:
        time.sleep(0.05)
        log.append("x")
        return "ran"

    def read_file(path: str = "") -> str:
        log.append("r")
        return "content"

    tools = [
        StructuredTool.from_function(execute_code, name="execute_code",
                                     description="fake exec"),
        StructuredTool.from_function(read_file, name="read_file",
                                     description="fake reader"),
    ]
    node = SafeToolNode(tools, SafetyGuard(str(tmp_path)))
    st = _state(_calls(("execute_code", {"code": "print(1)"}),
                       ("read_file", {"path": "unrelated.txt"})))
    out = _reach_node(node, st, _cfg(tmp_path))
    assert log == ["x", "r"], "wildcard batches run in strict input order"
    msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.content for m in msgs] == ["ran", "content"]


def test_unknown_tool_falls_through_toolnode_canonical(
        tmp_path, monkeypatch):
    monkeypatch.delenv("PULSEAI_PARALLEL_TOOLS", raising=False)
    tools = [_mk("slow_a", 0.01)]
    node = SafeToolNode(tools, SafetyGuard(str(tmp_path)))
    st = _state(_calls(("slow_a", {"x": "1"}), ("mystery", {})))
    out = _reach_node(node, st, _cfg(tmp_path))
    msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(msgs) == 2
    err = [m for m in msgs if m.name == "mystery"][0]
    assert err.status == "error"
    assert "not a valid tool" in err.content and "mystery" in err.content
    ok = [m for m in msgs if m.name == "slow_a"][0]
    assert ok.status != "error" and ok.content == "slow_a:1"


def test_sequential_error_slot_pairs_and_continues(tmp_path, monkeypatch):
    monkeypatch.delenv("PULSEAI_PARALLEL_TOOLS", raising=False)
    log: list = []
    tools = _order_tools(log, w_delay=0.01)
    doomed = StructuredTool.from_function(
        (lambda path="", content="": (_ for _ in ()).throw(
            ValueError("disk died"))),
        name="write_file", description="doomed writer")
    tools[0] = doomed
    node = SafeToolNode(tools, SafetyGuard(str(tmp_path)))
    st = _state(_calls(("write_file", {"path": "x.txt", "content": "N"}),
                       ("read_file", {"path": "x.txt"})))
    out = _reach_node(node, st, _cfg(tmp_path))
    msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert msgs[0].status == "error"
    assert "write_file" in msgs[0].content and "disk died" in msgs[0].content
    assert msgs[0].tool_call_id == "tc0"
    assert msgs[1].status != "error" and msgs[1].content == "read:x.txt"
    assert log == ["r"], "reader still ran after the writer's error"


# ------------------------------------------------- end-to-end wall clock

def _reach_node(node_func, state, cfg):
    g = StateGraph(MessagesState)
    g.add_node("tools", node_func)
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    out = g.compile().invoke(state, config=cfg)
    return {"messages": out["messages"][len(state["messages"]):]}


def test_parallel_batch_beats_serial_wall_clock(tmp_path, monkeypatch):
    monkeypatch.delenv("PULSEAI_PARALLEL_TOOLS", raising=False)
    tools = [_mk("slow_a", 0.25), _mk("slow_b", 0.25), _mk("slow_c", 0.25)]
    node = SafeToolNode(tools, SafetyGuard(str(tmp_path)))
    t0 = time.perf_counter()
    out = _reach_node(node, _state(_calls(
        ("slow_a", {"x": "1"}), ("slow_b", {"x": "2"}), ("slow_c", {"x": "3"}),
    )), _cfg(tmp_path))
    dt = time.perf_counter() - t0
    # Serial = >= 0.75s. Parallel target < 0.6s leaves 2x CI headroom.
    assert dt < 0.6, f"batch took {dt:.2f}s — ran sequentially"
    msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.name for m in msgs] == ["slow_a", "slow_b", "slow_c"]
    assert [m.content for m in msgs] == ["slow_a:1", "slow_b:2", "slow_c:3"]


def test_wiring_returns_parallel_results_without_touching_toolnode(
        tmp_path, monkeypatch):
    """Wiring pin: when the helper yields results, __call__ returns them
    verbatim (and the sequential node is never reached)."""
    tools = [_mk("p", 0.01), _mk("q", 0.01)]
    node = SafeToolNode(tools, SafetyGuard(str(tmp_path)))
    sentinel = [ToolMessage(content="S", tool_call_id="tc0", name="p"),
                ToolMessage(content="T", tool_call_id="tc1", name="q")]
    import src.graphs.parallel_tools as pt
    monkeypatch.setattr(pt, "try_parallel_batch",
                        lambda *a, **k: sentinel)
    out = node(_state(_calls(("p", {}), ("q", {}))), _cfg(tmp_path))
    assert out == {"messages": sentinel}


def test_repair_tool_call_ids_deduplicates_deterministically():
    """hermes _uniquify_tool_call_ids (#58327): reused call ids in one
    batch silently lose the later call's result. Repair must dedupe with
    a STABLE scheme (cache prefixes must not churn)."""
    from src.graphs.parallel_tools import repair_tool_call_ids
    calls = [
        {"name": "write_file", "args": {"path": "a.ts"}, "id": "dup", "type": "tool_call"},
        {"name": "write_file", "args": {"path": "b.ts"}, "id": "dup", "type": "tool_call"},
        {"name": "write_file", "args": {"path": "c.ts"}, "id": "", "type": "tool_call"},
    ]
    repaired, changed = repair_tool_call_ids(calls)
    assert changed is True
    ids = [c["id"] for c in repaired]
    assert len(set(ids)) == 3, f"ids must be unique: {ids}"
    assert ids[0] == "dup", "first occurrence keeps its id"
    assert ids[1].startswith("call_") and ids[2].startswith("call_")
    # deterministic: same input -> same ids
    again, _ = repair_tool_call_ids(calls)
    assert [c["id"] for c in again] == ids


def test_repair_tool_call_ids_noop_when_unique():
    from src.graphs.parallel_tools import repair_tool_call_ids
    calls = [
        {"name": "read_file", "args": {"path": "a"}, "id": "x1", "type": "tool_call"},
        {"name": "read_file", "args": {"path": "b"}, "id": "x2", "type": "tool_call"},
    ]
    repaired, changed = repair_tool_call_ids(calls)
    assert changed is False


# ------------------------------------------------------------ D11 guard


def test_unsafe_call_in_batch_denied_alone_rest_execute(tmp_path, monkeypatch):
    """D11: the old guard rejected the ENTIRE batch when one call was
    unsafe (and fabricated an AIMessage that read as the model's own
    words). Under autonomous mode a mixed batch must deny only the
    unsafe call (ToolMessage, model adapts in one turn) and still
    execute the safe ones."""
    monkeypatch.setenv("PULSEAI_AUTO_APPROVE_WRITES", "1")
    log: list = []

    def write_file(path: str = "", content: str = "") -> str:
        log.append("w")
        (tmp_path / path).write_text(content)
        return "wrote"

    def read_file(path: str = "") -> str:
        log.append("r")
        return "read"

    def run_terminal(command: str = "") -> str:
        log.append("t")
        return "ran"

    tools = [
        StructuredTool.from_function(write_file, name="write_file",
                                     description="fake writer"),
        StructuredTool.from_function(read_file, name="read_file",
                                     description="fake reader"),
        StructuredTool.from_function(run_terminal, name="run_terminal",
                                     description="fake terminal"),
    ]
    node = SafeToolNode(tools, SafetyGuard(str(tmp_path)))
    st = _state(_calls(
        ("run_terminal", {"command": "rm -rf keep"}),               # unsafe
        ("read_file", {"path": "other.txt"}),                      # safe
        ("write_file", {"path": "fresh.txt", "content": "N"}),   # safe
    ))
    out = _reach_node(node, st, _cfg(tmp_path))
    msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(msgs) == 3, f"expected 3 results (1 denial + 2 runs), got {len(msgs)}"
    # Denial for the dangerous command, in the model's original order.
    denied = msgs[0]
    assert denied.tool_call_id == "tc0"
    assert denied.status == "error"
    assert "BLOCKED" in denied.content and "rm -rf" in denied.content
    assert "confirmation first" not in denied.content
    assert "do not wait for approval" in denied.content
    # Safe calls executed.
    assert msgs[1].tool_call_id == "tc1" and msgs[1].content == "read"
    assert msgs[2].tool_call_id == "tc2" and msgs[2].content == "wrote"
    assert log == ["r", "w"], "safe calls must run; only the unsafe one is denied"
    assert "t" not in log, "the dangerous command must never execute"
    # No fabricated AIMessage pretending the model asked for confirmation.
    assert not any(isinstance(m, AIMessage) for m in out["messages"])


def test_workspace_session_lands_large_safe_write_without_approval_wait(tmp_path, monkeypatch):
    """Test-5 regression: a large complete write is valid work, not a reason
    for a headless bridge to emit safety_request and wait for a UI forever."""
    monkeypatch.delenv("PULSEAI_AUTO_APPROVE_WRITES", raising=False)
    payload = "const shader = `" + ("x" * 35_000) + "`;\n"

    def write_file(path: str = "", content: str = "") -> str:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return "wrote"

    tool = StructuredTool.from_function(
        write_file, name="write_file", description="fake writer"
    )
    node = SafeToolNode([tool], SafetyGuard(str(tmp_path)))
    cfg = _cfg(tmp_path)
    cfg["configurable"].update({
        "approval_channel": True,
        "approval_policy": "workspace_session",
        "approval_timeout": 0.01,
    })
    out = _reach_node(
        node,
        _state(_calls(("write_file", {"path": "src/main.js", "content": payload}))),
        cfg,
    )
    messages = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(messages) == 1 and messages[0].content == "wrote"
    assert (tmp_path / "src" / "main.js").read_text(encoding="utf-8") == payload


def test_auto_approve_writes_allows_ordinary_overwrite(tmp_path, monkeypatch):
    """D11: PULSEAI_AUTO_APPROVE_WRITES=1 (autonomous eval, no human)
    lets the agent overwrite ordinary workspace files — it must be able
    to FIX its own files or it deadlocks (D9: tsconfig fix blocked 4x,
    model declared Finished on a broken app). Critical paths and
    dangerous commands still block."""
    monkeypatch.setenv("PULSEAI_AUTO_APPROVE_WRITES", "1")
    guard = SafetyGuard(str(tmp_path))
    (tmp_path / "page.tsx").write_text("old")
    ok, warning = guard.check_tool_call(
        "write_file", {"path": "page.tsx", "content": "new"})
    assert ok is True, "ordinary overwrite must pass under auto-approve"
    # Critical path still blocks.
    (tmp_path / ".env").write_text("SECRET=1")
    ok2, warning2 = guard.check_tool_call(
        "write_file", {"path": ".env", "content": "SECRET=2"})
    assert ok2 is False, "critical path must still block under auto-approve"
    # Dangerous command still blocks.
    ok3, _ = guard.check_tool_call("run_terminal", {"command": "rm -rf /x"})
    assert ok3 is False, "dangerous commands must still block under auto-approve"


def test_without_auto_approve_overwrite_still_flagged(tmp_path, monkeypatch):
    """Interactive default unchanged: overwrite of an existing file is
    still flagged for a human to confirm (auto-approve is opt-in)."""
    monkeypatch.delenv("PULSEAI_AUTO_APPROVE_WRITES", raising=False)
    guard = SafetyGuard(str(tmp_path))
    (tmp_path / "keep.txt").write_text("old")
    ok, warning = guard.check_tool_call(
        "write_file", {"path": "keep.txt", "content": "new"})
    assert ok is False
    assert "overwrite" in warning.lower()
