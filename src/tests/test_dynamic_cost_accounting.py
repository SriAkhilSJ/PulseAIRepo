"""No guessed generic prices: both accounting surfaces use the ledger catalog."""
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from src.context.token_tracker import TokenTracker, TokenUsage


def test_token_tracker_prices_from_dynamic_catalog_and_marks_unknown_honestly():
    card = {
        "z-ai/glm-5.3-flash": {
            "input_per_1m": 0.018,
            "output_per_1m": 0.121,
            "currency": "USD",
        }
    }
    response = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 12_000, "output_tokens": 100, "total_tokens": 12_100},
    )
    with patch("src.telemetry.call_ledger.load_rate_card", return_value=card):
        usage = TokenTracker.record_call([HumanMessage(content="hello")], response, "z-ai/glm-5.3-flash")
    assert usage.cost_known is True
    assert usage.estimated_cost_usd == (12_000 * 0.018 + 100 * 0.121) / 1_000_000

    with patch("src.telemetry.call_ledger.load_rate_card", return_value={}):
        unknown = TokenTracker.record_call([HumanMessage(content="hello")], response, "unlisted-model")
    assert unknown.cost_known is False
    assert "Cost: unknown (no USD rate)" in TokenTracker.format_usage(unknown)


def test_token_usage_merge_keeps_unknown_cost_unknown():
    known = TokenUsage(estimated_cost_usd=0.02, cost_known=True, calls_made=1)
    unpriced = TokenUsage(estimated_cost_usd=0.0, cost_known=False, calls_made=1)
    combined = known + unpriced
    assert combined.estimated_cost_usd == 0.02
    assert combined.cost_known is False
    assert TokenUsage.from_dict(combined.to_dict()).cost_known is False
