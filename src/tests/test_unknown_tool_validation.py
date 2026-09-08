"""Unknown tool-name validation — hermes agent/turn_tool_validation.py +
agent_runtime_helpers.repair_tool_call (#33007), SafeToolNode-shaped.

Field receipt that pinned this (owner log 2026-09-08, run 2cef1d80): the
model emitted `terminal` — hermes' own shell tool name (terminal_tool.py
name="terminal") — and `Bash` into pulse's run_terminal-named toolset; both
fell through to ToolNode's terse unknown-name text with no catalog, the
model flailed (dir -R, 2>/dev/null || echo ...), and the turn finalized
"Ended unverified". Hermes repairs the name before validating, and answers
unrepairable names with tool-role error results carrying the catalog —
mixed batches error ONLY the invalid calls and run the valid ones.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool as lc_tool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.context.safety_guard import SafetyGuard  # noqa: E402
from src.graphs import chat_graph  # noqa: E402
from src.graphs.parallel_tools import repair_tool_call_name  # noqa: E402

_VALID = {
    "read_file", "write_file", "edit_file", "list_files", "search_code",
    "run_terminal", "start_terminal", "check_terminal", "stop_terminal",
    "browser_navigate",
}


def test_repair_table_hermes_shapes():
    assert repair_tool_call_name("terminal", _VALID) == "run_terminal"
    assert repair_tool_call_name("run terminal", _VALID) == "run_terminal"
    assert repair_tool_call_name("Run-Terminal", _VALID) == "run_terminal"
    assert repair_tool_call_name("ReadFile", _VALID) == "read_file"           # camel
    assert repair_tool_call_name("ReadFileTool", _VALID) == "read_file"       # suffix
    assert repair_tool_call_name("read file", _VALID) == "read_file"          # space
    assert repair_tool_call_name("read_file", _VALID) == "read_file"          # exact
    # XML attribute leakage (hermes #33007): trim at the first quote first.
    assert (
        repair_tool_call_name('terminal" parameter="command"', _VALID)
        == "run_terminal"
    )
    # fuzzy cutoff 0.7: a one-letter typo still lands.
    assert repair_tool_call_name("terminl", _VALID) == "run_terminal"
    # No plausible target: None (the caller must error with the catalog).
    assert repair_tool_call_name("Bash", _VALID) is None
    assert repair_tool_call_name("", _VALID) is None


@lc_tool
def echo_probe(text: str) -> str:
    """Echo probe tool used by the validation tests."""
    return f"echo:{text}"


def _node(tmp_path: Path) -> chat_graph.SafeToolNode:
    # run_terminal included: the fuzzy repair must see pulse's real shell tool
    # name to map hermes' `terminal` dialect onto it (field shape).
    from src.tools.terminal_tools import run_terminal
    return chat_graph.SafeToolNode(
        [echo_probe, run_terminal], safety_guard=SafetyGuard(str(tmp_path))
    )


def _config(tmp_path: Path) -> dict:
    return {"configurable": {"thread_id": "unknown-name-test", "workspace": str(tmp_path)}}


def test_mixed_batch_errors_only_the_invalid_call(tmp_path):
    node = _node(tmp_path)
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "Bash", "args": {"command": "ls"}, "id": "c1"},
        {"name": "echo_probe", "args": {"text": "hi"}, "id": "c2"},
    ])]}
    results = node(state, _config(tmp_path))["messages"]
    by_id = {m.tool_call_id: m for m in results if isinstance(m, ToolMessage)}
    assert set(by_id) == {"c1", "c2"}
    assert by_id["c1"].status == "error"
    assert "Tool 'Bash' does not exist" in by_id["c1"].content
    assert "echo_probe" in by_id["c1"].content       # the catalog, for self-correction
    assert by_id["c2"].content == "echo:hi"          # the valid call still ran


def test_all_invalid_batch_gets_catalog_errors(tmp_path):
    node = _node(tmp_path)
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "Bash", "args": {"command": "dir -R"}, "id": "c1"},
        {"name": "not_a_real_tool", "args": {}, "id": "c2"},
    ])]}
    results = node(state, _config(tmp_path))["messages"]
    assert len(results) == 2
    for m in results:
        assert isinstance(m, ToolMessage) and m.status == "error"
        assert "does not exist. Available tools:" in m.content and "echo_probe" in m.content


def test_blank_name_gets_the_terse_anti_priming_text(tmp_path):
    node = _node(tmp_path)
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "", "args": {}, "id": "c1"},
    ])]}
    results = node(state, _config(tmp_path))["messages"]
    assert len(results) == 1
    assert "tool name was empty" in results[0].content
    # hermes #47967: dumping the catalog feeds the echo loop — it must not.
    assert "Available tools:" not in results[0].content


def test_hermes_dialect_name_is_repaired_and_executed(tmp_path):
    node = _node(tmp_path)
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "terminal", "args": {"command": "echo repair-e2e"}, "id": "c1"},
    ])]}
    results = node(state, _config(tmp_path))["messages"]
    # The assistant message is rewritten (same id) so history shows the bound
    # name, then the call executes as run_terminal.
    repaired_ai = [m for m in results if isinstance(m, AIMessage)]
    assert repaired_ai and repaired_ai[0].tool_calls[0]["name"] == "run_terminal"
    executed = [m for m in results if isinstance(m, ToolMessage)]
    assert executed and executed[0].tool_call_id == "c1"
    assert "repair-e2e" in executed[0].content


def test_progress_printer_prints_fresh_labels_not_the_stale_tail():
    """Field log 2026-09-08: the printer showed steps_completed[-1] — a check
    on a running process classifies SKIP and records nothing, so the STALE
    start receipt printed again; a repeated start command dedups out of the
    list, so stop's receipt printed after start. The printer must emit the
    labels earned since the previous event and stay silent otherwise."""
    source = (Path(__file__).resolve().parents[1] / "graphs" / "chat_graph.py").read_text(
        encoding="utf-8"
    )
    assert "printed_step_labels" in source
    assert "printed_failed_labels" in source
    assert "latest = steps_completed[-1]" not in source
    assert "latest = failed_steps[-1]" not in source
