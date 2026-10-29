"""Verdict-honesty pins — audit 2026-10-12.

Four defects were found by running the suite against the shipped code. Each
one had the same shape: a rule the runtime STATES (in a docstring, a comment,
or a sibling test) was not actually enforced, and the only thing missing was
an assertion that could fail. These are those assertions.

1. `_looks_like_execution_task` matched markers as SUBSTRINGS, so "test"
   matched inside "test2" and read-only verification turns were stamped
   incomplete by finalize.
2. `no_work_done` fired on "no mutation tool ran", which is what every
   read-only turn looks like; it must fire only on a pure monologue.
3. The finalize console line and the returned `task_status` could disagree.
4. The plan-complete wrap lap (ONE closing summary call) could be routed back
   into `finish_gate` because the no-tool Hard Gate sat above it, and a UI
   task asking for a screenshot could pass with no screenshot receipt.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import pytest


@pytest.fixture()
def _no_memory(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setattr(chat_graph, "memory_manager", None)


# ---------------------------------------------------------------------------
# 1. Word-boundary task classification
# ---------------------------------------------------------------------------

def test_execution_classifier_is_word_boundary_not_substring():
    from src.graphs.gates import _looks_like_execution_task

    # The audit's failing field case: "test2" is a FOLDER NAME, not a verb.
    # (A hyphenated "test-2" still reads as the verb — "test" there sits on a
    # real word boundary, and separating that from "run test -2" is not
    # lexically possible. The field bug was the glued digit.)
    assert _looks_like_execution_task("verify the test2 folder") is False
    assert _looks_like_execution_task("read the address from the config file") is False
    # ...while the real verbs and their inflections still classify.
    assert _looks_like_execution_task("build app and test it") is True
    assert _looks_like_execution_task("run the tests") is True
    assert _looks_like_execution_task("adding a settings page") is True
    assert _looks_like_execution_task("write a README") is True
    assert _looks_like_execution_task("make a landing page") is True
    assert _looks_like_execution_task("Please fix the parser") is True
    assert _looks_like_execution_task("") is False


def test_rewrite_all_no_longer_reads_as_write_a():
    """`"write a" in task` matched inside "re"write a"ll" — a second substring
    trap in the same marker list. Phrase markers now carry real boundaries."""
    from src.graphs.gates import _looks_like_execution_task

    assert _looks_like_execution_task("rewrite all the docs") is False


# ---------------------------------------------------------------------------
# 2 + 3. Finalize verdicts: read-only work completes, monologue fails, and the
#        log says exactly what the verdict says.
# ---------------------------------------------------------------------------

def _finalize(state: dict):
    from src.graphs.chat_graph import finalize_node

    return finalize_node(dict(state), {"configurable": {}})


def test_readonly_verification_turn_is_not_stamped_incomplete(_no_memory):
    """Field pin (test2_ws_retest): the run read the folder, succeeded, and
    finalize still returned task_completed=False because "test" ⊂ "test2"."""
    state = {
        "messages": [
            HumanMessage(content="verify the test2 folder"),
            AIMessage(content="", tool_calls=[
                {"name": "read_file", "args": {"path": "test2/app.css"}, "id": "t1"},
            ]),
            ToolMessage(content="✅ Read file: test2/app.css", tool_call_id="t1", name="read_file"),
            AIMessage(content="test2 looks correct — globals.css is present."),
        ],
        "current_task": "verify the test2 folder",
        "steps_completed": ["Read file: test2/app.css"],
        "failed_steps": [],
        "plan": [],
    }
    out = _finalize(state)
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"
    assert out["messages"] == [], "a completed run stamps nothing"


def test_pure_monologue_on_an_execution_task_still_fails(_no_memory):
    """The check's original purpose must survive the fix: a model that talked
    and never called a single tool did not do the work."""
    state = {
        "messages": [
            HumanMessage(content="build a landing page with a hero section"),
            AIMessage(content="I'll start by planning the structure, then build it."),
        ],
        "current_task": "build a landing page with a hero section",
        "steps_completed": [],
        "failed_steps": [],
        "plan": [],
    }
    out = _finalize(state)
    assert out["task_completed"] is False
    assert out["task_status"] == "failed"


def test_recovered_tool_failures_are_never_an_incomplete_verdict(_no_memory):
    """Hermes law: tool errors are observations. A failure that was retried
    successfully must not fail the turn."""
    state = {
        "messages": [
            HumanMessage(content="clean up the stylesheet"),
            AIMessage(content="", tool_calls=[
                {"name": "read_file", "args": {"path": "nope.css"}, "id": "t1"},
            ]),
            ToolMessage(content="❌ read_file: no such file", tool_call_id="t1", name="read_file"),
            AIMessage(content="", tool_calls=[
                {"name": "read_file", "args": {"path": "app/globals.css"}, "id": "t2"},
            ]),
            ToolMessage(content="✅ Read file: app/globals.css", tool_call_id="t2", name="read_file"),
            AIMessage(content="All checks pass."),
        ],
        "current_task": "clean up the stylesheet",
        "steps_completed": ["Read file: app/globals.css"],
        "failed_steps": ["Command failed: npx next dev --host 0.0.0.0"],
        "plan": [],
    }
    out = _finalize(state)
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


def test_finalize_log_line_agrees_with_the_returned_verdict(_no_memory, capsys):
    """Audit 2026-10-12: `[turn] finalize done: completed` was printed while
    the function returned task_completed=False. One verdict, one voice."""
    monologue = {
        "messages": [HumanMessage(content="build the thing"), AIMessage(content="sure!")],
        "current_task": "build the thing",
        "steps_completed": [],
        "failed_steps": [],
        "plan": [],
    }
    out = _finalize(monologue)
    printed = capsys.readouterr().out
    assert out["task_status"] == "failed"
    assert "[turn] finalize done: failed" in printed, (
        "the console line must name the verdict the caller receives — it read "
        f"'completed' while returning {out['task_status']!r}({out['task_completed']})"
    )


# ---------------------------------------------------------------------------
# 4a. The plan-complete wrap lap is terminal
# ---------------------------------------------------------------------------

def _router_state(**extra) -> dict:
    state = {
        "messages": [AIMessage(content="Summary of what was done.")],
        "current_task": "build the app and test it",
        "iteration_used": 3,
        "finish_nudges": 0,
        "verify_nudges": 0,
        "grace_done": 0,
        "workspace": "/nonexistent-ws",
    }
    state.update(extra)
    return state


def test_wrap_lap_finalizes_even_under_the_no_tool_hard_gate():
    """The Hard Gate ("execution task, no mutation tools ran") used to sit
    above the wrap check, so the guaranteed closing lap could be answered
    with another 'go do work' nudge. The wrap lap owns the verdict."""
    from src.graphs.gates import should_continue

    state = _router_state(wrap_summary=1)
    assert should_continue(state) == "finalize"


def test_wrap_lap_still_dispatches_pending_tool_calls():
    """A wrap lap that DID emit tool calls must have them executed (hermes
    IterationBudget law) — the terminal wrap rule applies to text-only laps."""
    from src.graphs.gates import should_continue

    state = _router_state(wrap_summary=1)
    state["messages"] = [
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "a.py"}, "id": "c1"}])
    ]
    assert should_continue(state) == "tools"


# ---------------------------------------------------------------------------
# 4b. A screenshot ask requires a screenshot receipt
# ---------------------------------------------------------------------------

def _ui_receipt_state(task: str, extra: list) -> dict:
    calls = AIMessage(content="", tool_calls=[
        {"id": "t", "name": "typecheck_workspace", "args": {}},
        {"id": "n", "name": "browser_navigate", "args": {"url": "http://localhost"}},
        {"id": "s", "name": "browser_snapshot", "args": {}},
    ])
    return {
        "current_task": task,
        "messages": [
            calls,
            ToolMessage(name="typecheck_workspace",
                        content="✅ typecheck_workspace: tsc --noEmit passed with 0 errors.",
                        tool_call_id="t"),
            ToolMessage(name="browser_navigate", content="Navigated to http://localhost",
                        tool_call_id="n"),
            ToolMessage(name="browser_snapshot", content='{"title":"App","text":"Hello"}',
                        tool_call_id="s"),
        ] + extra,
    }


def test_ui_task_without_screenshot_ask_can_pass_on_a_snapshot():
    from src.graphs.gates import _verification_ran_and_passed

    assert _verification_ran_and_passed(_ui_receipt_state("build the dashboard page", [])) is True


def test_ui_task_that_asks_for_a_screenshot_requires_the_screenshot_receipt():
    from src.graphs.gates import _verification_ran_and_passed

    state = _ui_receipt_state("build a React component and take a screenshot", [])
    assert _verification_ran_and_passed(state) is False, (
        "the requested visual proof is the receipt — a DOM snapshot cannot "
        "stand in for the screenshot the user asked for"
    )

    state["messages"] = state["messages"] + [
        ToolMessage(name="browser_screenshot",
                    content="✅ Screenshot saved: screenshots/proof.png. VISUAL QUALITY PASSED",
                    tool_call_id="p"),
    ]
    assert _verification_ran_and_passed(state) is True


def test_composite_ui_verification_satisfies_the_screenshot_ask():
    from src.graphs.gates import _verification_ran_and_passed

    state = {
        "current_task": "build a React component and take a screenshot proof",
        "messages": [
            ToolMessage(name="verify_ui_workspace", content="✅ UI VERIFICATION PASSED",
                        tool_call_id="v"),
        ],
    }
    assert _verification_ran_and_passed(state) is True, (
        "verify_ui_workspace typechecks + navigates + snapshots + screenshots "
        "in one call; it must satisfy the composite contract"
    )


# ---------------------------------------------------------------------------
# 5. Terminal-created deliverables are verifiable deliverables
# (field 2026-10-19 run 2: `flutter create` in the terminal, verification
# FAILED, model chattered, turn stamped completed — _wrote_code_files was
# False because no write_file call ever happened.)
# ---------------------------------------------------------------------------

def _terminal_created_app_state(tmp_path, verify_results: list[str]) -> dict:
    (tmp_path / "flutterdemo").mkdir(exist_ok=True)
    messages = [
        HumanMessage("Create a Flutter app called flutterdemo"),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "run_terminal",
                "args": {"command": "flutter create flutterdemo"},
                "id": "c1",
            }],
        ),
        ToolMessage(
            content="Creating project flutterdemo... All done! (93 files)",
            tool_call_id="c1",
            name="run_terminal",
        ),
    ]
    for i, result in enumerate(verify_results):
        cid = f"v{i}"
        messages.append(AIMessage(
            content="",
            tool_calls=[{
                "name": "verify_ui_workspace",
                "args": {"command": "flutter run -d web-server", "url": "http://localhost:8137"},
                "id": cid,
            }],
        ))
        messages.append(ToolMessage(content=result, tool_call_id=cid, name="verify_ui_workspace"))
    messages.append(AIMessage(
        content="The probe gave up before the first web build finished. "
                "Let me check whether the port now serves."
    ))
    return {
        "messages": messages,
        "current_task": "Create a Flutter app called flutterdemo",
        "workspace": str(tmp_path),
        "steps_completed": ["Ran command: flutter create flutterdemo"],
        "failed_steps": [],
        "plan": [],
    }


_FAILED_VERIFY = (
    "❌ UI VERIFICATION FAILED: server never became ready:\n"
    "Status: RUNNING\nProcess ID: 04cd7805"
)


def test_terminal_created_app_with_failed_verification_is_not_completed(_no_memory, tmp_path):
    from src.graphs.chat_graph import finalize_node

    state = _terminal_created_app_state(tmp_path, [_FAILED_VERIFY])
    out = finalize_node(state, {"configurable": {}})
    assert out["task_completed"] is False
    assert out["task_status"] == "unverified"


def test_terminal_created_app_passing_verification_later_still_completes(_no_memory, tmp_path):
    from src.graphs.chat_graph import finalize_node

    state = _terminal_created_app_state(
        tmp_path, [_FAILED_VERIFY, "✅ UI VERIFICATION PASSED\npage rendered"]
    )
    out = finalize_node(state, {"configurable": {}})
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


def test_verify_gate_sees_terminal_created_app(tmp_path):
    from src.graphs.gates import _verify_unsatisfied, should_continue

    state = _terminal_created_app_state(tmp_path, [_FAILED_VERIFY])
    state.update({"finish_nudges": 0, "verify_nudges": 0, "iteration_used": 0})
    assert _verify_unsatisfied(state) is True
    assert should_continue(state) == "finish_gate"


# ---------------------------------------------------------------------------
# 5b. Hard gate (founder 2026-10-20, go 2_hard): verification that NEVER
# ran gates exactly like verification that failed. Run 3 ended unverified
# with zero `flutter analyze`/`test` — under the old bar a never-ran
# terminal-created app could close silently; now it is nudged (bounded),
# and any bounded escape ends stamped unverified, never completed.
# ---------------------------------------------------------------------------

def test_terminal_created_app_never_verified_is_not_completed(_no_memory, tmp_path):
    from src.graphs.chat_graph import finalize_node

    state = _terminal_created_app_state(tmp_path, [])
    out = finalize_node(state, {"configurable": {}})
    assert out["task_completed"] is False
    assert out["task_status"] == "unverified"


def test_verify_gate_blocks_terminal_created_app_that_never_verified(tmp_path):
    from src.graphs.gates import _verify_unsatisfied, finish_gate_node, should_continue

    state = _terminal_created_app_state(tmp_path, [])
    state.update({"finish_nudges": 0, "verify_nudges": 0, "iteration_used": 0})
    assert _verify_unsatisfied(state) is True
    assert should_continue(state) == "finish_gate"
    out = finish_gate_node(state)
    assert out["verify_nudges"] == 1
    assert "verif" in out["messages"][0].content.lower()


def test_verify_gate_bounded_escape_still_finalizes_unverified(tmp_path):
    """Refusal is bounded: once the verify-nudge budget is spent the router
    lets the turn end — but the verdict stays unverified (the founder is
    surfaced the truth, not a silent completed)."""
    from src.graphs.gates import _verify_unsatisfied, should_continue

    state = _terminal_created_app_state(tmp_path, [])
    state.update({
        # Every bounded budget spent: finish (terminal production is not
        # a _WORK_TOOLS call), verify, and stall-continuation (the
        # fixture's closing line announces a next step).
        "finish_nudges": 2, "verify_nudges": 2, "iteration_used": 0,
        "stall_continuations": 2,
    })
    assert _verify_unsatisfied(state) is False
    assert should_continue(state) == "finalize"


def test_terminal_named_check_receipts_register_static_proof(tmp_path):
    """Field 2026-10-21 (build 47234e16): the desktop shell is bound as
    `terminal` (hermes parity rename), but the evidence ledger only
    recognized the legacy `run_terminal` name — a full granttest run of
    flutter analyze + flutter test + flutter build registered ZERO
    verification receipts and ended unverified. Terminal-named check
    results now earn static proof exactly like the alias; the UI
    render bar is untouched (static alone still cannot pass a UI app).
    """
    from src.graphs.gates import _verification_receipt_status

    def receipts(content: str, command: str) -> dict:
        state = _terminal_created_app_state(tmp_path, [])
        # Replace the create call's result name with the desktop's real
        # shell tool name and append the check call.
        from langchain_core.messages import AIMessage, ToolMessage
        state["messages"] = [
            AIMessage(content="", tool_calls=[{
                "name": "terminal", "args": {"command": command}, "id": "k1",
            }]),
            ToolMessage(content=content, tool_call_id="k1", name="terminal"),
            AIMessage(content="done"),
        ]
        return _verification_receipt_status(state)

    ok = receipts("No issues found!\nExit code: 0", "flutter analyze")
    assert ok["static"] is True, "flutter analyze via `terminal` must register"
    assert ok["passed"] is False, "static proof alone must not pass a UI app"
    assert "navigate" in ok["missing"]

    bad = receipts("error: Target of URI doesn't exist\nExit code: 1",
                   "flutter analyze")
    assert bad["static"] is False, "a failed analyze proves nothing"


def test_empty_reply_laps_converge_to_finalize(tmp_path):
    """Field 2026-10-21 (build ca4a5b0d): after `flutter create`, the
    model answered EMPTY replies in a loop — 8+ paid calls, no tools.
    Two budget gears never meshed: the router stopped routing on the
    verify gate at its budget but re-entered through the finish gate,
    whose budget the node's verify branch never spends; and each
    nudge SystemMessage reset the no-progress streak. Simulate the
    field lap-for-lap: the router must reach finalize in a bounded
    number of laps, after which the turn ends unverified (previous
    pin), never spins."""
    from langchain_core.messages import AIMessage

    from src.graphs.gates import finish_gate_node, should_continue

    state = _terminal_created_app_state(tmp_path, [])
    state.update({
        "finish_nudges": 0, "verify_nudges": 0, "iteration_used": 0,
        "stall_continuations": 2,
    })
    laps = 0
    while should_continue(state) == "finish_gate" and laps < 12:
        laps += 1
        out = finish_gate_node(state)
        for key in ("finish_nudges", "verify_nudges", "stall_continuations"):
            if key in out:
                state[key] = out[key]
        state["messages"] = list(state["messages"]) + list(
            out.get("messages") or []
        ) + [AIMessage(content="")]
    assert should_continue(state) == "finalize", (
        f"empty-reply laps must converge (still routing after {laps} laps)"
    )
    assert laps <= 6, f"convergence must be cheap, took {laps} laps"
    assert state["verify_nudges"] <= 2, "verify budget must actually bind"


def test_pdf_artifact_without_verification_still_completes(_no_memory, tmp_path):
    """Non-code artifacts carry no runtime to verify: a produced
    report.pdf must not be dragged into the unverified verdict."""
    from src.graphs.chat_graph import finalize_node

    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4\ncontent")
    state = {
        "messages": [
            HumanMessage("Create the final research report as report.pdf"),
            AIMessage(
                content="",
                tool_calls=[{"name": "execute_code", "args": {"code": "..."}, "id": "c1"}],
            ),
            ToolMessage(content="✅ wrote report.pdf", tool_call_id="c1", name="execute_code"),
            AIMessage(content="Done — report.pdf is ready."),
        ],
        "current_task": "Create the final research report as report.pdf",
        "workspace": str(tmp_path),
        "steps_completed": ["Generated report.pdf"],
        "failed_steps": [],
        "plan": [],
    }
    out = finalize_node(state, {"configurable": {}})
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


# ---------------------------------------------------------------------------
# 6. Run-3 shapes (field 2026-10-19): the one-shot verifier failed at the
# server stage, the agent then proved the app MANUALLY in a live browser.
# Two attribution gaps stamped that genuinely-verified turn "unverified":
# the failed receipt zeroed the static domain its own call had passed,
# and .dart was not a recognized code extension at all.
# ---------------------------------------------------------------------------

def _skyapp_run_state(tmp_path, verify_text: str) -> dict:
    (tmp_path / "skyapp").mkdir()
    return {
        "messages": [
            HumanMessage("Create a Flutter app called skyapp"),
            AIMessage(
                content="",
                tool_calls=[{"name": "write_file", "args": {"path": "skyapp/lib/main.dart"}, "id": "w1"}],
            ),
            ToolMessage(content="File written: skyapp/lib/main.dart", tool_call_id="w1", name="write_file"),
            AIMessage(
                content="",
                tool_calls=[{"name": "verify_ui_workspace", "args": {"command": "flutter run -d chrome", "url": "http://127.0.0.1:8090"}, "id": "v1"}],
            ),
            ToolMessage(content=verify_text, tool_call_id="v1", name="verify_ui_workspace"),
            AIMessage(
                content="",
                tool_calls=[{"name": "browser_navigate", "args": {"url": "http://127.0.0.1:8090"}, "id": "b1"}],
            ),
            ToolMessage(content="Navigated to http://127.0.0.1:8090 successfully.", tool_call_id="b1", name="browser_navigate"),
            AIMessage(
                content="",
                tool_calls=[{"name": "browser_snapshot", "args": {}, "id": "b2"}],
            ),
            ToolMessage(
                content='{"title":"Sky App","text":"You have pushed the button this many times:"}',
                tool_call_id="b2",
                name="browser_snapshot",
            ),
            AIMessage(
                content="",
                tool_calls=[{"name": "browser_screenshot", "args": {"name": "skyapp_live_home"}, "id": "b3"}],
            ),
            ToolMessage(
                content="Screenshot saved to screenshots/skyapp_live_home.png",
                tool_call_id="b3",
                name="browser_screenshot",
            ),
            AIMessage(content="Verified in the live browser — the app renders."),
        ],
        "current_task": "Create a Flutter app called skyapp",
        "workspace": str(tmp_path),
        "steps_completed": ["Wrote file: skyapp/lib/main.dart"],
        "failed_steps": [],
        "plan": [],
    }


_SERVER_STAGE_FAILURE = (
    "❌ UI VERIFICATION FAILED: server never became ready "
    "(waited 300s; the started process was stopped, so nothing is "
    "left listening):\nStatus: COMPLETED"
)


def test_failed_oneshot_plus_manual_browser_proof_completes(_no_memory, tmp_path):
    from src.graphs.chat_graph import finalize_node

    state = _skyapp_run_state(tmp_path, _SERVER_STAGE_FAILURE)
    out = finalize_node(state, {"configurable": {}})
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


def test_static_stage_failure_still_condemns_the_turn(_no_memory, tmp_path):
    from src.graphs.chat_graph import finalize_node
    from src.graphs.gates import _verification_ran_and_passed

    state = _skyapp_run_state(
        tmp_path,
        "❌ UI VERIFICATION FAILED at static source checks:\n3 type errors",
    )
    assert _verification_ran_and_passed(state) is False
    out = finalize_node(state, {"configurable": {}})
    assert out["task_completed"] is False


def test_wrote_code_files_recognizes_native_stacks():
    from src.graphs.gates import _wrote_code_files

    for step in (
        "Wrote file: lib/main.dart",
        "Wrote file: app/src/main/java/com/example/Main.kt",
        "Edited file: ios/Runner/AppDelegate.swift",
        "Wrote file: src/main.rs",
    ):
        assert _wrote_code_files({"steps_completed": [step]}) is True, step
    # Docs remain outside the runtime-verify contract.
    assert _wrote_code_files({"steps_completed": ["Wrote file: docs/hero.md"]}) is False


def test_derive_4state_verification_receipt_states():
    from src.graphs.gates import derive_4state_verification_receipt
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    # 1. Non-execution / read-only -> not_applicable
    ro_state = {
        "current_task": "explain this architecture",
        "messages": [HumanMessage(content="explain this architecture")],
        "steps_completed": [],
    }
    r1 = derive_4state_verification_receipt(ro_state)
    assert r1["state"] == "not_applicable"
    assert r1["passed"] is True

    # 2. Execution task with code written but no checks ran -> unverified
    unv_state = {
        "current_task": "build backend api",
        "messages": [
            HumanMessage(content="build backend api"),
            AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "server.py"}, "id": "c1"}]),
            ToolMessage(content="Wrote file: server.py", tool_call_id="c1", name="write_file"),
        ],
        "steps_completed": ["Wrote file: server.py"],
        "marked_edits": ["server.py"],
    }
    r2 = derive_4state_verification_receipt(unv_state)
    assert r2["state"] == "unverified"
    assert r2["passed"] is False
    assert "static" in r2["required"]

    # 3. Execution task with passing terminal checks -> verified
    ver_state = {
        "current_task": "build backend api",
        "messages": [
            HumanMessage(content="build backend api"),
            AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "server.py"}, "id": "c1"}]),
            ToolMessage(content="Wrote file: server.py", tool_call_id="c1", name="write_file"),
            AIMessage(content="", tool_calls=[{"name": "terminal", "args": {"command": "pytest test_api.py"}, "id": "c2"}]),
            ToolMessage(content="exit code: 0\n24 passed in 0.5s", tool_call_id="c2", name="terminal"),
        ],
        "steps_completed": ["Wrote file: server.py", "Ran command: pytest test_api.py"],
        "marked_edits": ["server.py"],
    }
    r3 = derive_4state_verification_receipt(ver_state)
    assert r3["state"] == "verified"
    assert r3["passed"] is True
    assert r3["checks"]["static"] == "passed"


# ---------------------------------------------------------------------------
# GPT-4o-Mini Regression: Completion Gate Evidence-Based Integrity
# ---------------------------------------------------------------------------

def test_gpt_4o_mini_failed_test_blocks_successful_completion(_no_memory, tmp_path):
    """Reproduce the GPT-4o-mini scenario:
    1. The model creates application files.
    2. A mandatory test command exits with code 1.
    3. The model claims the task is complete in text.
    4. CrusorAI MUST refuse to report successful completion while that failure is unresolved.
    5. Once the exact check passes, completion is permitted.
    """
    from src.graphs.chat_graph import finalize_node

    server_file = tmp_path / "backend" / "server.py"
    server_file.parent.mkdir(parents=True, exist_ok=True)
    server_file.write_text("# server code")

    # Step 1-3: Code written, test command exits with code 1, model claims "Task is complete!"
    failing_state = {
        "current_task": "Build full stack task app and run the automated tests to verify",
        "latest_instruction": "Build full stack task app and run the automated tests to verify",
        "workspace": str(tmp_path),
        "messages": [
            HumanMessage(content="Build full stack task app and run the automated tests to verify"),
            AIMessage(
                content="",
                tool_calls=[{"name": "write_file", "args": {"path": "backend/server.py"}, "id": "call_w1"}],
            ),
            ToolMessage(content="File written: backend/server.py", tool_call_id="call_w1", name="write_file"),
            AIMessage(
                content="",
                tool_calls=[{"name": "terminal", "args": {"command": "python -m unittest tests/test_server.py"}, "id": "call_t1"}],
            ),
            ToolMessage(
                content="FAILED (failures=5)\n\nExit code: 1\nsqlite3.OperationalError: no such table: tasks",
                tool_call_id="call_t1",
                name="terminal",
            ),
            AIMessage(content="All deliverables have been created and tests executed. The task is complete!"),
        ],
        "steps_completed": ["Wrote file: backend/server.py"],
        "failed_steps": ["Command failed: python -m unittest tests/test_server.py\nExit code: 1"],
        "marked_edits": ["backend/server.py"],
        "execution_trace": [
            {"tool": "write_file", "args": {"path": "backend/server.py"}, "status": "success", "result": "ok"},
            {
                "tool": "terminal",
                "args": {"command": "python -m unittest tests/test_server.py"},
                "status": "failed",
                "result": "FAILED (failures=5)\n\nExit code: 1",
            },
        ],
    }

    # Step 4: Finalize MUST reject completion
    result = finalize_node(failing_state, {"configurable": {}})
    assert result["task_completed"] is False, "Finalize must refuse completed=True when test failed!"
    assert result["task_status"] in {"unverified", "failed"}, f"Unexpected status: {result['task_status']}"

    # Step 5: Now repair the code and rerun the test to exit code 0
    passing_state = {
        **failing_state,
        "messages": [
            *failing_state["messages"],
            AIMessage(
                content="",
                tool_calls=[{"name": "write_file", "args": {"path": "backend/server.py"}, "id": "call_w2"}],
            ),
            ToolMessage(content="File written: backend/server.py", tool_call_id="call_w2", name="write_file"),
            AIMessage(
                content="",
                tool_calls=[{"name": "terminal", "args": {"command": "python -m unittest tests/test_server.py"}, "id": "call_t2"}],
            ),
            ToolMessage(
                content="Ran 6 tests in 0.045s\n\nOK\n\nExit code: 0",
                tool_call_id="call_t2",
                name="terminal",
            ),
            AIMessage(content="Repaired the database initialization. All 6 tests now pass!"),
        ],
        "steps_completed": [
            "Wrote file: backend/server.py",
            "Ran command: python -m unittest tests/test_server.py",
        ],
        "marked_edits": ["backend/server.py"],
        "execution_trace": [
            *failing_state["execution_trace"],
            {"tool": "write_file", "args": {"path": "backend/server.py"}, "status": "success", "result": "ok"},
            {
                "tool": "terminal",
                "args": {"command": "python -m unittest tests/test_server.py"},
                "status": "success",
                "result": "OK\n\nExit code: 0",
            },
        ],
    }

    result_pass = finalize_node(passing_state, {"configurable": {}})
    assert result_pass["task_completed"] is True, "Finalize must allow completed=True once tests pass!"
    assert result_pass["task_status"] == "completed"


def test_recovery_limit_node_enforces_failure_verdict():
    """Verify recovery_limit_node structurally emits task_completed=False and task_status='failed'."""
    from src.graphs.chat_graph import recovery_limit_node

    state = {
        "failed_steps": ["Command failed: python -m unittest tests/test_server.py\nExit code: 1"],
        "current_task": "Build full stack task app",
        "messages": [],
    }
    config = {"configurable": {"thread_id": "test_thread"}}
    res = recovery_limit_node(state, config)

    assert res["task_completed"] is False, "recovery_limit_node must set task_completed=False"
    assert res["task_status"] == "failed", "recovery_limit_node must set task_status='failed'"
    assert "stopped trying to automatically recover" in res["messages"][0].content


def test_historical_gpt_false_completion_under_recovery_limit(tmp_path):
    """Phase 2 regression pin: Simulate historical GPT-4o-mini false completion.
    
    1. Agent writes files.
    2. Mandatory test fails with exit code 1.
    3. Model claims completion.
    4. Recovery limit is reached.
    5. Finalize MUST enforce task_completed=False and preserve failed verification.
    """
    from src.graphs.chat_graph import finalize_node, recovery_limit_node

    test_file = tmp_path / "backend" / "server.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("print('mock server')")

    state = {
        "current_task": "Build server and test it",
        "workspace": str(tmp_path),
        "messages": [
            HumanMessage(content="Build server and test it"),
            AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "backend/server.py"}, "id": "w1"}]),
            ToolMessage(content="File written: backend/server.py", tool_call_id="w1", name="write_file"),
            AIMessage(content="", tool_calls=[{"name": "terminal", "args": {"command": "python -m unittest"}, "id": "t1"}]),
            ToolMessage(content="FAILED (failures=1)\nExit code: 1", tool_call_id="t1", name="terminal"),
            AIMessage(content="Everything is implemented and tested. Complete!"),
        ],
        "steps_completed": ["Wrote file: backend/server.py"],
        "failed_steps": ["Command failed: python -m unittest\nExit code: 1"],
        "tool_failures": 6,
        "recovery_mode": True,
        "plan": [],
    }
    # Simulate recovery limit node firing
    rec_out = recovery_limit_node(state, {"configurable": {}})
    state.update(rec_out)

    fin_out = finalize_node(state, {"configurable": {}})
    assert fin_out["task_completed"] is False, "Must refuse completion when mandatory test failed"
    assert fin_out["task_status"] == "failed"
    assert fin_out["execution_status"] in ("failed", "recovery_limit")
    assert fin_out["application_verification_status"] == "failed"
    assert fin_out["required_checks_passed"] is False


def test_verified_task_with_obsolete_nudge_completes_successfully(tmp_path):
    """Phase 2 regression pin: A task that genuinely passed verification and deliverables exist
    must not be condemned by an earlier, obsolete finish nudge."""
    from src.graphs.chat_graph import finalize_node

    srv = tmp_path / "server.py"
    srv.write_text("print('ok')")

    state = {
        "current_task": "Build server.py and verify it",
        "latest_instruction": "Build server.py and verify it",
        "workspace": str(tmp_path),
        "nudged_at_msg_count": 2,
        "messages": [
            HumanMessage(content="Build server.py and verify it"),
            AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "server.py"}, "id": "w1"}]),
            ToolMessage(content="File written: server.py", tool_call_id="w1", name="write_file"),
            AIMessage(content="", tool_calls=[{"name": "terminal", "args": {"command": "python -m pytest test.py"}, "id": "t1"}]),
            ToolMessage(content="1 passed in 0.01s\nExit code: 0", tool_call_id="t1", name="terminal"),
            AIMessage(content="Server built and verified."),
        ],
        "steps_completed": ["Wrote file: server.py", "Ran command: python -m pytest test.py"],
        "failed_steps": [],
        "plan": [],
    }

    out = finalize_node(state, {"configurable": {}})
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"
    assert out["execution_status"] == "completed"
    assert out["application_verification_status"] == "verified"
    assert out["required_checks_passed"] is True


def test_dual_status_separation_safety_denial_with_verified_app(tmp_path):
    """Phase 2 regression pin: Separate execution status from verification status.
    
    When an application has passed all tests and deliverables exist on disk,
    but trailing execution ends on a safety policy denial:
      - execution_status = 'ended_with_safety_denial'
      - application_verification_status = 'verified'
      - required_checks_passed = True
      - task_completed = False (because final tool action was an unresolved denial)
    """
    from src.graphs.chat_graph import finalize_node

    srv = tmp_path / "server.py"
    srv.write_text("print('ok')")

    state = {
        "current_task": "Build server and test it",
        "latest_instruction": "Build server and test it",
        "workspace": str(tmp_path),
        "messages": [
            HumanMessage(content="Build server and test it"),
            AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "server.py"}, "id": "w1"}]),
            ToolMessage(content="File written: server.py", tool_call_id="w1", name="write_file"),
            AIMessage(content="", tool_calls=[{"name": "terminal", "args": {"command": "python -m pytest test.py"}, "id": "t1"}]),
            ToolMessage(content="1 passed in 0.01s\nExit code: 0", tool_call_id="t1", name="terminal"),
            AIMessage(content="", tool_calls=[{"name": "terminal", "args": {"command": "cd C:/Users/Administrator && ls"}, "id": "t2"}]),
            ToolMessage(content="Blocked (safety policy): Out-of-bounds path traversal denied. Choose a safe alternative.", tool_call_id="t2", name="terminal"),
        ],
        "steps_completed": ["Wrote file: server.py", "Ran command: python -m pytest test.py"],
        "failed_steps": ["Blocked (safety policy): Out-of-bounds path traversal denied."],
        "plan": [],
    }

    out = finalize_node(state, {"configurable": {}})
    assert out["task_completed"] is False, "Denied trailing action must keep task_completed=False"
    assert out["execution_status"] == "ended_with_safety_denial"
    assert out["application_verification_status"] == "verified"
    assert out["required_checks_passed"] is True

