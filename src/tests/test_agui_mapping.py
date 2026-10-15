"""AG-UI edge mapping — golden event sequences (AGUI_A2UI_PLAN.md Phase 1).

Shapes mirror what the engine emits on Bridge v2 (crusorAIProtocol.ts)
and what src/dashboard/mock_agent.py scripts for a turn. No server, no
SDK, no live model required; an optional cross-check validates wire
dicts against the real ag-ui-protocol models when installed.
"""
import pytest

from src.agui.bind import resolve_bind
from src.agui.mapping import V2ToAguiTranslator, interrupt_resume_to_v2

S = {"session_id": "sess-1", "turn_id": "turn-1"}


def types(events):
    return [e["type"] for e in events]


def test_text_turn_sequence():
    t = V2ToAguiTranslator("sess-1")
    out = t.translate_stream([
        {**S, "type": "turn_started"},
        {**S, "type": "token", "text": "Hello "},
        {**S, "type": "token", "text": "world"},
        {**S, "type": "turn_done", "completed": True, "cancelled": False},
    ])
    assert types(out) == [
        "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "RUN_FINISHED",
    ]
    assert out[0]["threadId"] == "sess-1" and out[0]["runId"] == "turn-1"
    assert out[2]["delta"] == "Hello " and out[3]["delta"] == "world"
    assert out[2]["messageId"] == out[3]["messageId"] == out[4]["messageId"]
    assert out[5]["outcome"] == {"type": "success"}


def test_reasoning_closes_before_finish():
    t = V2ToAguiTranslator("sess-1")
    out = t.translate_stream([
        {**S, "type": "turn_started"},
        {**S, "type": "reasoning", "text": "checking both files"},
        {**S, "type": "token", "text": "Found it."},
        {**S, "type": "turn_done", "completed": True, "cancelled": False},
    ])
    assert types(out) == [
        "RUN_STARTED", "REASONING_START", "REASONING_MESSAGE_START",
        "REASONING_MESSAGE_CONTENT", "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT", "REASONING_MESSAGE_END", "REASONING_END",
        "TEXT_MESSAGE_END", "RUN_FINISHED",
    ]


def test_tool_turn_sequence():
    t = V2ToAguiTranslator("sess-1")
    out = t.translate_stream([
        {**S, "type": "turn_started"},
        {**S, "type": "tool_call_start", "tool_id": "tc1", "name": "run_terminal",
         "arguments": {"command": "pytest -q"}},
        {**S, "type": "tool_call_end", "tool_id": "tc1", "status": "passed",
         "result": "2434 passed"},
        {**S, "type": "turn_done", "completed": True, "cancelled": False},
    ])
    assert types(out) == [
        "RUN_STARTED", "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END",
        "TOOL_CALL_RESULT", "RUN_FINISHED",
    ]
    assert out[1]["toolCallName"] == "run_terminal"
    assert "pytest -q" in out[2]["delta"]
    assert out[4]["toolCallId"] == "tc1" and out[4]["content"] == "2434 passed"
    assert out[4]["role"] == "tool"


def test_plan_and_todo_become_state_delta():
    t = V2ToAguiTranslator("sess-1")
    out = t.translate_stream([
        {**S, "type": "plan_updated", "steps": [{"description": "inspect", "status": "pending"}]},
        {**S, "type": "todo_updated", "todos": [{"id": "1", "content": "fix", "status": "pending"}],
         "revision": 3},
    ])
    assert types(out) == ["STATE_DELTA", "STATE_DELTA"]
    assert out[0]["delta"][0]["path"] == "/plan"
    assert out[1]["delta"][0]["path"] == "/todos"


def test_safety_request_is_interrupt_and_resumes():
    t = V2ToAguiTranslator("sess-1")
    out = t.translate_stream([
        {**S, "type": "turn_started"},
        {**S, "type": "safety_request", "tool_id": "tc9", "name": "run_terminal",
         "arguments": {"command": "rm -rf build"}, "warning": "destructive"},
    ])
    assert types(out) == ["RUN_STARTED", "RUN_FINISHED"]
    outcome = out[1]["outcome"]
    assert outcome["type"] == "interrupt"
    intr = outcome["interrupts"][0]
    assert intr["reason"] == "safety_request" and intr["id"] == "tc9"
    assert intr["message"] == "destructive"
    assert interrupt_resume_to_v2("safety_request", "tc9", {"approved": True}) == {
        "type": "safety_reply", "tool_id": "tc9",
        "approved": True, "always_allow": False,
    }


def test_clarify_request_is_interrupt_and_resumes():
    t = V2ToAguiTranslator("sess-1")
    out = t.translate_stream([
        {**S, "type": "clarify_request", "request_id": "q1",
         "title": "Which file?", "questions": [{"qid": "q", "question": "Which file?"}]},
    ])
    assert types(out) == ["RUN_FINISHED"]
    intr = out[0]["outcome"]["interrupts"][0]
    assert intr["reason"] == "clarify_request" and intr["id"] == "q1"
    assert interrupt_resume_to_v2(
        "clarify_request", "q1", {"answers": {"q": "server.py"}}
    ) == {
        "type": "clarify_reply", "request_id": "q1",
        "answers": {"q": "server.py"}, "timed_out": False,
    }


def test_failed_turn_is_run_error():
    t = V2ToAguiTranslator("sess-1")
    out = t.translate_stream([
        {**S, "type": "turn_started"},
        {**S, "type": "turn_failed", "error": "model unreachable", "completed": False},
    ])
    assert types(out) == ["RUN_STARTED", "RUN_ERROR"]
    assert out[1]["message"] == "model unreachable"


def test_desktop_only_events_are_not_mapped():
    t = V2ToAguiTranslator("sess-1")
    assert t.translate({**S, "type": "host_tool_request", "request_id": "r1"}) == []
    assert t.translate({**S, "type": "checkpoint_event"}) == []
    assert t.unmapped == ["host_tool_request", "checkpoint_event"]


def test_verification_and_telemetry_are_custom_events():
    t = V2ToAguiTranslator("sess-1")
    out = t.translate_stream([
        {**S, "type": "verification_updated", "status": "passed", "evidence": {"a": 1}},
        {**S, "type": "telemetry", "input": 10, "output": 5},
    ])
    assert [e["name"] for e in out] == [
        "crusor.verification_updated", "crusor.telemetry",
    ]


def test_bind_guard_defaults_and_refusals():
    assert resolve_bind({}).host == "127.0.0.1"
    assert resolve_bind({}).port == 8123
    assert resolve_bind({"CRUSORAI_HOST": "localhost"}).ok
    assert not resolve_bind({"CRUSORAI_HOST": "0.0.0.0"}).ok
    assert resolve_bind(
        {"CRUSORAI_HOST": "0.0.0.0", "CRUSORAI_DASHBOARD_TOKEN": "x"}
    ).ok
    assert not resolve_bind({"CRUSORAI_PORT": "abc"}).ok


def test_wire_events_validate_against_real_sdk_when_available():
    core = pytest.importorskip("ag_ui.core")
    t = V2ToAguiTranslator("sess-1")
    out = t.translate_stream([
        {**S, "type": "turn_started"},
        {**S, "type": "token", "text": "hi"},
        {**S, "type": "tool_call_start", "tool_id": "tc1", "name": "read_file",
         "arguments": {"path": "src/server.py"}},
        {**S, "type": "tool_call_end", "tool_id": "tc1", "status": "passed",
         "result": "ok"},
        {**S, "type": "safety_request", "tool_id": "tc2", "name": "edit_file",
         "warning": "needs approval"},
        {**S, "type": "turn_done", "completed": True, "cancelled": False},
    ])
    by_type = {
        "RUN_STARTED": core.RunStartedEvent,
        "TEXT_MESSAGE_START": core.TextMessageStartEvent,
        "TEXT_MESSAGE_CONTENT": core.TextMessageContentEvent,
        "TEXT_MESSAGE_END": core.TextMessageEndEvent,
        "TOOL_CALL_START": core.ToolCallStartEvent,
        "TOOL_CALL_ARGS": core.ToolCallArgsEvent,
        "TOOL_CALL_END": core.ToolCallEndEvent,
        "TOOL_CALL_RESULT": core.ToolCallResultEvent,
        "RUN_FINISHED": core.RunFinishedEvent,
    }
    for event in out:
        model = by_type.get(event["type"])
        assert model is not None, event
        model.model_validate(event)
