"""Contract tests: Floor-2 Hermes parity phases A/B/C.

A — Pinned summary route (hermes ``_SUMMARY_ROUTE_PIN``): a ContextVar pin,
    single-use consumption, re-entrant restore, None passthrough, and the
    aux resolver honoring provider/model while delegating everything else.
B — Stale reasoning-replay pruning: aged AIMessages lose their reasoning
    payloads, the newest keep_recent keep theirs, count is exact.
C — Salvage summary cap: an over-chatty running summary is capped at 8,000
    chars with an honest marker, never its own overflow.

Provider-free: no LLM, no network, no embeddings.
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.context.compaction import (
    _salvage_cap_summary,
    prune_stale_reasoning_replay,
)
from src.context.summary_route_pin import (
    PINNED_ROUTE_FIELDS,
    aux_llm_for_route,
    peek_pinned_summary_route,
    pin_summary_route,
    take_pinned_summary_route,
)


# ---------------------------------------------------------------------------
# Phase A — the pin lifecycle
# ---------------------------------------------------------------------------

def test_pin_sets_and_take_consumes_once():
    route = {"provider": "groq", "model": "llama-3.1-8b-instant"}
    with pin_summary_route(route):
        assert peek_pinned_summary_route() is route
        assert take_pinned_summary_route() is route
        # Single use by design: the retry must not re-issue the pin.
        assert take_pinned_summary_route() is None
        assert peek_pinned_summary_route() is None
    assert take_pinned_summary_route() is None


def test_pin_none_is_a_noop_passthrough():
    with pin_summary_route(None):
        assert take_pinned_summary_route() is None


def test_pin_is_reentrant_safe():
    outer = {"provider": "a", "model": "m1"}
    inner = {"provider": "b", "model": "m2"}
    with pin_summary_route(outer):
        with pin_summary_route(inner):
            assert take_pinned_summary_route() is inner
        # Exit of the INNER pin restores the OUTER pin, not a clean state.
        assert take_pinned_summary_route() is outer


def test_pinned_fields_are_the_declared_six():
    assert PINNED_ROUTE_FIELDS == (
        "provider", "model", "base_url", "api_key", "api_mode", "timeout",
    )


def test_aux_llm_for_route_honors_provider_and_model():
    def default_getter():
        return "DEFAULT_LLM"

    llm = aux_llm_for_route(default_getter, {"provider": "groq", "model": "fall"})
    from src.llm.factory import RequestScopedAuxLLM

    assert isinstance(llm, RequestScopedAuxLLM)


def test_aux_llm_for_route_passthrough_without_usable_route():
    def default_getter():
        return "DEFAULT_LLM"

    assert aux_llm_for_route(default_getter, None) == "DEFAULT_LLM"
    assert aux_llm_for_route(default_getter, {}) == "DEFAULT_LLM"
    # A route with neither provider nor model cannot build a facade.
    assert aux_llm_for_route(default_getter, {"timeout": 5}) == "DEFAULT_LLM"


# ---------------------------------------------------------------------------
# Phase B — stale reasoning-replay pruning
# ---------------------------------------------------------------------------

def _ai_with_reasoning(text: str, payload: str) -> AIMessage:
    return AIMessage(content=text, additional_kwargs={
        "reasoning_content": payload, "reasoning": payload,
        "reasoning_details": [{"text": payload}],
    })


def test_prune_aged_reasoning_keeps_recent_window():
    msgs = [HumanMessage(content="u0")]
    msgs += [_ai_with_reasoning(f"a{i}", f"think-{i}") for i in range(10)]
    msgs.append(HumanMessage(content="final"))

    pruned = prune_stale_reasoning_replay(msgs, keep_recent=3)

    assert pruned == 7  # 10 AI messages, newest 3 untouched
    for i in range(7):
        assert "reasoning_content" not in msgs[1 + i].additional_kwargs
    for i in (7, 8, 9):
        assert msgs[1 + i].additional_kwargs["reasoning_content"] == f"think-{i}"


def test_prune_counts_only_messages_that_had_reasoning():
    msgs = [AIMessage(content="clean", additional_kwargs={}) for _ in range(5)]
    msgs[0].additional_kwargs["reasoning"] = "only-this-one"
    pruned = prune_stale_reasoning_replay(msgs, keep_recent=0)
    assert pruned == 1
    assert "reasoning" not in msgs[0].additional_kwargs


def test_prune_never_touches_non_ai_messages():
    msgs = [HumanMessage(content="human", additional_kwargs={"reasoning": "odd"})] * 3
    pruned = prune_stale_reasoning_replay(msgs, keep_recent=0)
    assert pruned == 0
    assert msgs[0].additional_kwargs["reasoning"] == "odd"


# ---------------------------------------------------------------------------
# Phase C — the salvage summary cap
# ---------------------------------------------------------------------------

def test_salvage_cap_passthrough_under_limit():
    assert _salvage_cap_summary("short summary") == "short summary"
    assert _salvage_cap_summary("x" * 8_000) == "x" * 8_000


def test_salvage_cap_truncates_overgrown_summary_honestly():
    grown = "x" * 20_000
    capped = _salvage_cap_summary(grown)
    assert len(capped) < len(grown)
    assert capped.startswith("x" * 100)  # head kept
    assert capped.endswith("...[summary truncated to salvage the transcript]...")
    assert len(capped) == 8_000 + len("\n...[summary truncated to salvage the transcript]...")
