"""P3 — Hermes/OpenClaude alignment: context-engine parity tests.

Behavior contracts (no count/byte snapshots):

* the concrete engine IS the pluggable ContextEngine ABC (it was ported
  as dead code; P3 wires it),
* the engine owns the compaction decision from the provider's ACTUAL
  usage (Hermes threshold_percent=0.75 of the real window),
* usage pressure tightens the history budget ONCE per episode and
  re-arms only after usage relaxes (anti-thrash),
* compress() is the Hermes-parity entry: head/tail protected,
  AI(tool_calls)/ToolMessage pairs never split, dict protocol round-trips,
* cache-break detection (OpenClaude promptCacheBreakDetection): a
  REGRESSION of the stable prefix (>5% and >~2000 tokens below the
  session peak) is an event; tail growth and small wobbles are not,
* memory layers sanitize untrusted content before it reaches the prompt
  (Hermes sanitize_memory_context),
* get_status() is the unified telemetry surface.

Runs provider-free: no API key, no tokens, no network.
"""

import pytest

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.context.context_engine import ContextEngine
from src.context.engine import ContextEngine as BaseContextEngine


def _engine(**kw) -> ContextEngine:
    kw.setdefault("max_tokens", 8_000)
    kw.setdefault("llm", None)
    kw.setdefault("memory_manager", None)
    return ContextEngine(**kw)


def _windowed_engine(window: int) -> ContextEngine:
    """Engine with a known real window (no discovery chain, no network)."""
    eng = _engine()
    eng._apply_window(window, "test")
    return eng


def _state(task: str = "fix the bug in the parser", n_history: int = 1) -> dict:
    return {
        "current_task": task,
        "messages": [HumanMessage(content="please fix")] * n_history,
        "workspace": ".",
        "plan": [],
        "steps_completed": [],
        "failed_steps": [],
        "recovery_mode": False,
        "recovery_attempts": 0,
        "replan_count": 0,
    }


def _tool_history(rounds: int, chars: int = 2_000) -> list:
    msgs: list = [HumanMessage(content="do the work")]
    for i in range(rounds):
        msgs.append(AIMessage(
            content=f"step {i}",
            tool_calls=[{
                "name": "run_terminal",
                "args": {"command": f"cmd-{i}"},
                "id": f"call_{i}",
            }],
        ))
        msgs.append(ToolMessage(
            content=f"output {i} " + "x" * chars,
            tool_call_id=f"call_{i}",
        ))
    return msgs


def _assert_pairing_ok(messages: list) -> None:
    """Every ToolMessage must be answered by a preceding AIMessage with a
    matching tool_call id (the P4 pairing invariant)."""
    pending: set = set()
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                tcid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tcid:
                    pending.add(tcid)
        elif isinstance(m, ToolMessage):
            assert m.tool_call_id in pending, (
                f"orphan ToolMessage {m.tool_call_id!r} — tool pair was split"
            )
            pending.discard(m.tool_call_id)


# =========================================================
# ABC wiring
# =========================================================

def test_concrete_engine_is_the_abc():
    eng = _engine()
    assert isinstance(eng, BaseContextEngine), (
        "the concrete ContextEngine must implement the pluggable ABC "
        "(P3: it was ported as dead code)"
    )
    assert eng.name == "layered"


def test_abc_abstract_methods_are_callable():
    eng = _windowed_engine(32_768)
    eng.update_from_response({"prompt_tokens": 1_000, "completion_tokens": 10})
    assert eng.last_prompt_tokens == 1_000
    assert eng.should_compress(100) is False
    fire, reason = eng.should_compress_info(100)
    assert fire is False and reason is None
    assert eng.compress([]) == []
    eng.on_turn_complete([], usage={"prompt_tokens": 2_000})
    assert eng.last_prompt_tokens == 2_000


def test_on_session_reset_clears_p3_state():
    eng = _windowed_engine(131_072)
    eng.update_from_response({"prompt_tokens": 120_000})
    eng._apply_usage_pressure(40_000)
    assert eng._usage_pressure_active is True
    eng.on_session_reset()
    assert eng.last_prompt_tokens == 0
    assert eng.compression_count == 0
    assert eng._usage_pressure_active is False
    assert eng._cache_break_receipt_emitted is False


def test_update_model_applies_window_verbatim():
    eng = _engine()
    eng.update_model("some-model", 65_536)
    assert eng.context_window == 65_536
    assert eng.context_window_source == "update-model"
    assert eng.threshold_tokens == int(65_536 * 0.75)
    assert eng.max_tokens <= 65_536


def test_get_status_is_the_unified_surface():
    eng = _windowed_engine(32_768)
    eng.update_from_response({"prompt_tokens": 16_000, "completion_tokens": 200})
    status = eng.get_status()
    for key in (
        "name", "model", "max_tokens", "context_window",
        "context_window_source", "threshold_tokens", "threshold_percent",
        "usage_percent", "compression_count",
        "last_prompt_tokens", "usage_pressure_active", "volatile_tail",
        "compaction", "prompt_cache",
    ):
        assert key in status, f"get_status missing {key}"
    assert status["context_window"] == 32_768
    assert status["last_prompt_tokens"] == 16_000
    assert abs(status["usage_percent"] - 49.0) < 1.0
    assert "prunes" in status["compaction"]
    assert "hit_rate" in status["prompt_cache"]


# =========================================================
# Actual-usage-driven compaction decision (Hermes parity)
# =========================================================

def test_update_from_response_tracks_actual_usage():
    eng = _windowed_engine(32_768)
    assert eng.last_prompt_tokens == 0
    assert eng.threshold_tokens == int(32_768 * 0.75)
    eng.update_from_response({
        "prompt_tokens": 25_000,
        "completion_tokens": 300,
        "total_tokens": 25_300,
    })
    assert eng.last_prompt_tokens == 25_000
    assert eng.last_completion_tokens == 300
    assert eng.last_total_tokens == 25_300
    # zero/absent fields must not clobber known usage
    eng.update_from_response({"prompt_tokens": 0})
    assert eng.last_prompt_tokens == 25_000
    eng.update_from_response(None)  # type: ignore[arg-type]
    assert eng.last_prompt_tokens == 25_000


def test_should_compress_threshold_semantics():
    eng = _windowed_engine(32_768)  # threshold = 24_576
    assert eng.should_compress() is False, "no usage yet -> nothing to decide"
    eng.update_from_response({"prompt_tokens": 20_000})
    assert eng.should_compress() is False
    assert eng.should_compress(30_000) is True, "explicit prompt_tokens wins"
    eng.update_from_response({"prompt_tokens": 24_576})
    assert eng.should_compress() is True, "AT the threshold fires"
    assert eng.should_compress(24_575) is False, "just under does not"
    fire, reason = eng.should_compress_info()
    assert fire is True and "24,576" in reason


def test_should_compress_without_window_is_false():
    eng = _engine()  # explicit max_tokens -> context_window is None
    eng.update_from_response({"prompt_tokens": 10**9})
    assert eng.should_compress() is False, (
        "no known real window -> the engine must not guess"
    )


def test_usage_pressure_tightens_history_budget_once():
    eng = _windowed_engine(131_072)  # threshold = 98_304
    base = 40_000
    assert eng._apply_usage_pressure(base) == base, "no usage -> no pressure"
    eng.update_from_response({"prompt_tokens": 100_000})
    first = eng._apply_usage_pressure(base)
    assert first < base, "crossing the threshold must tighten the budget"
    assert eng._usage_pressure_active is True
    assert eng.compression_count == 1
    second = eng._apply_usage_pressure(base)
    assert second == first, "pressure must not stack within one episode"
    assert eng.compression_count == 1, "one tightening = one counter bump"


def test_usage_pressure_rearms_after_relaxation():
    eng = _windowed_engine(131_072)  # 60% = 78_643
    eng.update_from_response({"prompt_tokens": 100_000})
    assert eng._apply_usage_pressure(40_000) < 40_000
    eng.update_from_response({"prompt_tokens": 50_000})
    assert eng._usage_pressure_active is False, (
        "relaxation below 60% of the window re-arms the flag"
    )
    assert eng._apply_usage_pressure(40_000) == 40_000
    # a NEW crossing fires again (new episode)
    eng.update_from_response({"prompt_tokens": 110_000})
    assert eng._apply_usage_pressure(40_000) < 40_000


def test_usage_pressure_survives_full_build():
    """Integration: crossing the threshold must shrink what
    build_ai_messages ACTUALLY sends (the per-turn path, not the helper)."""
    from src.context.token_budget import count_tokens

    eng = _windowed_engine(131_072)
    # The sandbox's PROVIDER_SAFE_LIMIT (6000) is a provider-side guard,
    # not part of the pressure semantics — size the budget to the real
    # window so the lean-tail floor (10k) is reachable.
    eng.max_tokens = 120_000
    eng.context_budget = int(eng.max_tokens * 0.35)
    eng.history_budget = eng.max_tokens - eng.context_budget
    # Plain human/ai exchanges: big enough to exceed BOTH budgets, and
    # outside the tool summarizer's reach so the ONLY variable is the
    # pressure-tightened history budget.
    history: list = []
    for i in range(150):
        history.append(HumanMessage(content=f"question {i} " + "q" * 4_000))
        history.append(AIMessage(content=f"answer {i} " + "a" * 4_000))

    # Baseline build: usage well under the threshold -> full history budget.
    eng.update_from_response({"prompt_tokens": 10_000})
    state_free = _state()
    state_free["messages"] = list(history)
    out_free = eng.build_ai_messages(state_free, SystemMessage(content="SYS"))

    # Pressured build: the provider says the last prompt was 100k of 131k.
    eng.update_from_response({"prompt_tokens": 100_000, "completion_tokens": 50})
    state_press = _state()
    state_press["messages"] = list(history)
    out_press = eng.build_ai_messages(state_press, SystemMessage(content="SYS"))

    t_free = count_tokens(out_free, eng.model)
    t_press = count_tokens(out_press, eng.model)
    assert t_press < t_free, (
        f"usage pressure did not shrink the sent request ({t_press} >= {t_free})"
    )
    _assert_pairing_ok(out_free)
    _assert_pairing_ok(out_press)


# =========================================================
# compress() — Hermes-parity entry
# =========================================================

def test_compress_never_splits_tool_pairs():
    eng = _windowed_engine(32_768)
    history = _tool_history(24, chars=3_000)
    from src.context.token_budget import count_tokens
    before = count_tokens(history, eng.model)

    result = eng.compress(history, current_tokens=before)
    assert len(result) > 0
    assert count_tokens(result, eng.model) < before, "nothing was compressed"
    _assert_pairing_ok(result)
    assert eng.compression_count >= 1


def test_compress_protects_the_newest_exchange():
    eng = _windowed_engine(32_768)
    history = _tool_history(20, chars=3_000)
    needle = "output 19 "
    result = eng.compress(history, current_tokens=10**6)
    tail = "".join(
        m.content for m in result[-6:] if isinstance(m.content, str)
    )
    assert needle in tail, (
        "the lean tail must keep the newest tool round verbatim"
    )


def test_compress_dict_protocol_roundtrip():
    eng = _windowed_engine(32_768)
    dicts = [{"type": "human", "content": "go"}]
    for i in range(20):
        dicts.append({"type": "ai", "content": f"step {i}"})
        dicts.append({"type": "human", "content": f"result {i} " + "y" * 3_000})
    result = eng.compress(dicts)
    assert result, "dict input produced empty output"
    assert all(isinstance(m, dict) for m in result), "dict in -> dict out"
    assert any("y" * 300 in m.get("content", "") for m in result[-6:]), (
        "tail should survive verbatim in dict mode"
    )


# =========================================================
# Cache-break detection (OpenClaude promptCacheBreakDetection)
# =========================================================

def _audit_turn(audit, persona: str, tail_chars: int) -> dict:
    msgs = [
        SystemMessage(content=persona),
        SystemMessage(content="L" * 4_000, response_metadata={"layer": "repo_map"}),
    ]
    msgs += [HumanMessage(content="t" + "z" * tail_chars)]
    return audit.record(msgs)


def test_cache_break_fires_on_prefix_regression():
    from src.context.prompt_cache_audit import CachePrefixAudit
    audit = CachePrefixAudit()
    big_persona = "P" * 20_000
    rec1 = _audit_turn(audit, big_persona, 500)
    assert rec1["stable_chars"] is None  # first turn: nothing to compare
    rec2 = _audit_turn(audit, big_persona, 600)  # tail growth only
    assert rec2["cache_break"] is False
    peak = rec2["stable_chars"]
    assert peak >= 24_000
    rec3 = _audit_turn(audit, "p" * 200, 600)  # persona rewritten: prefix regression
    assert rec3["cache_break"] is True
    assert rec3["breaker"] == "persona"
    assert rec3["cache_break_dropped_chars"] >= 24_000 - 200
    stats = audit.stats()
    assert stats["cache_breaks"] == 1
    assert stats["last_cache_break"]["breaker"] == "persona"


def test_cache_break_not_on_tail_growth():
    from src.context.prompt_cache_audit import CachePrefixAudit
    audit = CachePrefixAudit()
    persona = "P" * 20_000
    _audit_turn(audit, persona, 100)
    rec = _audit_turn(audit, persona, 20_000)  # same prefix, big tail
    assert rec["cache_break"] is False
    assert audit.stats()["cache_breaks"] == 0


def test_cache_break_small_drop_is_noise():
    from src.context.prompt_cache_audit import CachePrefixAudit
    audit = CachePrefixAudit()
    persona = "P" * 20_000
    _audit_turn(audit, persona, 100)
    # drop the persona by 1_000 chars: below the 2000-token noise floor
    rec = _audit_turn(audit, "P" * 19_000, 100)
    assert rec["cache_break"] is False, "sub-noise wobble is not a break"
    assert audit.stats()["cache_breaks"] == 0


def test_engine_emits_cache_break_receipt_once():
    """Integration: two builds whose stable prefix regresses must produce
    EXACTLY ONE runtime.cache_break receipt (latched per session)."""
    from src.dashboard.event_bus import event_bus

    eng = _windowed_engine(32_768)
    eng.thread_id = "cache-break-test"

    def _build(persona: str):
        state = _state()
        state["messages"] = [HumanMessage(content="task " + "q" * 3_000)]
        return eng.build_ai_messages(state, SystemMessage(content=persona))

    def _drain(q):
        events = []
        while True:
            try:
                events.append(q.get_nowait())
            except Exception:
                return events

    # turn 1: big stable prefix
    _build("PERSONA-" + "A" * 30_000)
    # drain any history the subscription replays
    q = event_bus.subscribe(thread_id="cache-break-test")
    _drain(q)

    # turn 2: same prefix (no break expected)
    _build("PERSONA-" + "A" * 30_000)
    # turn 3: persona rewritten -> prefix regression
    _build("personB-" + "B" * 30_000)

    events = _drain(q)
    event_bus.unsubscribe(q)

    breaks = [e for e in events if e["type"] == "runtime.cache_break"]
    assert len(breaks) == 1, (
        f"expected exactly one runtime.cache_break receipt, got {len(breaks)}"
    )
    assert breaks[0]["payload"]["thread_id"] == "cache-break-test"
    assert breaks[0]["payload"]["breaker"] == "persona"
    assert eng._cache_break_receipt_emitted is True
    # a fourth broken turn must NOT re-emit (latched)
    q2 = event_bus.subscribe(thread_id="cache-break-test")
    _drain(q2)
    _build("personC-" + "C" * 30_000)
    again = [e for e in _drain(q2) if e["type"] == "runtime.cache_break"]
    event_bus.unsubscribe(q2)
    assert again == [], "cache-break receipt must be latched once per session"


# =========================================================
# Memory-layer sanitization (Hermes sanitize_memory_context)
# =========================================================

class _StubMemoryManager:
    SECRET = "sk-paritytest1234567890abcd"

    def retrieve_relevant_memories(self, query, top_k=2):
        return [{
            "text": (
                f"previously solved this with key {self.SECRET} and "
                + "context " * 500  # > 6k chars: exercises the cap too
            )
        }]

    def retrieve_tool_memories(self, query, top_k=2):
        return [{
            "tool": "run_terminal",
            "summary": f"ran deploy with {self.SECRET} attached",
        }]


def test_memory_layers_are_sanitized_before_prompt():
    eng = _engine()
    eng._allow_embedding_compute = True  # enable the semantic path
    mem = _StubMemoryManager()
    eng.memory_manager = mem

    lt = eng._long_term_memory_layer({"current_task": "fix login"})
    assert lt is not None
    assert mem.SECRET not in lt.content, "raw secret leaked into long-term memory layer"
    assert "previously solved this with key" in lt.content, (
        "redaction must keep the context, not drop the memory"
    )
    assert "..." in lt.content, "secret must be abbreviated, not removed silently"
    assert len(lt.content) < 8_000, "memory context must stay within its cap"

    tm = eng._tool_memory_layer({"current_task": "fix login"})
    assert tm is not None
    assert mem.SECRET not in tm.content, "raw secret leaked into tool-memory layer"


def test_reflection_layer_is_sanitized_before_prompt(monkeypatch, tmp_path):
    from src.context import reflection_engine as refl

    class _FakeReflection:
        def get_recent_lessons(self, n=2):
            return ["last time it helped to use TOKEN=sk-paritytest1234567890abcd"]

    monkeypatch.setattr(refl, "ReflectionEngine", lambda: _FakeReflection())
    eng = _engine()
    layer = eng._reflection_layer({"current_task": "anything"})
    assert layer is not None
    assert "sk-paritytest1234567890abcd" not in layer.content
