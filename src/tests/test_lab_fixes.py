

# ---------------------------------------------------------------------------
# Finish gate (hermes _CODEX_INCOMPLETE_NUDGE pattern)
# ---------------------------------------------------------------------------

def test_early_finish_on_execution_task_is_nudged():
    from src.graphs.chat_graph import should_continue, finish_gate_node
    from langchain_core.messages import AIMessage, HumanMessage

    state = {
        "messages": [HumanMessage("Build a chat app"), AIMessage("## ✅ Finished")],
        "current_task": "Build a chat app using Next.js and Tailwind",
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finish_gate"
    out = finish_gate_node(dict(state))
    assert out["finish_nudges"] == 1
    assert "almost no real work" in out["messages"][0].content


def test_finish_gate_respects_budget():
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage

    state = {
        "messages": [AIMessage("done")],
        "current_task": "Build a chat app",
        "finish_nudges": 2,  # budget exhausted
    }
    assert should_continue(state) == "finalize"


def test_finish_gate_allows_real_work():
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, HumanMessage

    state = {
        "messages": [
            HumanMessage("t"),
            AIMessage("", tool_calls=[{"name": "read_file", "args": {}, "id": "1"}]),
            AIMessage("", tool_calls=[{"name": "write_file", "args": {}, "id": "2"}]),
            AIMessage("done"),
        ],
        "current_task": "Build a chat app",
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_finish_gate_skips_chat_tasks():
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, HumanMessage

    state = {
        "messages": [HumanMessage("Explain routing"), AIMessage("Sure")],
        "current_task": "Explain how the router works",
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finalize"


# =====================================================================
# TEST 2 FIXES — verify gate + multi-language syntax receipt
# (hermes file_operations._check_lint pattern; Test 2 shipped 15
# syntax/type bugs because writes were blind and nothing forced
# verification before finalize)
# =====================================================================

def test_verify_gate_blocks_unverified_code_finish():
    """Code files written + no verification tool -> finish_gate (nudge)."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "2", "type": "tool_call"}]),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: a.tsx", "Wrote file: b.tsx"],
        "current_task": "build a chat app",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finish_gate"


def test_verify_gate_allows_after_typecheck():
    """Writes + typecheck_workspace -> finalize allowed."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "typecheck_workspace", "args": {}, "id": "2", "type": "tool_call"}]),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: a.tsx"],
        "current_task": "build a chat app",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_verify_gate_blocks_failed_typecheck():
    """Writes + typecheck that RAN but FAILED -> finish_gate (fix nudge)."""
    from src.graphs.chat_graph import should_continue, finish_gate_node
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "typecheck_workspace", "args": {}, "id": "2", "type": "tool_call"}]),
        ToolMessage(
            content="❌ typecheck_workspace: 25 type error(s) found. Fix ALL of them before finishing:",
            tool_call_id="2", name="typecheck_workspace"),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: a.tsx"],
        "current_task": "build a chat app",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finish_gate"
    out = finish_gate_node(state)
    assert "did NOT pass" in out["messages"][0].content
    assert out["verify_nudges"] == 1


def test_verify_gate_allows_passing_typecheck():
    """Writes + typecheck that PASSED -> finalize allowed."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "typecheck_workspace", "args": {}, "id": "2", "type": "tool_call"}]),
        ToolMessage(
            content="✅ typecheck_workspace: tsc --noEmit passed with 0 errors.",
            tool_call_id="2", name="typecheck_workspace"),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: a.tsx"],
        "current_task": "build a chat app",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_verify_gate_latest_typecheck_result_wins():
    """An earlier ❌ superseded by a later ✅ (agent fixed + re-verified)."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "typecheck_workspace", "args": {}, "id": "2", "type": "tool_call"}]),
        ToolMessage(
            content="❌ typecheck_workspace: 25 type error(s) found.",
            tool_call_id="2", name="typecheck_workspace"),
        AIMessage(content="x", tool_calls=[
            {"name": "edit_file", "args": {}, "id": "3", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "typecheck_workspace", "args": {}, "id": "4", "type": "tool_call"}]),
        ToolMessage(
            content="✅ typecheck_workspace: tsc --noEmit passed with 0 errors.",
            tool_call_id="4", name="typecheck_workspace"),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: a.tsx", "Edited file: a.tsx"],
        "current_task": "build a chat app",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_verify_gate_skips_non_execution_tasks():
    """Explanation tasks with file writes aren't forced to verify."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: notes.md"],
        "current_task": "Explain how routing works",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_syntax_receipt_tsx_missing_arrow():
    """Test 2 bug: `() {` missing arrow — write must be rejected."""
    from pathlib import Path
    from src.tools.file_tools import _syntax_receipt
    r = _syntax_receipt(
        Path("x.tsx"),
        "const ok = () => 1;\n",
        "const x = () { return 1; }\n",
    )
    assert r is not None
    assert "rejected" in r


def test_syntax_receipt_tsx_jsx_concat_attribute():
    """Test 2 bug: `className=\"x\" + y` — invalid JSX attribute."""
    from pathlib import Path
    from src.tools.file_tools import _syntax_receipt
    r = _syntax_receipt(
        Path("y.tsx"),
        "export const a = 1;\n",
        'export const a = <div className="x" + y />;\n',
    )
    assert r is not None


def test_syntax_receipt_delta_repair_allowed():
    """Already-broken file + broken update -> allowed (repair path)."""
    from pathlib import Path
    from src.tools.file_tools import _syntax_receipt
    r = _syntax_receipt(
        Path("z.tsx"),
        "const x = () { broken\n",
        "const x = () { still broken\n",
    )
    assert r is None


def test_syntax_receipt_clean_write_allowed():
    from pathlib import Path
    from src.tools.file_tools import _syntax_receipt
    r = _syntax_receipt(Path("w.tsx"), "const a = 1;\n", "const b = 2;\n")
    assert r is None


def test_syntax_receipt_bad_json_rejected():
    from pathlib import Path
    from src.tools.file_tools import _syntax_receipt
    r = _syntax_receipt(Path("c.json"), '{"a": 1}', '{"a": }')
    assert r is not None
