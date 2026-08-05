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

        eng = ContextEngine(
            model="gpt-4o", llm=None, memory_manager=None, probe_window=False
        )
        expected = max(min(usable_budget("gpt-4o"), PROVIDER_SAFE_LIMIT), 4_096)
        assert eng.max_tokens == expected
        # And with the shipped default limit, a 128K model is capped DOWN:
        # building more would just be trimmed by RetryLLMProxy at send time.
        assert eng.max_tokens <= PROVIDER_SAFE_LIMIT
        assert eng.context_window == 128_000
        assert eng.context_window_source == "static-table"

    def test_auto_budget_never_below_floor(self):
        eng = ContextEngine(
            model="gpt-4", llm=None, memory_manager=None, probe_window=False
        )
        assert eng.max_tokens >= 4_096

    def test_unknown_model_auto_budget_is_conservative(self):
        # probe_window=False: no network in tests — unknown must degrade
        # straight to the conservative default.
        eng = ContextEngine(
            model="acme/mystery-llm", llm=None, memory_manager=None,
            probe_window=False,
        )
        assert eng.max_tokens <= 8_192
        assert eng.context_window_source == "default"


# =====================================================================
# DYNAMIC discovery: override -> cache -> table -> live probe -> default
# =====================================================================

import json
import os

import pytest

from src.context import model_budgets as mb


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Every dynamic test gets a private HOME (private ~/.pulseai cache)
    and no lingering override env var."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LLM_CONTEXT_WINDOW", raising=False)
    yield


class TestDynamicResolution:
    def test_env_override_wins_over_everything(self, monkeypatch):
        monkeypatch.setenv("LLM_CONTEXT_WINDOW", "99999")
        window, source = mb.resolve_context_window("gpt-4o", provider="openai")
        assert (window, source) == (99999, "env-override")

    def test_static_table_beats_network(self, monkeypatch):
        def _boom(url, headers=None):
            raise AssertionError("network must not be touched for known models")

        monkeypatch.setattr(mb, "_http_get_json", _boom)
        window, source = mb.resolve_context_window("gpt-4o", provider="openai")
        assert (window, source) == (128_000, "static-table")

    def test_groq_probe_parses_context_window(self, monkeypatch):
        def fake_get(url, headers=None):
            assert "api.groq.com" in url
            assert headers["Authorization"].startswith("Bearer ")
            return {"data": [
                {"id": "llama-3.3-70b-versatile", "context_window": 131072},
                {"id": "qwen/qwen3.6-27b", "context_window": 131072},
            ]}

        monkeypatch.setattr(mb, "_http_get_json", fake_get)
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        # The repo's OWN default model: unknown to every static table,
        # discoverable from the provider.
        window, source = mb.resolve_context_window(
            "qwen/qwen3.6-27b", provider="groq", allow_network=True
        )
        assert (window, source) == (131072, "groq-api")

    def test_gemini_probe_parses_input_token_limit(self, monkeypatch):
        monkeypatch.setattr(
            mb, "_http_get_json",
            lambda url, headers=None: {"inputTokenLimit": 1_048_576},
        )
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        window, source = mb.resolve_context_window(
            "gemini-9.9-ultra-exp",  # unknown to the static table
            provider="gemini",
            allow_network=True,
        )
        assert (window, source) == (1_048_576, "gemini-api")

    def test_openrouter_probe_parses_context_length(self, monkeypatch):
        monkeypatch.setattr(
            mb, "_http_get_json",
            lambda url, headers=None: {"data": [
                {"id": "acme/new-model", "context_length": 65536},
            ]},
        )
        window, source = mb.resolve_context_window(
            "acme/new-model", provider="openrouter", allow_network=True
        )
        assert (window, source) == (65536, "openrouter-api")

    def test_probe_result_is_cached(self, monkeypatch):
        calls = {"n": 0}

        def fake_get(url, headers=None):
            calls["n"] += 1
            return {"data": [{"id": "acme/m", "context_length": 50000}]}

        monkeypatch.setattr(mb, "_http_get_json", fake_get)
        first = mb.resolve_context_window("acme/m", provider="openrouter")
        assert first == (50000, "openrouter-api")

        # Second call: network now FAILS, fresh cache must answer instead.
        monkeypatch.setattr(
            mb, "_http_get_json",
            lambda url, headers=None: (_ for _ in ()).throw(OSError("down")),
        )
        second = mb.resolve_context_window("acme/m", provider="openrouter")
        assert second == (50000, "cache")
        assert calls["n"] == 1  # probed exactly once

    def test_probe_failure_falls_to_stale_cache_then_default(self, monkeypatch):
        # Write a stale cache entry by hand.
        cache = mb._cache_path()
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w") as f:
            json.dump({"groq:acme/old": {"window": 42000, "ts": 0}}, f)  # ts=0 -> ancient

        monkeypatch.setattr(mb, "_http_get_json", lambda url, headers=None: None)
        window, source = mb.resolve_context_window("acme/old", provider="groq")
        assert (window, source) == (42000, "cache-stale")

        window, source = mb.resolve_context_window("acme/never-seen", provider="groq")
        assert (window, source) == (8_192, "default")

    def test_engine_uses_dynamic_window(self, monkeypatch):
        monkeypatch.setattr(
            mb, "resolve_context_window",
            lambda model, provider=None, allow_network=True: (131072, "groq-api"),
        )
        from src.config.settings import PROVIDER_SAFE_LIMIT

        eng = ContextEngine(model="qwen/qwen3.6-27b", llm=None, memory_manager=None)
        assert eng.context_window == 131072
        assert eng.context_window_source == "groq-api"
        # min(131072 - 4096, PROVIDER_SAFE_LIMIT)
        assert eng.max_tokens == min(131072 - 4096, PROVIDER_SAFE_LIMIT)


class TestSettingsKeyResolution:
    def test_probe_reads_key_from_settings_when_env_missing(self, monkeypatch):
        from src.config import settings
        # Key lives in .env (loaded by settings); raw env deliberately absent.
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_from_dotenv")
        captured = {}

        def fake_get(url, headers=None):
            captured.update(headers or {})
            return {"data": [{"id": "acme/x", "context_window": 77777}]}

        monkeypatch.setattr(mb, "_http_get_json", fake_get)
        assert mb._probe_groq("acme/x") == 77777
        assert captured["Authorization"] == "Bearer gsk_from_dotenv"

    def test_probe_returns_none_without_any_key(self, monkeypatch):
        from src.config import settings
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setattr(settings, "GROQ_API_KEY", None)
        assert mb._probe_groq("acme/x") is None


class TestAutoUnlock:
    def test_engine_unlocks_discovered_window_when_cap_is_zero(self, monkeypatch):
        from src.config import settings
        monkeypatch.setattr(settings, "PROVIDER_SAFE_LIMIT", 0)
        monkeypatch.setattr(
            mb, "resolve_context_window",
            lambda model, provider=None, allow_network=True: (131072, "groq-api"),
        )
        eng = ContextEngine(llm=None, memory_manager=None)
        # No provider cap: budget = discovered window minus reply headroom.
        assert eng.max_tokens == 131072 - SAFETY_MARGIN
