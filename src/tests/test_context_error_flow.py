"""Window vs reply cap, kept separate -- and the provider's error deciding what changes.

Upstream (hermes-agent @ 8cab422, tests/test_ctx_halving_fix.py) names this as a fixed bug:
"max_tokens = OUTPUT token cap (a single response). context_length = TOTAL context window (input + output
combined). These are different and the old code conflated them; the fix keeps them separate."

Pulse re-introduced the conflation one commit ago by subtracting the stated reply cap from the budget. On
the owner's endpoint (window 1,048,576, max_output_tokens 512,000) that cost 262,144 tokens of context for
no provider reason -- while ALSO, because my clamp capped the reservation at 25% of the window, promising
MORE input than a max-length reply could coexist with. Both halves of that are wrong, so both are pinned here.
"""
from __future__ import annotations

import pathlib
import pytest

from src.context import model_budgets as mb
from src.llm import output_budget as ob
from src.llm.context_errors import (
    get_context_length_from_provider_error,
    parse_available_output_tokens_from_error,
    parse_context_limit_from_error,
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """One cache file AND one pending-allowance slot per test.

    The allowance store is module-level by design (the retry loop and the bind site have no object path to
    each other), so tests must clear it or they inherit each other's one-shot value -- which is also the
    honest description of its blast radius in production: at most one delivery, for one model.
    """
    monkeypatch.setattr(mb, "_cache_path", lambda: str(tmp_path / "model_windows.json"))
    ob._available_output.clear()
    yield
    ob._available_output.clear()


def _state(monkeypatch, *, window=None, cap="drop"):
    """Seed a real cache entry so the endpoint answer is in place -- through the actual file, not a stub.

    Stubbing `_read_cache` here would also blind the tests that assert a write landed, which is the exact
    round-trip under test. `cap="drop"` means "the entry exists but publishes no output ceiling".
    """
    import json

    monkeypatch.setattr(mb, "_effective_provider", lambda p: "custom")
    monkeypatch.delenv("LLM_CONTEXT_WINDOW", raising=False)
    path = pathlib.Path(mb._cache_path())
    entry = {"window": window} if window is not None else {}
    if cap != "drop":
        entry["max_output"] = cap
    entry["ts"] = __import__("time").time()
    payload = {"custom:test-model": entry} if entry else {}
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. The separation itself
# ---------------------------------------------------------------------------

def test_a_big_reply_allowance_does_not_shrink_the_window():
    window = 1_048_576
    assert mb.usable_window_budget(window) == window - max(mb.SAFETY_MARGIN, int(window * 0.05))
    # No second argument exists to pass a cap into -- the signature is the guard.
    with pytest.raises(TypeError):
        mb.usable_window_budget(window, 512_000)


# ---------------------------------------------------------------------------
# 2. The send path asks for what the provider allows, not for a constant
# ---------------------------------------------------------------------------

def test_the_user_setting_is_the_request_and_the_provider_is_the_ceiling(monkeypatch):
    _state(monkeypatch, window=1_048_576, cap=512_000)
    assert ob.requested_output_cap("test-model", requested=4096) == 4096
    assert ob.requested_output_cap("test-model", requested=600_000) == 512_000


def test_no_stated_cap_means_no_invented_cap(monkeypatch):
    """The bug this replaces: an absent provider number used to become 8,192."""

    _state(monkeypatch, window=131_072, cap=None)
    assert ob.requested_output_cap("test-model", requested=32_000) == 32_000


def test_a_silly_user_setting_is_floored_not_zeroed(monkeypatch):
    _state(monkeypatch, window=131_072, cap=512_000)
    assert ob.requested_output_cap("test-model", requested=10) == 512


def test_the_env_setting_still_drives_it(monkeypatch):
    _state(monkeypatch, window=131_072, cap=None)
    monkeypatch.setenv("PULSEAI_DELIVERY_MAX_TOKENS", "3072")
    assert ob.requested_output_cap("test-model") == 3072


# ---------------------------------------------------------------------------
# 3. The one-shot override
# ---------------------------------------------------------------------------

def test_the_reported_allowance_is_consumed_once():
    ob.note_available_output("test-model", 10_000)
    assert ob.take_available_output("test-model") == 10_000
    assert ob.take_available_output("test-model") is None, (
        "carrying it forward would cap the NEXT turn by a message about this one"
    )


def test_a_zero_allowance_is_not_recorded():
    ob.note_available_output("test-model", 0)
    assert ob.pending_available_output("test-model") is None


# ---------------------------------------------------------------------------
# 4. Upstream's message shapes, verbatim from their comments
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "message,expected",
    [
        (
            "max_tokens: 32768 > context_window: 200000 - input_tokens: 190000 = available_tokens: 10000",
            10_000,
        ),
        (
            "This model's maximum context length is 65536 tokens. However, you requested 65536 output "
            "tokens and your prompt contains 77409 characters, which exceeds the limit",
            None,  # ctx 65536 - ~25803 estimated input; a positive number is expected below instead
        ),
        ("Range of max_tokens should be [1, 65536]", 65_536),
        ("max_tokens (98304) exceeds model's maximum output tokens (65536)", 65_536),
        (
            "This model's maximum context length is 200000 tokens. Requested 40000 tokens of output "
            "(190000 of text input, 5000 of tool input, 40000 in the output)",
            5_000,
        ),
    ],
)
def test_output_cap_errors_recognised(message, expected):
    got = parse_available_output_tokens_from_error(message)
    if expected is None:
        # The llama.cpp form is an output-cap error upstream converts via chars/3, so it must return
        # SOME positive figure -- assert that instead of a hardcoded number, which is the old sin.
        assert got and got > 1, got
    else:
        assert got == expected, got


def test_a_plain_prompt_too_long_error_is_not_an_output_error():
    """Resending the same oversized prompt is not a recovery; compressing is."""

    msg = "This model's maximum context length is 8192 tokens. However, your messages resulted in 30000 tokens."
    assert parse_available_output_tokens_from_error(msg) is None


def test_a_limit_is_only_adopted_when_the_provider_states_it():
    assert parse_context_limit_from_error("max_model_len 32768") == 32_768
    assert parse_context_limit_from_error("context_length_exceeded: 131072") == 131_072
    assert get_context_length_from_provider_error("this prompt is too long, sorry", 200_000) is None, (
        "no number in the message means no new window from us -- never a guessed tier step-down"
    )
    assert get_context_length_from_provider_error("maximum context length is 32768 tokens", 200_000) == 32_768
    assert get_context_length_from_provider_error("maximum context length is 400000 tokens", 200_000) is None, (
        "a LARGER reported window is not a correction to apply mid-session"
    )


def test_an_explicit_limit_lands_in_the_cache_the_next_build_reads(tmp_path, monkeypatch):
    from src.llm.context_errors import apply_reported_limit

    apply_reported_limit("test-model", "custom", 32_768)
    monkeypatch.setattr(mb, "_effective_provider", lambda p: "custom")
    window, source = mb.resolve_context_window("test-model", allow_network=False)
    assert (window, source) == (32_768, "cache")


# ---------------------------------------------------------------------------
# 5. The decision the retry loop obeys (lives with the parsers so it is testable without a client)
# ---------------------------------------------------------------------------

def test_an_output_cap_rejection_allows_exactly_one_resend(monkeypatch):
    from src.llm.context_errors import handle_context_error

    _state(monkeypatch, window=200_000, cap=None)
    msg = "max_tokens: 32768 > context_window: 200000 - input_tokens: 190000 = available_tokens: 10000"
    assert handle_context_error("test-model", msg) is True
    assert ob.pending_available_output("test-model") == 10_000
    assert mb.resolve_context_window("test-model", allow_network=False)[0] == 200_000, (
        "the window must be untouched: an output rejection says nothing about its size"
    )


def test_a_prompt_too_long_rejection_is_not_resendable_and_guesses_nothing(monkeypatch):
    from src.llm.context_errors import handle_context_error

    _state(monkeypatch, window=200_000, cap=None)
    assert handle_context_error("test-model", "This prompt is too long for this model.") is False
    assert mb.resolve_context_window("test-model", allow_network=False)[0] == 200_000
    assert ob.pending_available_output("test-model") is None


def test_an_explicitly_reported_window_is_remembered_for_the_next_build(monkeypatch, capsys):
    from src.llm.context_errors import handle_context_error

    _state(monkeypatch, window=200_000, cap=None)
    assert handle_context_error("test-model", "maximum context length is 32768 tokens") is False
    assert "32,768" in capsys.readouterr().out, "the correction has to be visible when it happens"
    assert mb.resolve_context_window("test-model", allow_network=False) == (32_768, "cache")


def test_correcting_the_window_does_not_erase_the_reply_cap(monkeypatch):
    """The one real bug this commit found in its own new code.

    A cache write is whole-entry, so persisting a provider-reported window without carrying the cap forward
    would have quietly restored "no stated ceiling" for a model whose endpoint publishes 512,000.
    """
    from src.llm.context_errors import apply_reported_limit

    _state(monkeypatch, window=1_048_576, cap=512_000)
    apply_reported_limit("test-model", "custom", 262_144)
    assert mb.resolve_context_window("test-model", provider="custom", allow_network=False) == (262_144, "cache")
    assert mb.max_output_for("test-model", "custom") == 512_000, "the ceiling survives the correction"


def test_a_correction_lands_on_the_entry_the_app_reads(monkeypatch):
    """A cache key is `provider:model`, and the callers do not agree on the provider.

    The probe writes `custom:model` because it was handed "custom"; the engine resolves with
    settings.LLM_PROVIDER. My first version of `apply_reported_limit` defaulted a missing provider to "",
    writing a third key `:model` that nothing ever read -- the correction looked applied in the log and
    changed no budget. So the writer must follow the same fallback as the reader, and must reuse the
    model's existing entry instead of orphaning it.
    """
    import json
    from src.llm.context_errors import apply_reported_limit

    monkeypatch.setattr(mb, "_effective_provider", lambda p: (p or "").strip().lower())
    monkeypatch.delenv("LLM_CONTEXT_WINDOW", raising=False)
    path = pathlib.Path(mb._cache_path())
    path.write_text(json.dumps({"custom:test-model": {"window": 1_048_576, "max_output": 512_000,
                                                       "ts": __import__("time").time()}}), encoding="utf-8")

    apply_reported_limit("test-model", None, 262_144)

    data = json.loads(path.read_text())
    assert list(data) == ["custom:test-model"], f"writer created a sibling key: {list(data)}"
    assert data["custom:test-model"]["window"] == 262_144
    assert data["custom:test-model"]["max_output"] == 512_000
    assert mb.max_output_for("test-model") == 512_000
