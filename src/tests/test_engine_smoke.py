"""Pure (no-LLM) smoke tests for the PulseAI context engine and safety guard.

These run without provider keys, without the embedder model download, and
without network access — the engine deliberately falls back to heuristic
paths. Safe for CI on every PR.
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from src.context.context_engine import ContextEngine, TaskType
from src.context.safety_guard import SafetyGuard


def _engine() -> ContextEngine:
    return ContextEngine(max_tokens=4000, llm=None, memory_manager=None)


def _state() -> dict:
    return {
        "current_task": "fix the bug in the parser",
        "messages": [HumanMessage(content="please fix")],
        "workspace": ".",
        "plan": [{"id": 1, "description": "reproduce", "status": "pending"}],
        "steps_completed": [],
        "failed_steps": ["boom"],
        "recovery_mode": True,
        "recovery_attempts": 1,
        "replan_count": 0,
    }


def test_build_ai_messages_snapshots_layers_sent():
    eng = _engine()
    out = eng.build_ai_messages(_state(), SystemMessage(content="SYS"))
    assert out, "no messages built"
    assert eng._last_layers_sent, "attribution snapshot empty"
    assert "task" in eng._last_layers_sent
    assert "recovery" in eng._last_layers_sent


def test_task_classifier_is_reused_across_builds():
    eng = _engine()
    eng.build_ai_messages(_state(), SystemMessage(content="SYS"))
    first = eng._classifier
    assert first is not None, "classifier never initialized"
    eng.build_ai_messages(_state(), SystemMessage(content="SYS"))
    assert eng._classifier is first, "classifier was re-created (embedding re-warm)"


def test_layer_relevance_is_per_instance():
    eng = _engine()
    eng.LAYER_RELEVANCE["repo_map"][TaskType.CHAT] = 0.123
    fresh = _engine()
    assert fresh.LAYER_RELEVANCE["repo_map"][TaskType.CHAT] != 0.123, (
        "LAYER_RELEVANCE mutation leaked across engine instances"
    )


def test_record_feedback_attributes_layers_actually_sent(tmp_path):
    eng = _engine()
    eng._feedback_path = str(tmp_path / "feedback.json")
    eng.build_ai_messages(_state(), SystemMessage(content="SYS"))
    eng.record_feedback(True, task="fix the bug in the parser")
    record = json.loads(open(eng._feedback_path).read())[-1]
    assert record["layers_used"], "feedback recorded no layers"
    assert "task" in record["layers_used"]
    assert None not in record["layers_used"]


def test_every_built_layer_infers_a_known_name():
    """Regression guard: if a layer builder's header text is ever edited,
    _infer_layer_name must not silently degrade to 'unknown' (0.5 relevance
    plus broken feedback attribution)."""
    eng = _engine()
    eng.build_ai_messages(_state(), SystemMessage(content="SYS"))
    raw = eng._build_context_layers(_state(), TaskType.DEBUG)
    unknown = [m.content.splitlines()[0] for m in raw if eng._infer_layer_name(m) == "unknown"]
    assert not unknown, f"layers with unmapped headers: {unknown}"


def test_safety_guard_is_workspace_scoped():
    guard_tmp = SafetyGuard("/tmp")
    assert str(guard_tmp.workspace) == "/tmp"
    ok, _warning = guard_tmp.check_tool_call(
        "run_terminal", {"command": "echo hello"}
    )
    assert ok, "harmless command should not require approval"
    risky, _warning = guard_tmp.check_tool_call(
        "run_terminal", {"command": "rm -rf /important"}
    )
    assert not risky, "dangerous command was not flagged"
