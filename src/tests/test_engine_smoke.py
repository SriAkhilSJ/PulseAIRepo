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


def test_built_layers_carry_identity_tags():
    """Every layer the engine builds must carry its name in
    response_metadata — scoring/dedup/feedback must not depend on
    string-sniffing header text (one '=' short used to silently degrade
    attribution to 'unknown')."""
    eng = _engine()
    raw = eng._build_context_layers(_state(), TaskType.DEBUG)
    assert raw, "no layers built"
    untagged = [
        m.content.splitlines()[0] for m in raw if "layer" not in m.response_metadata
    ]
    assert not untagged, f"layers missing identity tags: {untagged}"
    for m in raw:
        assert eng._infer_layer_name(m) == m.response_metadata["layer"]


def test_infer_layer_name_prefers_tag_over_header():
    eng = _engine()
    msg = SystemMessage(
        content="== TOTALLY DIFFERENT HEADER ===",
        response_metadata={"layer": "tone"},
    )
    assert eng._infer_layer_name(msg) == "tone"
    # Fallback chain still works for messages built outside the engine loop.
    assert eng._infer_layer_name(SystemMessage(content="=== TONE: gentle")) == "tone"


def test_compress_layer_preserves_identity_tag():
    eng = _engine()
    big = SystemMessage(
        content="=== CODEBASE STRUCTURE (Repo Map) ===\n" + "src/a.py -> def f\n" * 400,
        response_metadata={"layer": "repo_map"},
    )
    out = eng._compress_layer(big, max_tokens=200)
    assert out is not None
    assert out.response_metadata.get("layer") == "repo_map"
    assert len(out.content) < len(big.content)


def test_layer_tags_are_invisible_to_providers():
    # The whole point of response_metadata: never leaks into API payloads.
    from langchain_core.messages.utils import convert_to_openai_messages
    dumped = convert_to_openai_messages(
        [SystemMessage(content="x", response_metadata={"layer": "task"})]
    )[0]
    assert "layer" not in dumped
    assert "response_metadata" not in dumped


def test_compress_layer_never_drops_a_fittable_layer():
    """Fuzz-proven gap (round 12): the old ≤3-iteration proportional loop
    returned None — layer SILENTLY DROPPED — for ~0.7% of mixed-density
    contents even though a fitting prefix existed. The binary-search
    fallback must make 'unjustified None' impossible."""
    from src.context.token_budget import count_tokens

    eng = _engine()
    suffix = "\n... (truncated) ..."
    LIGHT = "the quick brown fox jumps over the lazy dog " * 20
    CJK = "".join(chr(0x4E00 + (i % 500)) for i in range(400))   # ~1 char/token
    EMOJI = "🙂🚀🔥💡⚙️🧩🎯🛠️" * 50                                 # <1 char/token
    cases = [LIGHT + CJK, CJK + LIGHT, LIGHT + EMOJI + CJK, EMOJI + LIGHT,
             CJK + EMOJI]

    def fit_exists(content, budget):
        lo, hi, found = 0, len(content), False
        while lo <= hi:
            mid = (lo + hi) // 2
            if count_tokens([SystemMessage(content=content[:mid] + suffix)], eng.model) <= budget:
                found = True
                lo = mid + 1
            else:
                hi = mid - 1
        return found

    for content in cases:
        for budget in (50, 100, 200, 500, 1000):
            msg = SystemMessage(content=content, response_metadata={"layer": "x"})
            if count_tokens([msg], eng.model) <= budget:
                continue  # not a compression case
            out = eng._compress_layer(msg, budget)
            if fit_exists(content, budget):
                assert out is not None, (
                    f"fittable layer dropped (budget={budget})")
                assert count_tokens([out], eng.model) <= budget, (
                    f"compressed layer over budget (budget={budget})")
                assert out.response_metadata["layer"] == "x"
            else:
                assert out is None, f"magic compression of the unfittable (budget={budget})"


def test_compress_layer_none_only_when_truly_unfittable():
    eng = _engine()
    # Budget smaller than the suffix alone: None is the ONLY honest answer.
    msg = SystemMessage(content="🙂🚀🔥" * 100, response_metadata={"layer": "x"})
    assert eng._compress_layer(msg, max_tokens=3) is None
