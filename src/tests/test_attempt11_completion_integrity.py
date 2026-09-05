"""Provider-free regressions from Test-5 Attempt 11."""

import threading

from src.bridge.__main__ import BridgeServer
from src.graphs.chat_graph import AgentTurnResult, finalize_node


def test_bridge_uses_graph_completion_verdict_and_flushes_tool_result(
    monkeypatch, tmp_path
):
    import src.graphs.chat_graph as chat_graph
    from src.dashboard.event_bus import event_bus

    session_id = "attempt11-completion-regression"
    event_bus.clear(session_id)

    def fake_stream_agent(text, **kwargs):
        event_bus.emit("tool.call", {
            "thread_id": session_id,
            "tool_id": "terminal-one",
            "tool_name": "run_terminal",
            "tool_args": {"command": "echo verify"},
        })
        event_bus.emit("tool.result", {
            "thread_id": session_id,
            "tool_id": "terminal-one",
            "tool_name": "run_terminal",
            "status": "error",
            "result": "verification did not run",
        })
        return AgentTurnResult("Ended unverified", completed=False)

    monkeypatch.setattr(chat_graph, "stream_agent", fake_stream_agent)
    server = object.__new__(BridgeServer)
    emitted = []
    server.emit = emitted.append
    server._shutdown = threading.Event()

    server._run_turn(session_id, "build and verify", str(tmp_path))

    kinds = [frame["type"] for frame in emitted]
    assert "tool_call_start" in kinds
    assert "tool_call_end" in kinds
    assert kinds.index("tool_call_end") < kinds.index("turn_done")
    terminal = next(frame for frame in emitted if frame["type"] == "turn_done")
    assert terminal["completed"] is False
    assert terminal["message"] == "Ended unverified"


def test_stream_agent_returns_finalize_message_and_verdict(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage
    import src.context.convention_learner as conventions
    import src.context.self_curation as curation
    import src.graphs.chat_graph as chat_graph

    class FakeGraph:
        def stream(self, initial_state, config=None, stream_mode=None):
            yield {"ai": {"messages": [AIMessage(content="I will inspect next")]}}
            yield {"finalize": {
                "messages": [AIMessage(content="Ended unverified: verification missing")],
                "task_completed": False,
                "task_status": "unverified",
            }}

        def get_state(self, config):
            return SimpleNamespace(values={})

    monkeypatch.setattr(chat_graph, "graph", FakeGraph())
    monkeypatch.setattr(
        conventions.ConventionLearner, "get_conventions_text", lambda self, ws: ""
    )
    monkeypatch.setattr(curation, "maybe_spawn_memory_review", lambda *a, **k: None)

    result = chat_graph.stream_agent(
        "build and verify", thread_id="finalize-result", workspace=str(tmp_path)
    )

    assert isinstance(result, str)
    assert result == "Ended unverified: verification missing"
    assert result.completed is False


def test_finalize_uses_latest_instruction_when_current_task_is_absent(monkeypatch):
    from langchain_core.messages import AIMessage
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setattr(chat_graph, "memory_manager", None)
    state = {
        "messages": [AIMessage(content="I will inspect next")],
        "latest_instruction": "Build and verify a complete website",
        "steps_completed": ["Wrote file: index.html"],
        "failed_steps": [],
        "plan": [],
        "iteration_used": 20,
    }

    update = finalize_node(state, {"configurable": {}})

    assert update["task_completed"] is False
    assert update["task_status"] == "unverified"
    assert "Ended unverified" in update["messages"][0].content


def test_finalize_never_completes_with_unresolved_failed_steps(monkeypatch):
    """UNRECOVERED failure (still the trailing tool batch at finalize) keeps
    the turn incomplete. Recovered failure HISTORY alone must not fail the
    turn — hermes treats tool errors as observations the model iterates past
    (field 2026-09-05: a run with two long-recovered errors was stamped
    'Ended incomplete' while its actual last action was cut mid-flight by
    the old plan-complete shortcut)."""
    from langchain_core.messages import AIMessage, ToolMessage
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setattr(chat_graph, "memory_manager", None)
    state = {
        "messages": [
            AIMessage(content="trying..."),
            ToolMessage(
                content="Error: npm install timed out after 180s",
                tool_call_id="t1", name="run_terminal",
            ),
        ],
        "current_task": "Explain the repository",
        "steps_completed": [],
        "failed_steps": ["Terminal verification crashed"],
        "plan": [],
    }

    update = finalize_node(state, {"configurable": {}})

    assert update["task_completed"] is False
    assert update["task_status"] == "failed"
    assert "Ended incomplete" in update["messages"][0].content
    assert "✅ Finished" not in update["messages"][0].content


def test_finalize_completes_when_failures_were_recovered(monkeypatch):
    """The exact field shape (2026-09-05): failed_steps history carries a
    mis-typed read_file and a bad CLI flag — both retried successfully —
    and the turn must complete WITHOUT the 'Ended incomplete' stamp. The
    per-tool outcomes stay visible in their tool cards."""
    from langchain_core.messages import AIMessage, ToolMessage
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setattr(chat_graph, "memory_manager", None)
    state = {
        "messages": [
            AIMessage(content="working..."),
            ToolMessage(
                content="❌ read_file: no such file",
                tool_call_id="t1", name="read_file",
            ),
            AIMessage(content="retrying with the right path"),
            ToolMessage(
                content="✅ Read file: test2_ws_retest/app/globals.css",
                tool_call_id="t2", name="read_file",
            ),
        ],
        "current_task": "verify the test2 folder",
        "steps_completed": ["Read file: test2_ws_retest/app/globals.css"],
        "failed_steps": [
            "Command failed: read_file test2_ws_retest/[README.md](http://README.md)",
            "Command failed: npx next dev --host 0.0.0.0",
        ],
        "plan": [],
    }

    update = finalize_node(state, {"configurable": {}})

    assert update["task_completed"] is True
    assert update["task_status"] == "completed"
    assert update["messages"] == []


def test_terminal_subprocess_forces_utf8_transport(monkeypatch, tmp_path):
    import src.tools.shadow_checkpoints as checkpoints
    import src.tools.terminal_tools as terminal

    captured = {}

    class FakeProcess:
        pid = 123
        returncode = 0

        def communicate(self, timeout=None):
            return "Unicode output: 3√3 and r⁵\n", ""

    def fake_popen(command, **kwargs):
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(terminal.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(checkpoints, "checkpoint_before_mutation", lambda *a: None)
    monkeypatch.setattr(terminal, "_record_verification_result", lambda *a: None)

    raw = getattr(terminal.run_terminal, "func", terminal.run_terminal)
    result = raw(
        command="echo verify",
        config={"configurable": {"workspace": str(tmp_path), "thread_id": "utf8"}},
    )

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert "3√3" in result
    assert "Exit code: 0" in result
