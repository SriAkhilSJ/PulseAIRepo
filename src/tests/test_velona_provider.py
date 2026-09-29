"""Pins for the first-class Velona provider (OpenAI-compatible /v1 surface)."""

from __future__ import annotations

import pytest

import src.config.settings as settings
from src.llm import factory
from src.llm.factory import ReasoningAwareOpenAI, RetryLLMProxy, get_llm


def test_velona_builds_reasoning_aware_client_on_v1(monkeypatch):
    monkeypatch.delenv("VELONA_API_KEY", raising=False)
    monkeypatch.delenv("VELONA_BASE_URL", raising=False)
    # The branch reads the factory's from-imported names (like every provider).
    monkeypatch.setattr(factory, "VELONA_API_KEY", "key_test_123")
    monkeypatch.setattr(factory, "VELONA_BASE_URL", "https://velona.in/v1")
    client = get_llm("velona", "openai/gpt-4o-mini")
    assert isinstance(client, RetryLLMProxy)
    assert isinstance(client._llm, ReasoningAwareOpenAI)
    assert client._llm.model_name == "openai/gpt-4o-mini"
    assert str(client._llm.openai_api_base).rstrip("/") == "https://velona.in/v1"
    assert client._llm.openai_api_key.get_secret_value() == "key_test_123"


def test_velona_defaults_to_the_compat_surface(monkeypatch):
    monkeypatch.delenv("VELONA_API_KEY", raising=False)
    monkeypatch.delenv("VELONA_BASE_URL", raising=False)
    monkeypatch.setattr(factory, "VELONA_API_KEY", "k")
    monkeypatch.setattr(factory, "VELONA_BASE_URL", "")
    client = get_llm("velona", "m")
    assert str(client._llm.openai_api_base).rstrip("/") == "https://velona.in/v1"


def test_velona_requires_a_key(monkeypatch):
    monkeypatch.delenv("VELONA_API_KEY", raising=False)
    monkeypatch.setattr(factory, "VELONA_API_KEY", "")
    with pytest.raises(ValueError, match="VELONA_API_KEY"):
        get_llm("velona", "openai/gpt-4o-mini")


def test_velona_env_overrides_settings_without_restart(monkeypatch):
    monkeypatch.setattr(factory, "VELONA_API_KEY", "stale")
    monkeypatch.setattr(factory, "VELONA_BASE_URL", "https://stale.example/v1")
    monkeypatch.setenv("VELONA_API_KEY", "key_live_rotated")
    monkeypatch.setenv("VELONA_BASE_URL", "https://proxy.example/v1")
    client = get_llm("velona", "m")
    assert str(client._llm.openai_api_base).rstrip("/") == "https://proxy.example/v1"
    assert client._llm.openai_api_key.get_secret_value() == "key_live_rotated"


def test_velona_resolves_to_the_gateway_budget_probe():
    from src.context.model_budgets import _PROBES, _effective_provider

    assert _effective_provider("velona") == "velona"
    assert "velona" in _PROBES


def test_unknown_provider_still_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_llm("definitely-not-a-provider", "m")
