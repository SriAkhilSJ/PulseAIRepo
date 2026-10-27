"""Finalize writes NO prose on success — hermes parity.

Owner reports, in order: (1) a bare "hi" turn came back stapled to
"## ✅ Finished: hi / What would you like to do next?" — fake product voice on
chat turns; (2) after the stamp was gated to work runs, a directory-listing
turn closed with "### ✅ Finished: hi" — the stamp leaked a STALE task name
AND hard-coded tail text ("hardcoded text at last", 2026-09-04 screenshots).
Hermes appends nothing after the model's answer: the streamed words ARE the
turn. Everything the stamp carried rides structure now — verdict in
task_completed/task_status, per-step outcomes in tool cards, suggestions in
the `suggestions` event. Only DEVIATIONS keep words: a budget hit or
unrecovered trailing failure says so (hermes explainer); unverified rides
`task_status="unverified"` with no hardcoded transcript injection.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def _no_memory(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setattr(chat_graph, "memory_manager", None)


def _chat_state() -> dict:
    from langchain_core.messages import AIMessage, HumanMessage

    return {
        "messages": [HumanMessage("hi"), AIMessage("Hi! How can I help you today?")],
        "current_task": "hi",
        "steps_completed": [],
        "failed_steps": [],
        "plan": [],
    }


def test_pure_chat_turn_stamps_nothing(_no_memory):
    from src.graphs.chat_graph import finalize_node

    out = finalize_node(dict(_chat_state()), {"configurable": {}})
    # No finalize message at all: the model's own words are the transcript.
    assert out["messages"] == []
    # The verdict is still structural, not lost.
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


def test_successful_work_run_stamps_nothing(_no_memory):
    """hermes parity (owner, 2026-09-04): even a run that DID work gets NO
    finalize prose on success — no "Finished" stamp, no "What I did"
    inventory, no sign-off tail. The model's streamed answer is the entire
    transcript; the verdict rides out structurally."""
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["steps_completed"] = ["Wrote file: app/page.tsx"]
    out = finalize_node(dict(state), {"configurable": {}})
    assert out["messages"] == []
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


def test_finalize_report_counts_filtered_informational_execution(_no_memory, monkeypatch):
    """A real informational receipt counts even though it intentionally does
    not become a success/failure progress entry in execution_trace."""
    from src.graphs import chat_graph
    from src.runtime.step_tracker import StepTracker

    captured = {}

    class _Tracker:
        def finalize_report(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        StepTracker,
        "get_tracker",
        classmethod(lambda cls, session_id="default", workspace_root=None: _Tracker()),
    )
    state = _chat_state()
    state.update({
        "current_task": "Check Android tooling without modifying files.",
        "execution_trace": [],
        "turn_tool_execution_count": 1,
    })

    chat_graph.finalize_node(state, {"configurable": {"thread_id": "count-info"}})

    assert captured["receipts"]["tool_execution_count"] == 1


def test_work_run_never_carries_the_signoff_tail(_no_memory):
    """The "--- / *Need any tweaks? Just let me know!*" tail is dead. No
    finalize message may contain invented sign-off voice, on any outcome."""
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["steps_completed"] = ["Wrote file: app/page.tsx"]
    out = finalize_node(dict(state), {"configurable": {}})
    for m in out["messages"]:
        assert "Need any tweaks" not in m.content
        assert "What would you like to do next" not in m.content


def test_failed_run_keeps_the_incomplete_stamp(_no_memory):
    """Only an UNRECOVERED failure (still the trailing tool batch) stamps
    'Ended incomplete' - hermes: tool errors are observations; recovered
    history never fails a turn (see test_recovered_tool_failures_...)."""
    from langchain_core.messages import AIMessage, ToolMessage
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["messages"] = state["messages"] + [
        AIMessage(content="running the check..."),
        ToolMessage(
            content="Error: terminal verification crashed (exit 1)",
            tool_call_id="t1", name="run_terminal",
        ),
    ]
    state["failed_steps"] = ["Terminal verification crashed"]
    out = finalize_node(dict(state), {"configurable": {}})
    text = out["messages"][0].content
    assert "Ended incomplete" in text
    assert "\u2705 Finished" not in text
    assert "Need any tweaks" not in text, "deviation notes stay bare - no sign-off tail"
    assert out["task_completed"] is False


def test_recovered_tool_failures_never_stamp_incomplete(_no_memory):
    """Field 2026-09-05 ('Ended incomplete: verify test2 folder'): the two
    failed steps were long recovered (mis-typed path retried OK, bad CLI
    flag replaced) - the run must complete with NO stamp; outcomes live in
    the tool cards."""
    from langchain_core.messages import AIMessage, ToolMessage
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["current_task"] = "verify the test2 folder"
    state["messages"] = [
        AIMessage(content="working..."),
        ToolMessage(content="\u274c read_file: no such file", tool_call_id="t1", name="read_file"),
        AIMessage(content="retrying"),
        ToolMessage(content="\u2705 Read file: app/globals.css", tool_call_id="t2", name="read_file"),
        AIMessage(content="All checks pass - here is the summary."),
    ]
    state["steps_completed"] = ["Read file: app/globals.css"]
    state["failed_steps"] = [
        "Command failed: read_file test2_ws_retest/[README.md](http://README.md)",
        "Command failed: npx next dev --host 0.0.0.0",
    ]
    out = finalize_node(dict(state), {"configurable": {}})
    assert out["messages"] == [], "no stamp on a recovered run"
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


def test_deviation_header_uses_latest_user_message_not_stale_task(_no_memory):
    """Owner leak (2026-09-05): a file-listing turn printed 'Ended incomplete:
    hi' — the deviation header read current_task, stale from the session's
    first prompt. The LAST user message in the transcript is the honest
    label."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["messages"] = [
        HumanMessage("hi"),
        state["messages"][-1],  # stale assistant turn from the "hi" exchange
        HumanMessage("list the folders and files and present it in a file tree"),
        AIMessage(content="listing..."),
        ToolMessage(
            content="Error: run_terminal timed out after 300s",
            tool_call_id="t9", name="run_terminal",
        ),
    ]
    state["current_task"] = "hi"  # stale, must be outranked
    state["steps_completed"] = []
    state["failed_steps"] = ["run_terminal timed out after 300s"]
    out = finalize_node(dict(state), {"configurable": {}})
    text = out["messages"][0].content
    assert "Ended incomplete: list the folders and files and present it in a file tree"[:60] in text
    assert "incomplete: hi" not in text


def test_failure_bullets_are_one_tight_line(_no_memory):
    """Owner: 'needs some discipline' — failure bullets used to carry the
    full command AND the tool-output tail (duplicating the tool card in the
    transcript). One bounded line each now."""
    from langchain_core.messages import AIMessage, ToolMessage
    from src.graphs.chat_graph import finalize_node

    state = _chat_state()
    state["messages"] = state["messages"] + [
        AIMessage(content="running tree..."),
        ToolMessage(
            content="Error: tree not recognized", tool_call_id="t2", name="run_terminal",
        ),
    ]
    state["steps_completed"] = ["Ran command successfully: tree"]
    state["failed_steps"] = [
        "Command failed: powershell -NoProfile -Command \"Get-ChildItem -Path 'D:\\x' -Recurse\"\n"
        "Actual tool output:\n"
        + ("x" * 500)
    ]
    out = finalize_node(dict(state), {"configurable": {}})
    text = out["messages"][0].content
    bullet = [line for line in text.splitlines() if line.startswith("- ")][0]
    assert len(bullet) <= 165, f"bullet too long ({len(bullet)}): {bullet[:80]}..."
    assert "Actual tool output" not in text


def _install_then_promise_state() -> dict:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    return {
        "messages": [
            HumanMessage("Create a Flutter app called flutterdemo"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "install_toolchain",
                        "args": {"sdk": "flutter"},
                        "id": "c1",
                    }
                ],
            ),
            ToolMessage(
                content=(
                    "Flutter SDK installed and verified "
                    "(Flutter 3.47.7, channel stable)."
                ),
                tool_call_id="c1",
            ),
            AIMessage(content="Flutter 3.47.7 is installed. Creating the project now:"),
        ],
        "current_task": "Create a Flutter app called flutterdemo",
        "steps_completed": ["Install Flutter toolchain"],
        "failed_steps": [],
        "plan": [],
        "nudged_at_msg_count": 4,
    }


def test_nudged_but_never_acted_is_not_completed(_no_memory):
    """Field 2026-10-19: the SDK install succeeded, the model announced
    'Creating the project now:' and kept answering text-only until the
    nudge budget ran out. The verdict must not stamp that completed."""
    from src.graphs.chat_graph import finalize_node

    out = finalize_node(_install_then_promise_state(), {"configurable": {}})
    assert out["task_completed"] is False
    assert out["task_status"] == "failed"


def test_acting_after_the_nudge_still_completes(_no_memory):
    """The marker only fails turns where NO work followed the last nudge;
    a model that acts and then summarizes stays completed."""
    from langchain_core.messages import AIMessage, ToolMessage

    from src.graphs.chat_graph import finalize_node

    state = _install_then_promise_state()
    state["messages"] += [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_terminal",
                    "args": {"command": "flutter create flutterdemo"},
                    "id": "c2",
                }
            ],
        ),
        ToolMessage(content="Creating project flutterdemo... All done!", tool_call_id="c2"),
        AIMessage(content="Created flutterdemo and verified it runs."),
    ]
    out = finalize_node(state, {"configurable": {}})
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"
