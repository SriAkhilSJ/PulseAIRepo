"""A wallet with no money is terminal, not transient.

Field 2026-11-01, live 7-turn session: the gateway answered

    Error code: 402 - {'error': {'message': 'Balance ₹0.00. Top up from ₹10 at
                      https://velona.in/wallet', 'code': 402}}

and `classify_api_error` returned `unknown` with `retryable=True`. The agent
therefore retried a dead balance across every remaining turn (each failing again
in 0.6s), and the harness reported them as generic turn failures. Neither
surface could tell the operator the one thing that mattered: top up the account.

The phrasing misses the old pattern list, which is built from OpenAI/Anthropic
style bodies ("insufficient credits", "credit balance"…). Velona says
"Balance ₹0.00. Top up from ₹10".
"""

from __future__ import annotations

import pytest


VELONA_402 = (
    "Error code: 402 - {'error': {'message': 'Balance \u20b90.00. "
    "Top up from \u20b910 at https://velona.in/wallet', 'code': 402}}"
)


@pytest.mark.parametrize(
    "message",
    [
        VELONA_402,
        "insufficient balance",
        "Balance $0.00 please top up",
        "balance: 0",
        "your credit balance is too low",
        "402 payment required",
    ],
)
def test_billing_messages_are_recognised(message):
    from src.llm.error_classifier import _is_billing_message

    assert _is_billing_message(message.lower()) is True


@pytest.mark.parametrize(
    "message",
    [
        "rate limit exceeded, retry in 20s",
        "context length exceeded: 300000 tokens",
        "connection reset by peer",
        "model not found",
    ],
)
def test_non_billing_messages_are_not_flagged(message):
    from src.llm.error_classifier import _is_billing_message

    assert _is_billing_message(message.lower()) is False


def test_velona_402_classifies_as_billing_and_is_not_retryable():
    from src.llm.error_classifier import FailoverReason, classify_api_error

    class _ProviderError(Exception):
        pass

    result = classify_api_error(
        _ProviderError(VELONA_402), provider="custom", model="z-ai/glm-5.3-flash"
    )
    assert result.reason is FailoverReason.billing
    assert result.retryable is False


def test_billing_detection_has_one_definition():
    """Seven call sites used to inline the pattern list; they must not drift.

    The Velona body was missed by every one of them simultaneously precisely
    because the predicate was copy-pasted. There is now a single function, and
    the call sites route through it.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "llm" / "error_classifier.py"
    ).read_text(encoding="utf-8")
    inline = "any(p in error_msg for p in _BILLING_PATTERNS)"
    # Exactly ONE occurrence is allowed: inside _is_billing_message itself.
    assert source.count(inline) == 1, (
        "the billing pattern list must be consulted in exactly one place"
    )
    assert source.count("_is_billing_message(error_msg)") >= 5


def test_long_session_harness_halts_instead_of_burning_turns():
    """The driver must stop a session whose wallet is empty."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "run_long_session.py"
    ).read_text(encoding="utf-8")
    assert "_is_billing_failure" in source
    assert "session-halted-provider-balance" in source
    assert "topping up is the only fix" in source
