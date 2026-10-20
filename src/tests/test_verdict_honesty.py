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
    (tmp_path / "flutterdemo").mkdir()
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
