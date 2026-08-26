"""Pins for D20: sub-agent safety auto-deny (hermes delegate_tool.py:63-91).

Baseline proven before building: a sub-thread hitting a dangerous command
received the IDENTICAL "please confirm" AIMessage as an interactive
thread — a prompt addressed to a reader who does not exist (dead end ->
looped turns -> possible recursion-cap crash caught by D7's net).

D20 contract:
- interactive threads: UNCHANGED (approval prompt, nothing executes)
- sub threads: unsafe calls -> denial ToolMessages (status=error, ids
  paired, original tool_call order preserved); safe calls in the same
  batch STILL EXECUTE; every denial is audit-logged
- opt-in escape hatch: PULSEAI_SUBAGENT_AUTO_APPROVE=1 (batch/cron YOLO,
  hermes' subagent_auto_approve), also audit-logged
"""

from __future__ import annotations

import logging
import os

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from src.graphs.chat_graph import tool_node


def _invoke(state, cfg):
    """Reach the node the production way only: bare ToolNode.invoke dies
    on runtime config keys outside a compiled graph (learned in §27, same
    fixture as the crash-net pins)."""
    g = StateGraph(MessagesState)
    g.add_node("tools", tool_node)
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    out = g.compile().invoke(state, config=cfg)
    # add_messages reducer: response = original + appended tail
    return {"messages": out["messages"][len(state["messages"]):]}


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "precious.txt").write_text("do not delete")
    (tmp_path / "data.txt").write_text("line one\nline two\n")
    return tmp_path


def _cfg(ws, tid):
    return {"configurable": {"workspace": str(ws), "thread_id": tid,
                             "provider": "x", "model": "y"}}


def _state(*tool_calls):
    calls = []
    for i, (name, args) in enumerate(tool_calls):
        calls.append({"name": name, "args": args, "id": f"tc{i}", "type": "tool_call"})
    return {"messages": [AIMessage(content="", tool_calls=calls)]}


# ------------------------------------------------ interactive: unchanged
def test_main_thread_still_prompts_human(ws):
    out = _invoke(_state(("run_terminal", {"command": "rm -rf keep"})), _cfg(ws, "main-1"))
    msg = out["messages"][0]
    assert isinstance(msg, AIMessage) and not isinstance(msg, ToolMessage)
    assert "confirmation" in msg.content
    assert (ws / "keep" / "precious.txt").read_text() == "do not delete"


# ------------------------------------------------------ sub-agents: deny
def test_subagent_denial_is_toolmessage_not_prompt(ws, caplog):
    from src.dashboard.event_bus import event_bus
    event_bus.clear("sub-w-7")
    events = event_bus.subscribe("sub-w-7")
    with caplog.at_level(logging.WARNING, logger="pulseai.safety"):
        out = _invoke(_state(("run_terminal", {"command": "rm -rf keep"})), _cfg(ws, "sub-w-7"))
    msg = out["messages"][0]
    assert isinstance(msg, ToolMessage)
    assert msg.tool_call_id == "tc0" and msg.status == "error"
    assert "AUTO-DENIED" in msg.content
    assert "Do not retry" in msg.content
    assert "main session" in msg.content          # guidance, not a dead end
    assert (ws / "keep" / "precious.txt").read_text() == "do not delete"
    assert any("AUTO-DENIED" in r.message and "run_terminal" in r.message
               for r in caplog.records)           # hermes: both paths audit-log
    projected = []
    while not events.empty():
        projected.append(events.get_nowait())
    event_bus.unsubscribe(events)
    terminal = [event for event in projected if event["type"] == "tool.result"]
    assert len(terminal) == 1
    assert terminal[0]["payload"]["tool_id"] == "tc0"
    assert terminal[0]["payload"]["status"] == "error"


def test_subagent_mixed_batch_partial_execution_order_preserved(ws):
    out = _invoke(
        _state(
            ("read_file", {"path": "data.txt"}),
            ("run_terminal", {"command": "rm -rf keep"}),
            ("list_files", {"path": "."}),
        ),
        _cfg(ws, "sub-w-7"),
    )
    msgs = out["messages"]
    assert len(msgs) == 3 and all(isinstance(m, ToolMessage) for m in msgs)
    # Original tool_call order + exact id pairing, denial in the middle.
    assert [m.tool_call_id for m in msgs] == ["tc0", "tc1", "tc2"]
    assert "line one" in msgs[0].content          # safe call #1 really ran
    assert "AUTO-DENIED" in msgs[1].content       # denial kept its slot
    assert "data.txt" in msgs[2].content          # safe call #2 really ran
    assert (ws / "keep" / "precious.txt").exists()


def test_subagent_all_safe_calls_execute_normally(ws):
    out = _invoke(
        _state(("read_file", {"path": "data.txt"}), ("list_files", {"path": "."})),
        _cfg(ws, "sub-w-7"),
    )
    msgs = out["messages"]
    assert len(msgs) == 2
    assert "line one" in msgs[0].content
    assert all("AUTO-DENIED" not in m.content for m in msgs)


def test_subagent_unsafe_only_batch_never_prompts(ws):
    out = _invoke(
        _state(
            ("run_terminal", {"command": "rm -rf keep"}),
            ("write_file", {"path": "data.txt", "content": "overwrite"}),
        ),
        _cfg(ws, "sub-w-7"),
    )
    msgs = out["messages"]
    assert len(msgs) == 2 and all(isinstance(m, ToolMessage) for m in msgs)
    assert all("AUTO-DENIED" in m.content for m in msgs)
    assert ws.joinpath("data.txt").read_text() == "line one\nline two\n"  # overwrite denied


def test_auto_approve_escape_hatch(ws, monkeypatch, caplog):
    monkeypatch.setenv("PULSEAI_SUBAGENT_AUTO_APPROVE", "1")
    with caplog.at_level(logging.WARNING, logger="pulseai.safety"):
        out = _invoke(_state(("run_terminal", {"command": "echo approved > ok.txt"})),
                        _cfg(ws, "sub-cron-3"))
    msg = out["messages"][0]
    assert isinstance(msg, ToolMessage)
    assert "AUTO-DENIED" not in msg.content
    assert (ws / "ok.txt").exists()               # really executed
    assert any("AUTO-APPROVED" in r.message for r in caplog.records)


def test_env_default_off_and_main_unaffected_by_flag(ws, monkeypatch):
    # Flag set but thread is interactive: main path ignores it entirely.
    monkeypatch.setenv("PULSEAI_SUBAGENT_AUTO_APPROVE", "1")
    out = _invoke(_state(("run_terminal", {"command": "rm -rf keep"})), _cfg(ws, "main-1"))
    assert isinstance(out["messages"][0], AIMessage)  # still the human prompt
    assert (ws / "keep" / "precious.txt").exists()
    monkeypatch.delenv("PULSEAI_SUBAGENT_AUTO_APPROVE")
