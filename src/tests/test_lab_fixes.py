

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


def test_finish_gate_ignores_scratchpad_probe_calls():
    """think + list_files is NOT real work — declaring Finished after only
    those is an early stop (Test-2 retest workspace_d regression: the agent
    planned, listed an empty dir, and finalized with zero deliverables)."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, HumanMessage

    state = {
        "messages": [
            HumanMessage("Build a chat app"),
            AIMessage("", tool_calls=[{"name": "think", "args": {}, "id": "1"}]),
            AIMessage("", tool_calls=[{"name": "list_files", "args": {}, "id": "2"}]),
            AIMessage("## ✅ Finished"),
        ],
        "current_task": "Build a chat app using Next.js and Tailwind",
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finish_gate"


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
    """Non-UI execution: writes + typecheck_workspace -> finalize allowed."""
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
        "current_task": "build a REST API server in Python",
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
    """Non-UI execution: writes + typecheck that PASSED -> finalize allowed."""
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
        "current_task": "build a REST API server in Python",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_verify_gate_ui_typecheck_is_valid_evidence():
    """Policy-only gate (hermes verification_stop): the loop requires fresh
    verification EVIDENCE, never a specific tool. A passing typecheck is
    evidence the agent chose — the persona teaches that UI/frontend work
    additionally needs runtime proof in a real browser, but the gate does
    not hardcode browser-as-mandatory. The gate's job: evidence ran and
    is not failed."""
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
        "steps_completed": ["Wrote file: app/page.tsx"],
        "current_task": "build a chat app with Next.js",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_verify_gate_ui_allows_after_browser():
    """UI deliverable verified with a real browser_navigate + snapshot ->
    finalize allowed."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "browser_navigate", "args": {"url": "http://localhost:3000"}, "id": "2", "type": "tool_call"}]),
        ToolMessage(
            content="Current URL: http://localhost:3000\nTitle: Chat App\nHow Can I Help You?",
            tool_call_id="2", name="browser_navigate"),
        AIMessage(content="x", tool_calls=[
            {"name": "browser_snapshot", "args": {}, "id": "3", "type": "tool_call"}]),
        ToolMessage(
            content='{"url":"http://localhost:3000","title":"Chat App","text":"How Can I Help You?"}',
            tool_call_id="3", name="browser_snapshot"),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: app/page.tsx"],
        "current_task": "build a chat app with Next.js",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_verify_gate_ui_blocks_500_browser_result():
    """UI deliverable: browser_navigate that served an HTTP 500 is FAILED
    verification even after a clean tsc (D5's exact bug class)."""
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
        AIMessage(content="x", tool_calls=[
            {"name": "browser_navigate", "args": {"url": "http://localhost:3000"}, "id": "3", "type": "tool_call"}]),
        ToolMessage(
            content="GET / 500 in 9ms\nInternal Server Error: ChatLayout is importing hooks without 'use client'.",
            tool_call_id="3", name="browser_navigate"),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: app/page.tsx"],
        "current_task": "build a chat app with Next.js",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finish_gate"


def test_verify_gate_ui_blocks_empty_snapshot():
    """UI deliverable: typecheck ✅ + navigate ok + snapshot that returned
    NO rendered content is NOT verification — the page never painted (D6:
    dev server still compiling, snapshot {"title":"","text":""} and a
    timed-out screenshot, yet the agent declared Finished on a page that
    500'd at runtime with tsc clean). Gate nudges."""
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
        AIMessage(content="x", tool_calls=[
            {"name": "browser_navigate", "args": {"url": "http://localhost:3000"}, "id": "3", "type": "tool_call"}]),
        ToolMessage(
            content="Navigated to http://localhost:3000",
            tool_call_id="3", name="browser_navigate"),
        AIMessage(content="x", tool_calls=[
            {"name": "browser_snapshot", "args": {}, "id": "4", "type": "tool_call"}]),
        ToolMessage(
            content='Execution result:\n"{\\"url\\":\\"http://localhost:3000/\\",\\"title\\":\\"\\",\\"text\\":\\"\\"}"',
            tool_call_id="4", name="browser_snapshot"),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: app/page.tsx"],
        "current_task": "build a chat app with Next.js",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finish_gate"


def test_verify_gate_ui_blocks_screenshot_timeout():
    """UI deliverable: a screenshot that timed out means visual proof was
    never captured — the page may still be compiling. Gate nudges."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "browser_navigate", "args": {"url": "http://localhost:3000"}, "id": "2", "type": "tool_call"}]),
        ToolMessage(
            content="Navigated to http://localhost:3000",
            tool_call_id="2", name="browser_navigate"),
        AIMessage(content="x", tool_calls=[
            {"name": "browser_screenshot", "args": {"name": "shot"}, "id": "3", "type": "tool_call"}]),
        ToolMessage(
            content="[browser:puppeteer_screenshot] timed out after 60s — the page may still be loading; retry once or snapshot again.",
            tool_call_id="3", name="browser_screenshot"),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: app/page.tsx"],
        "current_task": "build a chat app with Next.js",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finish_gate"


def test_verify_gate_ui_rendered_snapshot_supersedes_failed_navigate():
    """UI deliverable: a later snapshot that shows real content supersedes
    an earlier failed navigate — the app was fixed and re-verified."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "browser_navigate", "args": {"url": "http://localhost:3000"}, "id": "2", "type": "tool_call"}]),
        ToolMessage(
            content="GET / 500 in 9ms\nInternal Server Error: missing 'use client'.",
            tool_call_id="2", name="browser_navigate"),
        AIMessage(content="x", tool_calls=[
            {"name": "edit_file", "args": {}, "id": "3", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "browser_snapshot", "args": {}, "id": "4", "type": "tool_call"}]),
        ToolMessage(
            content='Execution result:\n"{\\"url\\":\\"http://localhost:3000/\\",\\"title\\":\\"Chat App\\",\\"text\\":\\"How Can I Help You?\\"}"',
            tool_call_id="4", name="browser_snapshot"),
        AIMessage(content="done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: app/page.tsx", "Edited file: app/page.tsx"],
        "current_task": "build a chat app with Next.js",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_after_progress_plan_complete_but_unverified_routes_to_finish_gate():
    """D7 bypass: the model self-marked all 8 plan steps complete
    (including 'verify in browser' it never did), the last typecheck
    FAILED (57 errors), zero browser calls, no dev server — yet the
    plan-complete route in after_progress finalized clean with 0 nudges.
    Plan completion is model-DECLARED, so the plan-complete shortcut must
    consult the verify gate."""
    from src.graphs.chat_graph import after_progress
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "typecheck_workspace", "args": {}, "id": "2", "type": "tool_call"}]),
        ToolMessage(
            content="❌ typecheck_workspace: 57 type error(s) found. Fix ALL of them before finishing:",
            tool_call_id="2", name="typecheck_workspace"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: app/page.tsx", "Wrote file: components/ChatLayout.tsx"],
        "current_task": "Build an EaseMize-style chat application from scratch",
        "plan": [
            {"id": "1", "status": "completed", "description": "scaffold"},
            {"id": "2", "status": "completed", "description": "components"},
            {"id": "3", "status": "completed", "description": "typecheck"},
            {"id": "4", "status": "completed", "description": "browser verify"},
        ],
        "verify_nudges": 0,
        "finish_nudges": 0,
        "recovery_mode": False, "recovery_attempts": 0, "replan_needed": False,
        "env_failures": 0, "pivot_count": 0,
    }
    assert after_progress(state) == "finish_gate"


def test_after_progress_plan_complete_verified_finalizes():
    """Plan complete AND verification satisfied (typecheck ✅) -> finalize."""
    from src.graphs.chat_graph import after_progress
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage(content="x", tool_calls=[
            {"name": "typecheck_workspace", "args": {}, "id": "2", "type": "tool_call"}]),
        ToolMessage(
            content="✅ typecheck_workspace: tsc --noEmit passed with 0 errors.",
            tool_call_id="2", name="typecheck_workspace"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: app/page.tsx"],
        "current_task": "Build a REST API server in Python",
        "plan": [{"id": "1", "status": "completed", "description": "all done"}],
        "verify_nudges": 0,
        "finish_nudges": 0,
        "recovery_mode": False, "recovery_attempts": 0, "replan_needed": False,
        "env_failures": 0, "pivot_count": 0,
    }
    assert after_progress(state) == "finalize"


def test_after_progress_verify_budget_exhausted_allows_finalize():
    """Bounded: after 2 verify nudges the plan-complete route finalizes
    even if the model refused to verify — gates must not starve."""
    from src.graphs.chat_graph import after_progress
    from langchain_core.messages import AIMessage
    state = {
        "messages": [AIMessage(content="done")],
        "steps_completed": ["Wrote file: app/page.tsx"],
        "current_task": "build a chat app with Next.js",
        "plan": [{"id": "1", "status": "completed", "description": "all done"}],
        "verify_nudges": 2,
        "finish_nudges": 0,
        "recovery_mode": False, "recovery_attempts": 0, "replan_needed": False,
        "env_failures": 0, "pivot_count": 0,
    }
    assert after_progress(state) == "finalize"


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
        "current_task": "build a REST API server in Python",
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


def test_resolve_workspace_path_strips_workspace_leaf_prefix():
    """Test-2 retest bug: model wrote 'workspace_d/app/page.tsx' while inside
    workspace_d, double-nesting under workspace_d/workspace_d/. A leading
    component equal to the workspace's own basename must resolve to root."""
    from pathlib import Path
    from src.tools.file_tools import resolve_workspace_path

    root = Path("D:/pulseAIrepo/PulseAIRepo/lab/workspace_d")
    got = resolve_workspace_path(str(root), "workspace_d/app/page.tsx")
    assert got == root / "app" / "page.tsx"
    assert got.is_relative_to(root)


def test_resolve_workspace_path_plain_relative_unchanged():
    from pathlib import Path
    from src.tools.file_tools import resolve_workspace_path

    root = Path("D:/pulseAIrepo/PulseAIRepo/lab/workspace_d")
    got = resolve_workspace_path(str(root), "app/page.tsx")
    assert got == root / "app" / "page.tsx"
