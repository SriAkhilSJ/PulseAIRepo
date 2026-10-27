"""Provider-free contracts for Agent Core's trajectory-level loop guard.

The existing same-call guards catch A/A/A. These contracts pin the missing
A/B/A/B shape while proving that changed edits or outcomes remain productive.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from src.graphs import chat_graph as cg
from src.graphs import progress_helpers as ph


def _sample(tool: str, args: dict, result: str, *, failed: bool = False) -> dict[str, str]:
    return ph.tool_cycle_sample(tool, args, result, failed=failed)


def _ab_samples(repetitions: int) -> list[dict[str, str]]:
    a = _sample(
        "write_file",
        {"path": "app.py", "content": "print('same')"},
        "File written: app.py",
    )
    b = _sample(
        "terminal",
        {"command": "python app.py"},
        "same\nExit code: 0",
    )
    return [item for _ in range(repetitions) for item in (a, b)]


def _config(tmp_path) -> dict:
    return {
        "configurable": {
            "thread_id": "tool-cycle-test",
            "workspace": str(tmp_path),
            "approval_policy": "workspace_session",
        }
    }


def _last_b_state(tmp_path, prior_history: list[dict[str, str]]) -> dict:
    return {
        "messages": [
            AIMessage(content="", tool_calls=[{
                "id": "b-last",
                "name": "terminal",
                "args": {"command": "python app.py"},
            }]),
            ToolMessage(
                content="same\nExit code: 0",
                tool_call_id="b-last",
                name="terminal",
            ),
        ],
        "current_task": "repair app.py and verify it",
        "workspace": str(tmp_path),
        "turn_tool_execution_count": len(prior_history),
        "turn_tool_execution_names": [item["tool"] for item in prior_history],
        "tool_cycle_guard": {
            "history": prior_history,
            "warned_signature": "",
            "hard_stop": False,
            "detail": {},
        },
    }


def test_sample_is_canonical_and_privacy_safe():
    first = _sample("tool", {"b": 2, "a": {"y": 1, "x": 0}}, "secret result")
    second = _sample("tool", {"a": {"x": 0, "y": 1}, "b": 2}, "secret result")

    assert first == second
    assert set(first) == {"tool", "fingerprint"}
    assert len(first["fingerprint"]) == 64
    assert "secret" not in repr(first)


def test_detects_alternating_cycle_at_three_repetitions():
    cycle = ph.detect_tool_cycle(_ab_samples(3))

    assert cycle is not None
    assert cycle["length"] == 2
    assert cycle["repetitions"] == 3
    assert cycle["tools"] == ["write_file", "terminal"]
    assert cycle["hard_stop"] is False


def test_hard_stop_arms_at_five_repetitions():
    cycle = ph.detect_tool_cycle(_ab_samples(5))

    assert cycle is not None
    assert cycle["length"] == 2
    assert cycle["repetitions"] == 5
    assert cycle["hard_stop"] is True


def test_shortest_cycle_wins_for_one_repeated_action():
    repeated = [
        _sample("terminal", {"command": "npm test"}, "failed\nExit code: 1", failed=True)
        for _ in range(5)
    ]

    cycle = ph.detect_tool_cycle(repeated)
    assert cycle is not None
    assert cycle["length"] == 1
    assert cycle["tools"] == ["terminal"]
    assert cycle["hard_stop"] is True


def test_changed_arguments_or_outcomes_are_progress_not_a_loop():
    productive: list[dict[str, str]] = []
    for revision in range(5):
        productive.extend([
            _sample(
                "edit_file",
                {"path": "app.py", "old": str(revision), "new": str(revision + 1)},
                f"Edited revision {revision + 1}",
            ),
            _sample(
                "terminal",
                {"command": "pytest -q"},
                f"{5 + revision} passed, {4 - min(revision, 4)} failed\nExit code: 1",
                failed=True,
            ),
        ])

    assert ph.detect_tool_cycle(productive) is None


def test_history_is_bounded_to_five_cycles_of_five_actions():
    history: list[dict[str, str]] = []
    for index in range(100):
        history = ph.append_tool_cycle_sample(
            history,
            _sample("read_file", {"path": f"{index}.py"}, str(index)),
        )

    assert len(history) == ph.TOOL_CYCLE_HISTORY_LIMIT == 25
    assert history[0]["tool"] == "read_file"


def test_progress_node_soft_warns_and_emits_monitoring_event(monkeypatch, tmp_path):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(cg.event_bus, "emit", lambda kind, payload: events.append((kind, payload)))
    # Five prior samples end in A; processing the final B completes A/B × 3.
    state = _last_b_state(tmp_path, _ab_samples(2) + _ab_samples(1)[:1])

    out = cg.progress_node(state, _config(tmp_path))

    guard = out["tool_cycle_guard"]
    assert guard["hard_stop"] is False
    assert guard["detail"]["length"] == 2
    assert guard["detail"]["repetitions"] == 3
    assert guard["warned_signature"] == guard["detail"]["signature"]
    nudges = [m.content for m in out.get("messages", [])]
    assert len(nudges) == 1
    assert "TRAJECTORY LOOP GUARD" in nudges[0]
    assert "write_file → terminal" in nudges[0]
    status = [payload for kind, payload in events if kind == "context.status"]
    assert status and status[-1]["phase"] == "tool_cycle_guard"
    assert status[-1]["severity"] == "warning"
    assert "args" not in status[-1] and "result" not in status[-1]


def test_progress_node_hard_stops_without_another_model_call(monkeypatch, tmp_path):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(cg.event_bus, "emit", lambda kind, payload: events.append((kind, payload)))
    # Nine prior samples end in A; processing B completes A/B × 5.
    state = _last_b_state(tmp_path, _ab_samples(4) + _ab_samples(1)[:1])

    out = cg.progress_node(state, _config(tmp_path))
    merged = {**state, **out}

    assert out["tool_cycle_guard"]["hard_stop"] is True
    assert cg.after_progress(merged) == "tool_cycle_limit"
    terminal = cg.tool_cycle_limit_node(merged, _config(tmp_path))
    assert terminal["task_status"] == "failed"
    assert terminal["task_completed"] is False
    assert "identical outcomes 5 times" in terminal["messages"][0].content
    assert "workspace and session state are preserved" in terminal["messages"][0].content
    status = [payload for kind, payload in events if kind == "context.status"]
    assert status and status[-1]["severity"] == "error"


def test_turn_reset_lazily_clears_cycle_state_without_changing_reset_contract(tmp_path):
    reset = cg._turn_scoped_resets()
    # Existing acknowledgement/task-manager tests pin this helper's exact key
    # set. Reuse its execution counter as the turn epoch instead of widening
    # that public return shape.
    assert reset["turn_tool_execution_count"] == 0
    assert "tool_cycle_guard" not in reset

    state = _last_b_state(tmp_path, _ab_samples(5))
    state["tool_cycle_guard"].update({
        "warned_signature": "old-turn",
        "hard_stop": True,
        "detail": {"repetitions": 5},
    })
    state["turn_tool_execution_count"] = 0
    out = cg.progress_node(state, _config(tmp_path))

    assert len(out["tool_cycle_guard"]["history"]) == 1
    assert out["tool_cycle_guard"]["hard_stop"] is False
    assert out["tool_cycle_guard"]["detail"] == {}
    assert "tool_cycle_guard" in cg.AgentState.__annotations__
