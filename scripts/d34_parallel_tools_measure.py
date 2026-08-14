"""D34v2 (§46) measure: the tool-batch gate — safe batches stay parallel,
CONFLICTING batches stop racing.

HONEST PREMISE (measured here, pinned in §46): langgraph's ToolNode
ALREADY executes a multi-call batch CONCURRENTLY. The v1 design assumed
it was serial; the serial-floor assert in this very script caught the
lie (legacy "off" pass ran 0.31s, not the 1.2s serial floor). So D34 is
NOT a speed feature — it is a CORRECTNESS gate, which is also hermes'
actual design (_should_parallelize_tool_batch):

  A) [write x.txt "NEW" + read x.txt] in ONE batch, D34 ON:
     forced sequential in input order -> reader deterministically
     sees "NEW". Wall ~= writer(0.3s) + reader.
  B) same batch, PULSEAI_PARALLEL_TOOLS=off (TRUE legacy):
     ToolNode runs both at once -> reader finishes BEFORE the
     (0.3s-slowed) writer -> reader reports the file MISSING.
     The race, receipted. (Same-class as overwrite+read; that shape
     is intercepted by the overwrite approval guard upstream.)
  C) safe batch [read a,b,c,d] disjoint, D34 ON:
     stays concurrent, ~max(calls) not sum(calls).

Run:  python3 scripts/d34_parallel_tools_measure.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph

from src.context.safety_guard import SafetyGuard
from src.graphs.chat_graph import SafeToolNode

DELAY = 0.30


def _state(*specs):
    calls = [
        {"name": n, "args": a, "id": f"tc{i}", "type": "tool_call"}
        for i, (n, a) in enumerate(specs)
    ]
    return {"messages": [AIMessage(content="", tool_calls=calls)]}


def _reach(node, state, cfg):
    g = StateGraph(MessagesState)
    g.add_node("tools", node)
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    return g.compile().invoke(state, config=cfg)


def _tool_messages(out, state):
    return [m for m in out["messages"][len(state["messages"]):]
            if isinstance(m, ToolMessage)]


def _conflicting_batch(parallel_on: bool):
    """[write x NEW (0.3s slow) + read x]. Returns (wall, reader_content)."""
    if parallel_on:
        os.environ.pop("PULSEAI_PARALLEL_TOOLS", None)
    else:
        os.environ["PULSEAI_PARALLEL_TOOLS"] = "off"
    with tempfile.TemporaryDirectory() as td:
        def write_file(path: str = "", content: str = "") -> str:
            time.sleep(DELAY)  # slow write -> race window for legacy
            (Path(td) / path).write_text(content)
            return "wrote"

        def read_file(path: str = "") -> str:
            p = Path(td) / path
            return p.read_text() if p.exists() else "MISSING"

        tools = [
            StructuredTool.from_function(write_file, name="write_file",
                                         description="fake writer"),
            StructuredTool.from_function(read_file, name="read_file",
                                         description="fake reader"),
        ]
        node = SafeToolNode(tools, SafetyGuard(td))
        cfg = {"configurable": {"workspace": td, "thread_id": "main",
                                "provider": "x", "model": "y"}}
        st = _state(("write_file", {"path": "x.txt", "content": "NEW"}),
                    ("read_file", {"path": "x.txt"}))
        t0 = time.perf_counter()
        out = _reach(node, st, cfg)
        dt = time.perf_counter() - t0
        msgs = _tool_messages(out, st)
        assert [m.name for m in msgs] == ["write_file", "read_file"]
        return dt, msgs[1].content


def _safe_batch() -> float:
    os.environ.pop("PULSEAI_PARALLEL_TOOLS", None)
    with tempfile.TemporaryDirectory() as td:
        def read_file(path: str = "") -> str:
            time.sleep(DELAY)
            return f"read:{path}"
        tools = [StructuredTool.from_function(read_file, name="read_file",
                                              description="fake reader")]
        node = SafeToolNode(tools, SafetyGuard(td))
        cfg = {"configurable": {"workspace": td, "thread_id": "main",
                                "provider": "x", "model": "y"}}
        st = _state(*[(("read_file", {"path": f"f{i}.txt"})) for i in range(4)])
        t0 = time.perf_counter()
        out = _reach(node, st, cfg)
        dt = time.perf_counter() - t0
        assert len(_tool_messages(out, st)) == 4
        return dt


def main() -> None:
    d34_wall, d34_content = _conflicting_batch(True)
    leg_wall, leg_content = _conflicting_batch(False)
    safe_wall = _safe_batch()

    print("D34 tool-batch gate — receipts")
    print(f"A) conflicting [write NEW (slow {DELAY}s) + read], D34 ON :")
    print(f"     wall={d34_wall:.2f}s (sequential, input order), "
          f"reader saw: {d34_content!r}")
    print(f"B) same batch, kill-switch OFF (legacy ToolNode)          :")
    print(f"     wall={leg_wall:.2f}s (concurrent — the honest premise), "
          f"reader saw: {leg_content!r}")
    print(f"C) safe disjoint batch [4 x {DELAY}s reads], D34 ON        :")
    print(f"     wall={safe_wall:.2f}s (serial sum would be ~{4 * DELAY:.2f}s)")

    # Loud, assertion-backed claims (all three must hold):
    # The CONTENT asserts carry the proof (deterministic: writer 0.3s,
    # reader instant). Wall asserts are wide sanity bounds only — with an
    # instant reader both shapes cost ~max(calls), so walls can't
    # discriminate this shape; order/contents do.
    assert d34_wall >= DELAY * 0.9, "sanity: writer slept"
    assert d34_content == "NEW", "D34 reader must see the fresh write"
    assert leg_wall < 2 * DELAY, "sanity: no pathological stall on legacy"
    assert leg_content == "MISSING", \
        "legacy race receipt: reader finished before the slow writer"
    assert safe_wall < 4 * DELAY * 0.6, "safe batches stay parallel"
    print("OK: D34 keeps safe batches parallel, stops the race; "
          "kill-switch restores true legacy (races and all).")


if __name__ == "__main__":
    main()
