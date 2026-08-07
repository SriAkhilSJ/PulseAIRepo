"""Pins for D22: the hermes compaction hardening pack (compaction.py).

Contract verified against their context_compressor.py (§29 receipts):
prune-first (free) with ABSOLUTE head/tail protection, structural stage
only on the expendable middle, dropped turns folded into an iterative
aux-model summary, anti-thrash suppression, and the checkpoint store never
sees any of it (request-only copies — their #43175 cannot occur here).
"""

from __future__ import annotations

import pytest
from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)

from src.context.compaction import (
    COMPACTION_SUMMARY_PREFIX,
    HistoryCompactor,
    _PRUNED_TOOL_PLACEHOLDER,
)


def mk(pair_id: str, size: int = 2000) -> list[BaseMessage]:
    """One agent turn with a big tool dump."""
    return [
        HumanMessage(content=f"question {pair_id}"),
        AIMessage(content=f"doing {pair_id}",
                  tool_calls=[{"name": "t", "args": {}, "id": f"tc-{pair_id}"}]),
        ToolMessage(content=f"dump-{pair_id} " + "x" * size,
                    tool_call_id=f"tc-{pair_id}", name="t"),
    ]


@pytest.fixture()
def history() -> list[BaseMessage]:
    msgs = mk("head")
    for i in range(8):
        msgs += mk(str(i))
    return msgs


@pytest.fixture()
def compactor() -> HistoryCompactor:
    return HistoryCompactor(model="gpt-4o-mini", aux_llm_getter=None, tail_tokens=500)


ident = lambda h: h


def _structural_scenario(turns: int = 7, tail_tokens: int = 150):
    """History with a SMALL head (fat heads dominate budgets and mask
    middles) and a compactor whose tiny slim-tail leaves a real middle."""
    hist = mk("head", size=60)
    for i in range(turns):
        hist += mk(str(i))
    compactor = HistoryCompactor(model="gpt-4o-mini", tail_tokens=tail_tokens)
    return hist, compactor


def _budget_forcing_structural(compactor, history, margin=40):
    from src.context.token_budget import count_tokens
    pruned, _, _ = compactor.prune(history)
    return max(1, count_tokens(pruned, "gpt-4o-mini") - margin)


def boom_structural(h, b):
    raise AssertionError("structural stage must not fire")


# ------------------------------------------------------------------ prune
def test_prune_replaces_middle_only_and_never_mutates(history, compactor):
    original_contents = [m.content for m in history]
    pruned, replaced, reclaimed = compactor.prune(history)

    assert replaced == 7                      # head + last turn protected
    assert reclaimed > 10_000
    placeholders = [i for i, m in enumerate(pruned)
                    if isinstance(m, ToolMessage) and m.content == _PRUNED_TOOL_PLACEHOLDER]
    assert all(i >= 3 for i in placeholders)  # nothing in the protected head
    assert pruned[2].content.startswith("dump-head")   # head verbatim
    assert [m.content for m in history] == original_contents  # source untouched
    # pairing survived: every placeholder still carries its tool_call_id
    for m in pruned:
        if isinstance(m, ToolMessage):
            assert m.tool_call_id.startswith("tc-")


def test_short_tool_outputs_and_tiny_histories_untouched(compactor):
    small = [HumanMessage(content="hi"), AIMessage(content="ok",
             tool_calls=[{"name": "t", "args": {}, "id": "a"}]),
             ToolMessage(content="short", tool_call_id="a", name="t")]
    pruned, replaced, _ = compactor.prune(small)
    assert replaced == 0 and pruned[2].content == "short"
    assert compactor.prune([]) == ([], 0, 0)


def test_tail_boundary_never_splits_tool_pair(compactor, history):
    # tail boundary rules: if the boundary message is a ToolMessage, its
    # answering AI(tool_calls) must be pulled into the tail as well.
    tail = compactor._tail_start(history, compactor._head_len(history))
    if tail < len(history) and isinstance(history[tail], ToolMessage):
        pytest.fail("tail starts on a ToolMessage — pair would split")


# ------------------------------------------------------------- two stages
def test_prune_alone_skips_structural_stage(history, compactor):
    # Budget fits AFTER placeholders: structural must never run (spy).
    # Budget measured after prune so it FITS regardless of tokenizer mood.
    pruned, _, _ = compactor.prune(history)
    from src.context.token_budget import count_tokens
    fits = count_tokens(pruned, "gpt-4o-mini")
    compactor2 = HistoryCompactor(model="gpt-4o-mini", tail_tokens=500)
    out = compactor2.compact(history, budget=fits + 200, summarize_tools=ident,
                             structural_compress=boom_structural,
                             fallback_trim=boom_structural)
    assert compactor2.stats["structural_compactions"] == 0
    assert any(isinstance(m, ToolMessage) and m.content == _PRUNED_TOOL_PLACEHOLDER for m in out)


def test_fast_path_no_work(history, compactor):
    out = compactor.compact(history, budget=10**9, summarize_tools=ident,
                            structural_compress=boom_structural, fallback_trim=boom_structural)
    assert compactor.stats["prunes"] == 0 and out is history


def test_head_tail_never_reach_structural_stage(history, compactor):
    seen: list[list[BaseMessage]] = []

    def spy_structural(h, b):
        seen.append(h)
        return h[:1]  # butcher the middle deliberately

    history, compactor = _structural_scenario()
    out = compactor.compact(history, budget=_budget_forcing_structural(compactor, history), summarize_tools=ident,
                            structural_compress=spy_structural, fallback_trim=lambda h, b: h)
    middle = seen[0]
    # absolute protection: head turn + tail never presented to the stage
    assert middle and not any(m.content.startswith("question head") for m in middle)
    assert out[0].content.startswith("question head")         # head leads final
    assert out[-1] is not None
    assert [type(m).__name__ for m in out[-3:]] == ["HumanMessage", "AIMessage", "ToolMessage"]


# ---------------------------------------------------------------- summary
def test_dropped_turns_become_summary_after_head(history, compactor):
    history, compactor = _structural_scenario()
    compactor._aux_llm_getter = None
    out = compactor.compact(history, budget=_budget_forcing_structural(compactor, history), summarize_tools=ident,
                            structural_compress=lambda h, b: h[:1],
                            fallback_trim=lambda h, b: h)
    summaries = [m for m in out if isinstance(m, SystemMessage)
                 and m.response_metadata.get("compaction")]
    assert len(summaries) == 1
    assert summaries[0].content.startswith(COMPACTION_SUMMARY_PREFIX[:40])
    head_len = compactor._head_len(out) if any(
        isinstance(m, HumanMessage) for m in out) else 0
    assert out.index(summaries[0]) <= 3       # right after protected head
    assert compactor.summary                  # running text exists


def test_iterative_summary_extends_previous_via_aux():
    prompts: list[str] = []

    class FakeAux:
        def invoke(self, prompt):
            prompts.append(prompt)
            class R: content = "rolled-summary-v" + str(len(prompts))
            return R()

    hist1, c = _structural_scenario()
    c._aux_llm_getter = lambda: FakeAux()
    c.compact(hist1, budget=_budget_forcing_structural(c, hist1), summarize_tools=ident,
              structural_compress=lambda h, b: h[:1], fallback_trim=lambda h, b: h)
    first = c.summary
    c.compact(hist1, budget=_budget_forcing_structural(c, hist1), summarize_tools=ident,
              structural_compress=lambda h, b: h[:1], fallback_trim=lambda h, b: h)
    assert c.stats["llm_summary_calls"] == 2
    assert first in prompts[-1]               # extend-not-rebuild proof


def test_aux_failure_plain_appends_bounded(compactor):
    def _boom():
        raise RuntimeError("provider down")

    hist, compactor = _structural_scenario()
    compactor._aux_llm_getter = _boom
    out = compactor.compact(
        hist, budget=_budget_forcing_structural(compactor, hist), summarize_tools=ident,
        structural_compress=lambda h, b: h[:1], fallback_trim=lambda h, b: h)
    assert compactor.stats["llm_summary_calls"] == 0
    assert len(compactor.summary) <= 3000
    assert any(isinstance(m, SystemMessage) for m in out)  # still informed


def test_anti_thrash_suppresses_llm_after_three_ineffective():
    calls = []

    class FakeAux:
        def invoke(self, prompt):
            calls.append(prompt)
            class R: content = "s"
            return R()

    c = HistoryCompactor(model="gpt-4o-mini", aux_llm_getter=lambda: FakeAux())
    for _ in range(3):
        c._update_summary([HumanMessage(content="x" * 100)])
        c._note_effectiveness(before=1000, after=960)     # <15% savings
    n = len(calls)
    assert c.llm_suppressed
    c._update_summary([HumanMessage(content="y" * 100)])
    assert len(calls) == n                                # LLM frozen out
    assert c.stats["llm_suppressed"] == 1


# ---------------------------------------------------------------- markers
def test_markers_match_session_index_ingest_skip_list():
    from src.context.session_index import _COMPACTION_PREFIXES
    assert COMPACTION_SUMMARY_PREFIX.startswith("[CONTEXT COMPACTION")
    assert any(COMPACTION_SUMMARY_PREFIX.startswith(p) for p in _COMPACTION_PREFIXES)


# ------------------------------------------------------------- engine glue
def test_engine_compact_history_kill_switch(engine_setup):
    eng, monkeypatch = engine_setup
    monkeypatch.setenv("PULSEAI_COMPACTION", "off")
    called = {}
    original = eng._trim_history
    def spy(hist, budget):
        called["hit"] = True
        return original(hist, budget)
    monkeypatch.setattr(eng, "_trim_history", spy)
    eng._compact_history([HumanMessage(content="hi")], 10**9)
    assert called.get("hit") and eng._compactor is None


@pytest.fixture()
def engine_setup(tmp_path, monkeypatch):
    from src.context.context_engine import ContextEngine
    eng = ContextEngine(max_tokens=8_000, model="gpt-4o-mini", probe_window=False)
    eng._feedback_path = str(tmp_path / "fb.jsonl")
    eng._feedback_history = []
    return eng, monkeypatch


def test_engine_request_only_state_never_mutated(engine_setup):
    eng, _ = engine_setup
    msgs = mk("head")
    for i in range(6):
        msgs += mk(str(i))
    snapshot = [m.content for m in msgs]
    out = eng._compact_history(list(msgs), budget=200)
    assert [m.content for m in msgs] == snapshot           # checkpoint copy safe
    assert len(out) <= len(msgs)
    stats = eng.compaction_stats()                          # wiring live
    assert "placeholders" in stats and "llm_summary_calls" in stats
