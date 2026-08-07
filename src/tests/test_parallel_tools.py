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
