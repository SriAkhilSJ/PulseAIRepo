"""Model-aware token budgets — regression tests.

These pin the exact failure modes found in an earlier pasted spec:
- naive prefix matching handed gpt-4-0613 a 128K budget (real: 8192),
- provider-prefixed names (the repo's own default format) fell through
  to the 8192 default,
- the engine must never budget past PROVIDER_SAFE_LIMIT, or the
  RetryLLMProxy trims the excess middle-out before every send.
"""

from src.context.context_engine import ContextEngine
from src.context.model_budgets import (
    MODEL_WINDOWS,
    SAFETY_MARGIN,
    model_window,
    usable_budget,
)


class TestModelWindow:
    def test_exact_match(self):
        assert model_window("gpt-4o") == 128_000
        assert model_window("claude-3-5-sonnet") == 200_000

    def test_date_suffix_stripped(self):
        assert model_window("claude-3-5-sonnet-20241022") == 200_000
        assert model_window("gpt-4o-2024-08-06") == 128_000

    def test_dated_gpt4_does_NOT_inherit_gpt4o_window(self):
        # THE pasted-spec bug: "gpt-4-0613" matched a "gpt" prefix derived
        # from the gpt-4o key and got 128_000. Must stay 8_192.
        assert model_window("gpt-4-0613") == 8_192
        assert model_window("gpt-4") == 8_192

    def test_longest_prefix_wins(self):
        # "gpt-4o-..." is a valid prefix-extension of both "gpt-4" and
        # "gpt-4o"; only the longest is correct.
        assert model_window("gpt-4o-mini-2024-07-18") == 128_000

    def test_provider_prefix_stripped(self):
        # The repo's LLM_MODEL default is provider-prefixed.
        assert model_window("openai/gpt-4o") == 128_000
        assert model_window("groq/llama-3.3-70b-versatile") == 131_072

    def test_unknown_model_is_conservative(self):
        # Unknown -> 8192 on purpose: undershoot costs context, overshoot
        # costs the whole request (provider 400).
        assert model_window("qwen/qwen3.6-27b") == MODEL_WINDOWS["default"]
        assert model_window("totally-made-up-9000") == MODEL_WINDOWS["default"]
        assert model_window(None) == MODEL_WINDOWS["default"]
        assert model_window("") == MODEL_WINDOWS["default"]

    def test_case_insensitive(self):
        assert model_window("GPT-4O") == 128_000


class TestUsableBudget:
    def test_safety_margin_reserved(self):
        assert usable_budget("gpt-4o") == 128_000 - SAFETY_MARGIN

    def test_floor_for_tiny_windows(self):
        # window <= margin must still return a usable floor
        assert usable_budget("gpt-4") == max(8_192 - SAFETY_MARGIN, 4_096)
        assert usable_budget("gpt-4") >= 4_096


class TestEngineAutoBudget:
    def test_explicit_max_tokens_wins(self):
        eng = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
        assert eng.max_tokens == 4000

    def test_auto_budget_capped_by_provider_safe_limit(self):
        from src.config.settings import PROVIDER_SAFE_LIMIT

        eng = ContextEngine(model="gpt-4o", llm=None, memory_manager=None)
        expected = max(min(usable_budget("gpt-4o"), PROVIDER_SAFE_LIMIT), 4_096)
        assert eng.max_tokens == expected
        # And with the shipped default limit, a 128K model is capped DOWN:
        # building more would just be trimmed by RetryLLMProxy at send time.
        assert eng.max_tokens <= PROVIDER_SAFE_LIMIT

    def test_auto_budget_never_below_floor(self):
        eng = ContextEngine(model="gpt-4", llm=None, memory_manager=None)
        assert eng.max_tokens >= 4_096

    def test_unknown_model_auto_budget_is_conservative(self):
        eng = ContextEngine(model="acme/mystery-llm", llm=None, memory_manager=None)
        assert eng.max_tokens <= 8_192
