"""
History Shaper contracts (P8 extraction)
========================================
Run: python -m pytest src/tests/test_history_shaper.py -q

Behavior contracts for the extracted history-shaping pipeline
(``src/context/history_shaper.py``) — the summarize / compact / trim /
telemetry unit the layered engine applies to conversation history:

* the pipeline itself (empty passthrough, pairing-safe trim, tool-only
  summarization)
* the ONE-anti-thrash-state contract: per-turn path and ABC compress() share
  a single HistoryCompactor per session
* the kill switch (PULSEAI_COMPACTION=off) still creates no compactor
* getters-not-values: the engine's model/session identity are read live, so
  a mid-session reconfigure or per-build thread routing cannot go stale

Provider-free, zero LLM spend.
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.context.history_shaper import HistoryShaper, _ZERO_STATS


class _FakeSummarizer:
    def __init__(self):
        self.calls = []

    def summarize_message(self, message):
        self.calls.append(message)
        return ToolMessage(content="SUMMARY", tool_call_id=message.tool_call_id)


def _shaper(model="gpt-4o", session="sess-1", window=32_768, task=""):
    summarizer = _FakeSummarizer()
    shaper = HistoryShaper(
        model=lambda: model,
        allow_embedding_compute=lambda: False,
        summarizer=summarizer,
        current_task=lambda: task,
        session_id=lambda: session,
        context_window=lambda: window,
    )
    return shaper, summarizer


def _history():
    return [
        HumanMessage(content="first ask"),
        AIMessage(content="", tool_calls=[
            {"name": "read_file", "args": {"path": "a"}, "id": "c1"}]),
        ToolMessage(content="result c1", tool_call_id="c1"),
        AIMessage(content="done"),
    ]


class TestPipeline:
    def test_trim_empty_returns_empty(self):
        shaper, _ = _shaper()
        assert shaper.trim([], budget=100) == []

    def test_trim_under_budget_keeps_the_exchange(self):
        shaper, _ = _shaper()
        out = shaper.trim(_history(), budget=10_000)
        assert [m.type for m in out] == ["human", "ai", "tool", "ai"]

    def test_summarize_touches_only_tool_messages(self):
        shaper, summarizer = _shaper()
        human = HumanMessage(content="hi")
        ai = AIMessage(content="ok")
        tool = ToolMessage(content="x" * 500, tool_call_id="c1")
        out = shaper.summarize_tool_messages([human, ai, tool])

        assert out[0] is human and out[1] is ai, "non-tool messages must pass through untouched"
        assert out[2].content == "SUMMARY"
        assert summarizer.calls == [tool], "only the ToolMessage reaches the summarizer"

    def test_stats_are_the_zero_shape_before_any_use(self):
        shaper, _ = _shaper()
        assert shaper.compactor is None
        assert shaper.stats() == _ZERO_STATS

    def test_stats_carry_the_compactor_counters_after_compact(self):
        shaper, _ = _shaper()
        shaper.compact(_history(), budget=10_000)
        stats = shaper.stats()
        assert "summary_chars" in stats
        assert "llm_suppressed_active" in stats
        assert set(_ZERO_STATS) <= set(stats), "zero keys must survive into live stats"


class TestCompactorSharing:
    def test_compact_off_kill_switch_creates_no_compactor(self, monkeypatch):
        monkeypatch.setenv("PULSEAI_COMPACTION", "off")
        shaper, _ = _shaper()
        out = shaper.compact(_history(), budget=10_000)
        assert isinstance(out, list) and out
        assert shaper.compactor is None, (
            "the legacy structural pipeline must not spin up the D22 compactor"
        )

    def test_two_compacts_share_one_compactor(self):
        """One anti-thrash state per session: the per-turn path and the ABC
        compress() entry must never own separate compactors."""
        shaper, _ = _shaper()
        shaper.compact(_history(), budget=10_000)
        first = shaper.compactor
        assert first is not None
        shaper.compact(_history(), budget=10_000)
        assert shaper.compactor is first

    def test_session_identity_is_rerouted_on_every_ensure(self):
        """Per-build thread routing (dashboard turns) must not leave the
        compactor stamped with a dead session id."""
        state = {"session": "sess-a"}
        shaper = HistoryShaper(
            model=lambda: "gpt-4o",
            allow_embedding_compute=lambda: False,
            summarizer=_FakeSummarizer(),
            current_task=lambda: "",
            session_id=lambda: state["session"],
            context_window=lambda: 32_768,
        )
        shaper.ensure_compactor()
        assert shaper.compactor._session_id == "sess-a"

        state["session"] = "sess-b"
        shaper.ensure_compactor()
        assert shaper.compactor._session_id == "sess-b"

    def test_model_is_read_live_not_captured(self):
        """The engine's model mutates mid-life (update_model /
        reconfigure_model). A shaper that captured it by value would keep
        token-counting with a dead model — the compactor must be created
        with whatever the getter says at FIRST USE."""
        state = {"model": "model-stale"}
        summarizer = _FakeSummarizer()
        shaper = HistoryShaper(
            model=lambda: state["model"],
            allow_embedding_compute=lambda: False,
            summarizer=summarizer,
            current_task=lambda: "",
            session_id=lambda: "sess",
            context_window=lambda: 32_768,
        )
        state["model"] = "model-fresh"  # changed after construction
        shaper.ensure_compactor()
        assert shaper.compactor._model == "model-fresh"


class TestEngineDelegation:
    """The engine keeps the documented method names on the same shaper."""

    def test_engine_methods_delegate_to_one_shaper(self):
        from src.context.context_engine import ContextEngine

        eng = ContextEngine(
            max_tokens=8_192, model="gpt-4o", probe_window=False,
            thread_id="evt-p8-delegate",
        )
        assert eng._compactor is None
        eng._trim_history(_history(), budget=10_000)
        eng._ensure_compactor()
        first = eng._compactor
        assert first is not None
        # _compact_history and the ABC compress() land on the SAME compactor
        eng._compact_history(_history(), budget=10_000)
        assert eng._compactor is first
        assert eng.compaction_stats()["summary_chars"] >= 0
