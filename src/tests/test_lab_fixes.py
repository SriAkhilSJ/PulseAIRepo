

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
    """Non-UI execution: a passing typecheck receipt permits finalize."""
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


def test_verify_gate_ui_typecheck_without_visual_receipts_is_blocked():
    """A compiler receipt alone cannot prove a requested rendered app."""
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
    assert should_continue(state) == "finish_gate"


def test_verify_gate_ui_allows_after_browser():
    """UI completion requires static, navigate, snapshot, and screenshot receipts."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, ToolMessage
    calls = AIMessage(content="x", tool_calls=[
        {"name": "typecheck_workspace", "args": {}, "id": "t", "type": "tool_call"},
        {"name": "browser_navigate", "args": {"url": "http://localhost:3000"}, "id": "n", "type": "tool_call"},
        {"name": "browser_snapshot", "args": {}, "id": "s", "type": "tool_call"},
        {"name": "browser_screenshot", "args": {"name": "proof"}, "id": "p", "type": "tool_call"},
    ])
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        calls,
        ToolMessage(content="✅ typecheck_workspace: tsc --noEmit passed with 0 errors.", tool_call_id="t", name="typecheck_workspace"),
        ToolMessage(content="Navigated to http://localhost:3000", tool_call_id="n", name="browser_navigate"),
        ToolMessage(content='{"url":"http://localhost:3000","title":"Chat App","text":"How Can I Help You?"}', tool_call_id="s", name="browser_snapshot"),
        ToolMessage(content="✅ Screenshot saved: screenshots/proof.png. VISUAL QUALITY PASSED", tool_call_id="p", name="browser_screenshot"),
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


def test_verify_gate_ui_snapshot_alone_cannot_supersede_failed_navigate():
    """A snapshot alone cannot replace fresh navigation/static/screenshot receipts."""
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
    assert should_continue(state) == "finish_gate"


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


def test_progress_conditional_edges_include_finish_gate():
    """D9 crash: after_progress returned "finish_gate" (D7 bypass fix) but
    the progress conditional-edges MAPPING omitted it — KeyError at runtime
    when a plan-complete task hit the unverified finalize path. The function
    test passed while the graph wiring was broken. Pin the compiled wiring."""
    from src.graphs.chat_graph import builder, memory
    # LangGraph stores conditional edges per source node; find the mapping
    # that includes the keys after_progress can return, and require
    # finish_gate to be wired to a real node.
    nodes = set(builder.compile(checkpointer=memory).get_graph().nodes)
    branch = builder.branches.get("progress")
    assert branch is not None, "progress node must have a conditional branch"
    # branch is {func_name: BranchSpec}; merge all specs' ends mappings
    mapping = {}
    for spec in branch.values():
        mapping.update(getattr(spec, "ends", {}) or {})
    for key in ("ai", "replanner", "recovery_limit", "finalize", "pivot", "finish_gate"):
        assert key in mapping, f"progress mapping missing {key}"
        assert mapping[key] in nodes, f"progress mapping target {mapping[key]} is not a node"


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


def test_verify_gate_raw_tsc_error_via_run_terminal_is_failure():
    """D9: the model ran `npx tsc --noEmit` through run_terminal and the
    tool returned raw `error TS2688:` STDOUT — the marker scan (which only
    looked for "❌ typecheck_workspace:") never saw it, so the broken app
    finalized as verified. Raw compiler errors are the same failure class."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "run_terminal", "args": {}, "id": "1", "type": "tool_call"}]),
        ToolMessage(
            content="STDOUT:\nerror TS2688: Cannot find type definition file for 'node'.\n"
                    "The file is in the program because:\n"
                    "  Entry point of type library 'node' specified in compilerOptions",
            tool_call_id="1", name="run_terminal"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: components/ChatLayout.tsx"],
        "current_task": "Build an EaseMize-style chat application from scratch",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finish_gate"


def test_verify_gate_tsc_skip_is_not_evidence():
    """D9: typecheck_workspace returned "ℹ️ typescript is not installed —
    skipped" and that counted as verification. A skipped check proves
    NOTHING — no compiler ran, so no evidence exists."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "typecheck_workspace", "args": {}, "id": "1", "type": "tool_call"}]),
        ToolMessage(
            content="ℹ️ typecheck_workspace: typescript is not installed in this workspace "
                    "(node_modules/typescript missing) — skipped.",
            tool_call_id="1", name="typecheck_workspace"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: app/page.tsx"],
        "current_task": "Build an EaseMize-style chat application from scratch",
        "verify_nudges": 0,
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finish_gate"


def test_finalize_unverified_stamps_warning_not_finished():
    """D9: finalize_node stamped "## ✅ Finished" unconditionally — a
    budget-exhausted run with a failing typecheck closed with a green
    checkmark. Unverified finalize must say so plainly."""
    from src.graphs.chat_graph import finalize_node, should_continue
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="x", tool_calls=[
            {"name": "run_terminal", "args": {}, "id": "1", "type": "tool_call"}]),
        ToolMessage(
            content="STDOUT:\nerror TS2688: Cannot find type definition file for 'node'.",
            tool_call_id="1", name="run_terminal"),
        AIMessage(content="I'm done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Wrote file: components/ChatLayout.tsx"],
        "current_task": "Build an EaseMize-style chat application from scratch",
        "verify_nudges": 0,
        "finish_nudges": 0,
        "failed_steps": [],
        "plan": [],
        "iteration_used": 0,
    }
    # The gate must fire (unverified + execution task)
    assert should_continue(state) == "finish_gate"
    # And if the run somehow finalizes anyway, the message is honest
    out = finalize_node(dict(state), {"configurable": {}})
    final_text = out["messages"][0].content
    assert "## ✅ Finished" not in final_text
    assert "unverified" in final_text
    assert out["task_completed"] is False


def test_grace_call_drops_tool_pairs():
    """D40 lab retest (2026-08-13): a run that spent its whole iteration
    budget died on the FAREWELL call — the grace call binds NO tools but
    the raw history still ends in AIMessage(tool_calls) + ToolMessage,
    and the OpenAI-compat provider 400'd with "Tool messages found but no
    tools provided". The no-tools request must be stripped of tool pairs;
    text-only AIMessages (reasoning) must survive."""
    from src.graphs.chat_graph import _drop_tool_pairs
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    msgs = [
        SystemMessage("preamble"),
        HumanMessage("build it"),
        AIMessage("thinking aloud"),
        AIMessage(content="", tool_calls=[
            {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
        ToolMessage(content="ok", tool_call_id="1", name="write_file"),
        AIMessage("## ✅ Finished"),
    ]
    out = _drop_tool_pairs(msgs)
    assert all(not isinstance(m, ToolMessage) for m in out)
    assert all(not getattr(m, "tool_calls", None) for m in out)
    kinds = [type(m).__name__ for m in out]
    assert "SystemMessage" in kinds and "HumanMessage" in kinds
    assert "thinking aloud" in [m.content for m in out]  # text survives
    assert [m.content for m in out][-1] == "## ✅ Finished"


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


def test_resolve_workspace_path_strips_workspace_leaf_prefix(tmp_path):
    """A workspace-prefixed model path must not double-nest the workspace."""
    from src.tools.file_tools import resolve_workspace_path

    root = (tmp_path / "workspace_d").resolve()
    root.mkdir()
    got = resolve_workspace_path(str(root), "workspace_d/app/page.tsx")
    assert got == root / "app" / "page.tsx"
    assert got.is_relative_to(root)


def test_resolve_workspace_path_plain_relative_unchanged(tmp_path):
    from src.tools.file_tools import resolve_workspace_path

    root = (tmp_path / "workspace_d").resolve()
    root.mkdir()
    got = resolve_workspace_path(str(root), "app/page.tsx")
    assert got == root / "app" / "page.tsx"


# =====================================================================
# TEST-3 E2 FIXES — the empty-deliverable hole (run_terminal counted as
# "work"; a model that ran 13 shadcn-CLI iterations, wrote nothing, and
# declared Finished finalized clean). Now only write/edit/copy count as
# work, copy_file produces a recognizable step, and copy-task nudges name
# the copy operation instead of a generic nudge.
# =====================================================================

def test_finish_gate_terminal_alone_is_not_work():
    """E2: run_terminal/execute_code are NOT deliverable-producing work.
    A run that only ran terminal commands (13 shadcn iterations in E2) and
    wrote no files is an early stop, not completion."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, HumanMessage
    msgs = [
        HumanMessage("Integrate the component"),
        AIMessage("x", tool_calls=[
            {"name": "run_terminal", "args": {"command": "npx shadcn init"}, "id": "1", "type": "tool_call"}]),
        AIMessage("x", tool_calls=[
            {"name": "run_terminal", "args": {"command": "npx shadcn init"}, "id": "2", "type": "tool_call"}]),
        AIMessage("x", tool_calls=[
            {"name": "execute_code", "args": {"code": "1"}, "id": "3", "type": "tool_call"}]),
        AIMessage("## ✅ Finished"),
    ]
    state = {
        "messages": msgs,
        "current_task": "integrate the react component into components/ui",
        "finish_nudges": 0,
    }
    assert should_continue(state) == "finish_gate"


def test_finish_gate_copy_task_nudge_names_copy_file():
    """E2: for a copy/compose task with zero files written, the nudge must
    teach the copy operation (copy_file + the provided source) — a generic
    "do more work" message is exactly what the E2 model ignored."""
    from src.graphs.chat_graph import finish_gate_node
    from langchain_core.messages import AIMessage, HumanMessage
    msgs = [
        HumanMessage(
            "Copy-paste this component to /components/ui folder: hero-futuristic.tsx and demo.tsx"
        ),
        AIMessage("x", tool_calls=[
            {"name": "run_terminal", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage("## ✅ Finished"),
    ]
    state = {
        "messages": msgs,
        "current_task": (
            "Integrate an existing React component. Copy-paste this component to "
            "/components/ui folder: [hero-futuristic.tsx code] and [demo.tsx code]. "
            "Install three, @react-three/drei, @react-three/fiber."
        ),
        "finish_nudges": 0,
    }
    out = finish_gate_node(dict(state))
    content = out["messages"][0].content
    assert "copy_file" in content
    assert out["finish_nudges"] == 1


def test_copy_file_step_counts_as_code_file_work():
    """The verify/finish gates must recognize a successful copy_file as
    real deliverable work (E2's deliverable was exactly 2 copy_file calls
    away). A copy step satisfies the FINISH gate (no empty-deliverable
    bypass), and the VERIFY gate then demands proof — copy is real code
    work, so it must be verified like any write."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage
    msgs = [
        AIMessage("x", tool_calls=[
            {"name": "copy_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage("done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": ["Copied file: src/components/ui/hero-futuristic.tsx"],
        "current_task": "integrate the react component into components/ui",
        "finish_nudges": 0,
        "verify_nudges": 0,
    }
    # write/edit/copy happened -> finish gate won't fire with a generic
    # "no work" nudge; the verify gate fires the typecheck nudge instead.
    assert should_continue(state) == "finish_gate"


def test_copy_file_then_typecheck_finalizes():
    """E2 full path: copy the provided files then typecheck — the run
    finalizes. This is the exact 2-copy call deliverable the resume nudge
    prescribed."""
    from src.graphs.chat_graph import should_continue
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage("x", tool_calls=[
            {"name": "copy_file", "args": {}, "id": "1", "type": "tool_call"}]),
        AIMessage("x", tool_calls=[
            {"name": "copy_file", "args": {}, "id": "2", "type": "tool_call"}]),
        AIMessage("x", tool_calls=[
            {"name": "typecheck_workspace", "args": {}, "id": "3", "type": "tool_call"}]),
        ToolMessage(
            content="✅ typecheck_workspace: tsc --noEmit passed with 0 errors.",
            tool_call_id="3", name="typecheck_workspace"),
        AIMessage("done"),
    ]
    state = {
        "messages": msgs,
        "steps_completed": [
            "Copied file: src/components/ui/hero-futuristic.tsx",
            "Copied file: src/components/ui/demo.tsx",
        ],
        "current_task": "integrate the react component into components/ui",
        "finish_nudges": 0,
        "verify_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_generic_copy_marker_detection():
    from src.graphs.chat_graph import (
        _looks_like_copy_task,
        _deliverable_targets,
    )
    task = (
        "Integrate an existing React component. Copy-paste this component to "
        "/components/ui folder: [hero-futuristic.tsx code] and [demo.tsx code]. "
        "Install three, @react-three/drei, @react-three/fiber."
    )
    assert _looks_like_copy_task(task)
    targets = _deliverable_targets(task)
    assert any("hero-futuristic.tsx" in t for t in targets)
    assert any("demo.tsx" in t for t in targets)


def test_terminal_timeout_env_returns_pivot_message():
    """A platform-neutral sleeping child must hit the foreground timeout."""
    import os
    import shlex
    import subprocess
    import sys
    from src.tools.terminal_tools import run_terminal
    from langchain_core.runnables import RunnableConfig
    cfg = RunnableConfig({"configurable": {"workspace": "."}})
    old = os.environ.get("PULSEAI_TERMINAL_TIMEOUT")
    os.environ["PULSEAI_TERMINAL_TIMEOUT"] = "1"
    argv = [sys.executable, "-c", "import time; time.sleep(60)"]
    command = (
        subprocess.list2cmdline(argv)
        if os.name == "nt"
        else shlex.join(argv)
    )
    try:
        out = run_terminal.invoke({"command": command}, cfg)
    finally:
        if old is None:
            os.environ.pop("PULSEAI_TERMINAL_TIMEOUT", None)
        else:
            os.environ["PULSEAI_TERMINAL_TIMEOUT"] = old
    assert "timed out" in out
    assert "ENVIRONMENT failure" in out
    assert "retry" in out


# =====================================================================
# P1 — prompt-cache plan (hermes prompt_caching.py shape). Pure functions,
# zero LLM calls. DEFAULT OFF: markers only when PULSEAI_PROMPT_CACHE=1 AND
# the provider is allowlisted.
# =====================================================================

def test_cache_plan_is_off_by_default():
    import os
    from langchain_core.messages import SystemMessage
    from src.context.prompt_cache_plan import build_prompt_cache_plan
    old = os.environ.get("PULSEAI_PROMPT_CACHE")
    os.environ.pop("PULSEAI_PROMPT_CACHE", None)
    try:
        msgs = [SystemMessage(content="persona"), SystemMessage(content="layer")]
        out, info = build_prompt_cache_plan(msgs, "openai", "gpt-4.1")
    finally:
        if old is None:
            os.environ.pop("PULSEAI_PROMPT_CACHE", None)
        else:
            os.environ["PULSEAI_PROMPT_CACHE"] = old
    assert out is msgs  # untouched by identity when disabled
    assert info["enabled"] is False


def test_cache_plan_marks_stable_head_when_enabled():
    import os
    from langchain_core.messages import SystemMessage, HumanMessage
    from src.context.prompt_cache_plan import build_prompt_cache_plan
    old = os.environ.get("PULSEAI_PROMPT_CACHE")
    os.environ["PULSEAI_PROMPT_CACHE"] = "1"
    try:
        msgs = [
            SystemMessage(content="persona"),
            SystemMessage(content="repo_map"),
            SystemMessage(content="task"),
            SystemMessage(content="plan"),
            HumanMessage(content="hi"),
        ]
        out, info = build_prompt_cache_plan(msgs, "openai", "gpt-4.1")
    finally:
        if old is None:
            os.environ.pop("PULSEAI_PROMPT_CACHE", None)
        else:
            os.environ["PULSEAI_PROMPT_CACHE"] = old
    assert info["enabled"] is True
    assert info["markers"] >= 1
    assert info["markers"] <= 4
    marked = [m for m in out if (m.additional_kwargs or {}).get("cache_control")]
    assert any(type(m).__name__ == "SystemMessage" for m in marked)
    assert all(type(m).__name__ in ("SystemMessage", "HumanMessage", "AIMessage", "ToolMessage") for m in marked)
    # content preserved verbatim
    assert [m.content for m in out] == [m.content for m in msgs]


def test_cache_plan_custom_provider_requires_opt_in():
    """The custom/base_url route (Sarvam on this box) must NOT be decorated
    unless explicitly verified — an endpoint that rejects unknown fields
    would 4xx the whole turn."""
    import os
    from langchain_core.messages import SystemMessage
    from src.context.prompt_cache_plan import build_prompt_cache_plan
    old_pc = os.environ.get("PULSEAI_PROMPT_CACHE")
    old_c = os.environ.get("PULSEAI_PROMPT_CACHE_CUSTOM")
    os.environ["PULSEAI_PROMPT_CACHE"] = "1"
    os.environ.pop("PULSEAI_PROMPT_CACHE_CUSTOM", None)
    try:
        msgs = [SystemMessage(content="persona")]
        out, info = build_prompt_cache_plan(msgs, "custom", "sarvam-105b-conversations")
    finally:
        if old_pc is None:
            os.environ.pop("PULSEAI_PROMPT_CACHE", None)
        else:
            os.environ["PULSEAI_PROMPT_CACHE"] = old_pc
        if old_c is None:
            os.environ.pop("PULSEAI_PROMPT_CACHE_CUSTOM", None)
        else:
            os.environ["PULSEAI_PROMPT_CACHE_CUSTOM"] = old_c
    assert out is msgs
    assert info["enabled"] is False


def test_cache_plan_never_raises_on_bad_input():
    from src.context.prompt_cache_plan import build_prompt_cache_plan
    out, info = build_prompt_cache_plan(None, "openai")
    assert out is None
    out2, info2 = build_prompt_cache_plan("not-a-list", "openai")
    assert out2 == "not-a-list"


# =====================================================================
# R3-1 — POSIX-on-Windows guard (the R3 retest loop was 25 identical
# POSIX commands against a Windows cmd shell; detect BEFORE spawning).
# =====================================================================

def test_posix_guard_flags_posix_mkdir_tmp():
    """R3's exact loop shape must be refused before spawn."""
    from src.tools.terminal_tools import _posix_violations, run_terminal
    from langchain_core.runnables import RunnableConfig
    import os
    if os.name != "nt":
        return
    cmd = "mkdir -p /tmp/next-scaffold && cd /tmp/next-scaffold && npx create-next-app@latest . --yes"
    violations = _posix_violations(cmd)
    assert violations, "expected POSIX violations for the R3 loop command"
    cfg = RunnableConfig({"configurable": {"workspace": "."}})
    out = run_terminal.invoke({"command": cmd}, cfg)
    assert "do NOT retry" in out.lower() or "do not retry" in out.lower()
    assert "POSIX" in out


def test_posix_guard_flags_which_npx():
    import os
    from src.tools.terminal_tools import _posix_violations
    if os.name != "nt":
        return
    violations = _posix_violations("which npx && npx --version")
    assert any("which" in v for v in violations)


def test_posix_guard_allows_windows_safe_commands():
    from src.tools.terminal_tools import _posix_violations
    safe = [
        "npm install --save three @react-three/drei @react-three/fiber",
        "node --version && npm --version",
        "npx tsc --noEmit",
        r"C:\Program Files\node\node.exe --version",
        "git status",
    ]
    for cmd in safe:
        assert _posix_violations(cmd) == [], f"false positive: {cmd}"


def test_posix_guard_allows_windows_temp_inside_workspace():
    import src.tools.terminal_tools as terminal

    original = terminal._IS_WINDOWS
    terminal._IS_WINDOWS = True
    try:
        cmd = "mkdir temp_app && cd temp_app && npx create-next-app@latest . --typescript --tailwind --yes"
        assert terminal._posix_violations(cmd) == [], "legit Windows scaffold must pass"
        assert terminal._posix_violations("mkdir -p temp_app"), "POSIX -p must still fail"
    finally:
        terminal._IS_WINDOWS = original


def test_posix_guard_non_windows_noop():
    """On POSIX the guard is a no-op — POSIX shell IS the native dialect."""
    import src.tools.terminal_tools as tt
    originally = tt._IS_WINDOWS
    tt._IS_WINDOWS = False
    try:
        assert tt._posix_violations("mkdir -p /tmp/x && which npx") == []
    finally:
        tt._IS_WINDOWS = originally


# ---------------------------------------------------------------------------
# E2-1: named deliverable targets missing on disk (MDX-style tasks)
# ---------------------------------------------------------------------------

def tmpdir_ws():
    import tempfile
    return tempfile.mkdtemp(prefix="e21-")


def test_deliverable_targets_rejects_page_scaffold_text():
    """E2-1 false-positive guard: T3 regression — 'Create a page using
    Next.js App Router' matched the target regex ('Next.js') and could
    fabricate a 'named target' from prose. Without named targets the
    plan-complete shortcut must finalize clean."""
    import tempfile
    from src.graphs.gates import _deliverables_missing_on_disk

    ws = tempfile.mkdtemp()
    state = {
        "messages": [],
        "current_task": "Create a page using Next.js App Router and Tailwind",
        "workspace": ws,
    }
    assert _deliverables_missing_on_disk(state, ws) == []


def test_named_deliverable_missing_on_disk_routes_to_finish_gate():
    """E2-1: task names deliverable files that were never created. The
    verify-gate evidence only proves written code sound — it proves nothing
    about the named file. before finalize, route to finish_gate so the
    E2 copy nudge fires."""
    from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
    from src.graphs.chat_graph import after_progress, should_continue
    msgs = [
        AIMessage("scaffold", tool_calls=[]),
        AIMessage("## ✅ Finished"),
    ]
    state = {
        "messages": msgs,
        "current_task": (
            "Build the MDX docs page. Create src/components/ui/hero.md containing "
            "the intro, and src/components/ui/demo.md containing the demo."
        ),
        "workspace": tmpdir_ws(),
        "plan": [],
        "steps_completed": ["Wrote file: src/components/ui/hero.md"],
        "plan_complete": True,
    }
    assert should_continue(state) == "finish_gate"


def test_named_deliverable_missing_routes_via_after_progress_as_well():
    """E2-1 DOM: the plan-complete shortcut finalizes without consulting
    the verify gate — named deliverable missing on disk must ALSO redirect
    through that path, not only the ai-node exit router."""
    from src.graphs.chat_graph import after_progress, is_plan_complete
    state = {
        "messages": [],
        "current_task": (
            "Build the MDX docs page. Create src/components/ui/hero.md and "
            "src/components/ui/demo.md."
        ),
        "workspace": tmpdir_ws(),
        "plan": [
            {"id": "1", "description": "Write hero.md", "status": "completed"},
            {"id": "2", "description": "Write demo.md", "status": "completed"},
        ],
        "steps_completed": [
            "Wrote file: src/components/ui/hero.md",
            "Wrote file: src/components/ui/demo.md",
        ],
    }
    assert is_plan_complete(state)
    # the shortcut would finalize; the missing named deliverable redirects
    assert after_progress(state) == "finish_gate"


def test_finish_gate_named_deliverable_uses_copy_nudge():
    """E2-1: when the task names its deliverable files and they don't exist
    on disk, finish_gate_node picks the copy/placement nudge — even for a
    non-copy task — so the model is told to produce the named artifact,
    not just 'do more work'."""
    from langchain_core.messages import AIMessage, HumanMessage
    from src.graphs.chat_graph import finish_gate_node
    msgs = [
        HumanMessage(
            "Create src/components/ui/hero.md and src/components/ui/demo.md"
        ),
        AIMessage("## ✅ Finished"),
    ]
    state = {
        "messages": msgs,
        "current_task": (
            "Build the MDX docs page. Create src/components/ui/hero.md containing "
            "the intro, and src/components/ui/demo.md containing the demo."
        ),
        "workspace": tmpdir_ws(),
        "finish_nudges": 0,
    }
    out = finish_gate_node(dict(state))
    content = out["messages"][0].content
    assert "copy_file" in content
    assert out["finish_nudges"] == 1


def test_named_deliverable_exists_on_disk_finalizes():
    """E2-1: the on-disk check must NOT fire once the named deliverable
    actually exists — the copy nudge does not immortalize itself."""
    from langchain_core.messages import AIMessage
    from src.graphs.chat_graph import should_continue
    import os
    ws = tmpdir_ws()
    for f in ("src/components/ui/hero.md", "src/components/ui/demo.md"):
        path = os.path.join(ws, *f.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# hello\n")
    state = {
        "messages": [
            AIMessage(content="x", tool_calls=[
                {"name": "write_file", "args": {}, "id": "1", "type": "tool_call"}]),
            AIMessage("## ✅ Finished"),
        ],
        "current_task": (
            "Build the MDX docs page. Create src/components/ui/hero.md and "
            "src/components/ui/demo.md."
        ),
        "workspace": ws,
        "steps_completed": ["Wrote file: src/components/ui/hero.md"],
    }
    assert should_continue(state) == "finalize"


# ---------------------------------------------------------------------------
# R3 / Test-3 retest regression: "✅ Finished" with zero placed components must
# be structurally impossible for a copy/compose task, even after the generic
# finish-nudge budget is exhausted. The retest (lab-test3-retest, 32s, 0 files)
# escaped because the E2-1 on-disk check was gated by finish_nudges, and the
# candidate scan never looked under src/components/ui/ for a bare filename.
# ---------------------------------------------------------------------------

_RETEST_TASK = (
    "Integrate an existing React component. The sources are in _provided/. "
    "Place _provided/hero-futuristic.tsx and _provided/demo.tsx into "
    "src/components/ui/ byte-for-byte using the copy_file tool "
    "(copy_file src=_provided/hero-futuristic.tsx "
    "dst=src/components/ui/hero-futuristic.tsx, and same for demo.tsx). "
    "Finish only when both files exist on disk at src/components/ui/."
)


def _retest_state(ws, finish_nudges=0, messages=None):
    from langchain_core.messages import AIMessage
    return {
        "messages": messages or [AIMessage("## ✅ Finished")],
        "current_task": _RETEST_TASK,
        "workspace": ws,
        "finish_nudges": finish_nudges,
        "steps_completed": [],
    }


def test_retest_copy_task_blocked_from_finalize_even_after_nudge_budget():
    """R3: a copy task that names its deliverables cannot finalize with zero
    placed files, even when finish_nudges is already at the budget (2). The
    old code returned 'finalize' here, letting the retest escape empty."""
    import tempfile
    from src.graphs.chat_graph import should_continue
    ws = tempfile.mkdtemp(prefix="r3-")
    state = _retest_state(ws, finish_nudges=2)
    assert should_continue(state) == "finish_gate"


def test_retest_copy_task_finalizes_once_components_placed():
    """R3: once both named components exist on disk (under src/components/ui/),
    the on-disk check must clear and the run finalizes — the candidate scan
    must recognize a bare 'demo.tsx' placed under the component dir."""
    import os, tempfile
    from src.graphs.chat_graph import should_continue
    ws = tempfile.mkdtemp(prefix="r3-")
    placed = (
        "src/components/ui/hero-futuristic.tsx",
        "src/components/ui/demo.tsx",
        "_provided/hero-futuristic.tsx",
        "_provided/demo.tsx",
    )
    for f in placed:
        p = os.path.join(ws, *f.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("// component\n")
    state = _retest_state(ws, finish_nudges=2)
    assert should_continue(state) == "finalize"


def test_ask_user_batch_finalizes_turn_hermes_style():
    """Field run 2026-09-05 ("asked question but"): ask_user returned its
    echo to the MODEL, which kept working (asked AND ran a command), then
    the turn died "Ended incomplete". Hermes questions are prose
    turn-enders: the user answers in chat, the next turn proceeds. An
    ask_user-only tool batch must finalize immediately (clean end — no
    steps, no failures, no stamp)."""
    from langchain_core.messages import AIMessage, ToolMessage
    from src.graphs.chat_graph import after_progress

    msgs = [
        AIMessage(content="", tool_calls=[
            {"name": "ask_user",
             "args": {"question": "Which directory?"},
             "id": "1", "type": "tool_call"}]),
        ToolMessage(
            content="? **I need a bit more clarity:** ...",
            tool_call_id="1", name="ask_user"),
    ]
    state = {"messages": msgs, "recovery_mode": False,
             "recovery_attempts": 0, "replan_needed": False,
             "env_failures": 0, "pivot_count": 0}
    assert after_progress(state) == "finalize"


def test_mixed_batch_with_ask_user_does_not_short_circuit():
    """ask_user alongside a real tool in the same batch: the real result
    still routes normally — only a pure-ask batch ends the turn."""
    from langchain_core.messages import AIMessage, ToolMessage
    from src.graphs.chat_graph import after_progress

    msgs = [
        AIMessage(content="", tool_calls=[
            {"name": "ask_user", "args": {"question": "which?"},
             "id": "1", "type": "tool_call"},
            {"name": "run_terminal",
             "args": {"command": "dir"}, "id": "2", "type": "tool_call"}]),
        ToolMessage(content="? ...", tool_call_id="1", name="ask_user"),
        ToolMessage(content="file.txt\nExit code: 0",
                    tool_call_id="2", name="run_terminal"),
    ]
    state = {"messages": msgs, "recovery_mode": False,
             "recovery_attempts": 0, "replan_needed": False,
             "env_failures": 0, "pivot_count": 0}
    assert after_progress(state) != "finalize"
