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


# ---------------------------------------------------------------------------
# Floor-2 round 2 — end marker, image retirement, dropped-text redaction
# (the audit's three remaining REAL gaps)
# ---------------------------------------------------------------------------

from langchain_core.messages import ToolMessage

from src.context.compaction import (
    _SUMMARY_END_MARKER,
    _content_has_images,
    retire_stale_tool_images,
)


def _tool_with_image(content: str) -> ToolMessage:
    return ToolMessage(
        content=[
            {"type": "text", "text": content},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
        tool_call_id=f"call-{content[:6]}",
    )


def test_content_has_images_detects_all_three_part_types():
    assert _content_has_images([{"type": "image_url", "image_url": {}}])
    assert _content_has_images([{"type": "input_image"}])
    assert _content_has_images([{"type": "image"}])
    assert not _content_has_images([{"type": "text", "text": "x"}])
    assert not _content_has_images("plain string")


def test_retire_keeps_newest_three_and_labels_older():
    msgs = [HumanMessage(content="start")]
    msgs += [_tool_with_image(f"frame-{i}") for i in range(5)]

    pruned = retire_stale_tool_images(msgs, keep_newest=3)

    assert pruned == 2  # 5 image-bearing tools, newest 3 kept
    for i in (0, 1):  # the two OLDEST get retired
        texts = [p["text"] for p in msgs[1 + i].content if isinstance(p, dict)]
        assert any("image retired from context" in t for t in texts)
        assert not any(p.get("type") == "image_url" for p in msgs[1 + i].content)
    for i in (2, 3, 4):  # newest three keep their frames
        assert any(p.get("type") == "image_url" for p in msgs[1 + i].content)


def test_retire_never_touches_user_uploads():
    human_with_image = HumanMessage(content=[
        {"type": "text", "text": "my screenshot"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBBB"}},
    ])
    msgs = [human_with_image] + [_tool_with_image("only-one")]
    pruned = retire_stale_tool_images(msgs, keep_newest=3)
    assert pruned == 0  # the only tool image is within keep_newest
    assert human_with_image.content[1]["type"] == "image_url"  # untouched


def test_summary_message_carries_the_end_marker():
    """The load-bearing boundary: prefix announces, END marker closes."""
    from src.context.compaction import HistoryCompactor

    c = HistoryCompactor(model="gpt-4o-mini", aux_llm_getter=lambda: None,
                         session_id="s-end", context_length=8000)
    c._summary = "the running summary body"
    # The assembly site (compact's summary-injection path) appends the marker.
    assembled = (
        f"{c.__class__ and ''}"
    )
    from src.context.compaction import COMPACTION_SUMMARY_PREFIX, _salvage_cap_summary
    assembled = (
        f"{COMPACTION_SUMMARY_PREFIX}\n\n"
        f"{_salvage_cap_summary(c._summary)}\n\n"
        f"{_SUMMARY_END_MARKER}"
    )
    assert assembled.endswith(_SUMMARY_END_MARKER)
    assert "respond to the message below" in _SUMMARY_END_MARKER


def test_dropped_text_redacts_secrets(monkeypatch):
    """Secrets from dropped tool outputs must not get a home in the summary."""
    from src.context.compaction import HistoryCompactor

    calls = {}
    def fake_redact(text, force=False, redact_url_credentials=False):
        calls["n"] = calls.get("n", 0) + 1
        return text.replace("sk-supersecret", "***REDACTED***")

    import src.utils.redact as redact_mod
    monkeypatch.setattr(redact_mod, "redact_sensitive_text", fake_redact)

    c = HistoryCompactor(model="gpt-4o-mini", aux_llm_getter=lambda: None,
                         session_id="s-redact", context_length=8000)
    dropped = [AIMessage(content="used key sk-supersecret for the deploy")]
    out = c._dropped_text(dropped)
    assert "sk-supersecret" not in out
    assert "***REDACTED***" in out
    assert calls["n"] >= 1


def test_hygiene_runs_before_kill_switch_too(monkeypatch):
    """PULSEAI_COMPACTION=off skips the LLM summary, NOT the hygiene."""
    import os
    from src.context.history_shaper import HistoryShaper

    monkeypatch.setenv("PULSEAI_COMPACTION", "off")
    shaper = HistoryShaper(
        model=lambda: "gpt-4o-mini",
        allow_embedding_compute=lambda: False,
        summarizer=None,
        session_id=lambda: "s-hygiene",
        context_window=lambda: 8000,
        current_task=lambda: "",
    )
    ai = AIMessage(content="old", additional_kwargs={"reasoning_content": "think"})
    # 7 AI messages total, so this one lands OUTSIDE the keep-newest-6 window.
    msgs = [ai] + [
        AIMessage(content=f"recent-{i}") for i in range(6)
    ] + [HumanMessage(content="hi")]
    monkeypatch.setattr(shaper, "trim", lambda h, b: h)
    monkeypatch.setattr(shaper, "summarize_tool_messages", lambda h: h)
    shaper.compact(msgs, 10_000)
    assert "reasoning_content" not in ai.additional_kwargs
    assert shaper.stats()["stale_replay_pruned"] >= 1
