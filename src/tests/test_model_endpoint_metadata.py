"""Ask the endpoint what it serves, the way Hermes does, before guessing.

Upstream `agent/model_metadata.py` reads twelve different field names out of the provider's own model
catalog and puts that answer ABOVE its hardcoded defaults (ladder step 2). Pulse probed three public
catalogs for one field name each, and had no path at all for `custom` -- Pulse's generic OpenAI-compatible
route, i.e. most self-hosted and router servers -- so an unrecognised model id fell to the 8,192 guess.
That guess produced a 4,096-token budget, a ~1,638-token context budget, and a `workspace exceeds scan
budget` refusal on a `hi` turn. The bound was honest; the number behind it was an assumption nobody asked
the provider about.

No network here: the catalog read is replaced and the 7-day disk cache is stubbed, so every test asserts
the parsing and the ladder order -- the parts that were missing.
"""
from __future__ import annotations

import pathlib

import pytest

from src.context import model_budgets as mb


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """No disk cache, no user override: the resolver's own rungs are what is under test."""

    monkeypatch.setattr(mb, "_write_cache", lambda *a, **k: None)
    monkeypatch.setattr(mb, "_cache_get", lambda *a, **k: None)
    monkeypatch.delenv("LLM_CONTEXT_WINDOW", raising=False)


def _catalog(monkeypatch, *entries):
    monkeypatch.setattr(mb, "_endpoint_catalog", lambda base: list(entries))


@pytest.mark.parametrize("key", mb._CONTEXT_LENGTH_KEYS)
def test_any_of_the_twelve_field_names_counts(key, monkeypatch):
    _catalog(monkeypatch, {"id": "my-model", key: 32_000})
    assert mb._probe_custom_endpoint("my-model") == 32_000


def test_a_string_number_and_a_nested_meta_block_are_both_understood(monkeypatch):
    _catalog(
        monkeypatch,
        {"id": "a", "n_ctx": "131072"},
        {"id": "b", "metadata": {"max_model_len": 65_536}},
    )
    assert mb._probe_custom_endpoint("a") == 131_072
    assert mb._probe_custom_endpoint("b") == 65_536


def test_booleans_are_not_windows(monkeypatch):
    # `max_position_embeddings: true` from a badly-behaved server must not become "1 token".
    _catalog(monkeypatch, {"id": "a", "max_position_embeddings": True})
    assert mb._probe_custom_endpoint("a") is None


def test_ids_match_across_prefixes_dates_and_quantisers():
    assert mb._model_id_matches("custom/llama-3.3-70b", "llama-3.3-70b")
    assert mb._model_id_matches("llama-3.3-70b", "meta-llama/llama-3.3-70b")
    assert mb._model_id_matches("gpt-4o", "gpt-4o-2024-11-20")
    assert not mb._model_id_matches("gpt-4o", "gpt-4o-mini")
    assert not mb._model_id_matches("gpt-4", "")


def test_the_endpoint_is_asked_before_the_static_table(monkeypatch):
    """`gpt-4` is in our table as 8,192; a server that says 128k for that id is believed."""

    import src.config.settings as settings

    monkeypatch.setattr(settings, "CUSTOM_BASE_URL", "http://127.0.0.1:8000/v1", raising=False)
    _catalog(monkeypatch, {"id": "gpt-4", "max_model_len": 128_000})
    window, source = mb.resolve_context_window("gpt-4", provider="custom")
    assert (window, source) == (128_000, "custom-api")


def test_a_known_model_still_answers_from_the_table_without_network():
    window, source = mb.resolve_context_window("gpt-4", provider="groq", allow_network=False)
    assert source == "static-table" and window == mb.MODEL_WINDOWS["gpt-4"]


def test_no_base_url_means_no_probe_and_the_old_default_still_applies(monkeypatch):
    import src.config.settings as settings

    monkeypatch.setattr(settings, "CUSTOM_BASE_URL", None, raising=False)
    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    window, source = mb.resolve_context_window("brand-new-model-xyz", provider="custom")
    assert source == "default"
    assert window == mb.MODEL_WINDOWS["default"]


def test_a_catalog_entry_with_no_window_field_does_not_lie(monkeypatch):
    import src.config.settings as settings

    monkeypatch.setattr(settings, "CUSTOM_BASE_URL", "http://127.0.0.1:8000/v1", raising=False)
    _catalog(monkeypatch, {"id": "brand-new-model-xyz"})
    window, source = mb.resolve_context_window("brand-new-model-xyz", provider="custom")
    assert source in ("static-table", "default")


def test_the_explicit_override_still_wins_over_the_endpoint(monkeypatch):
    import src.config.settings as settings

    monkeypatch.setattr(settings, "CUSTOM_BASE_URL", "http://127.0.0.1:8000/v1", raising=False)
    monkeypatch.setenv("LLM_CONTEXT_WINDOW", "200000")
    _catalog(monkeypatch, {"id": "m", "max_model_len": 32_000})
    window, source = mb.resolve_context_window("m", provider="custom")
    assert (window, source) == (200_000, "env-override")


def test_the_url_tolerates_a_base_that_already_carries_v1(monkeypatch):
    """`CUSTOM_BASE_URL` is whatever the OpenAI client was given; both shapes are common."""

    seen: list[str] = []

    def fake_get(url, headers=None):
        seen.append(url)
        return {"data": [{"id": "m", "max_model_len": 16_384}]}

    monkeypatch.setattr(mb, "_http_get_json", fake_get)
    assert mb._endpoint_catalog("http://host:8000/v1/") == [{"id": "m", "max_model_len": 16_384}]
    assert seen == ["http://host:8000/v1/models"], seen

    seen.clear()
    assert mb._endpoint_catalog("http://host:8000")
    assert seen == ["http://host:8000/v1/models"], seen


def test_the_shipped_default_is_auto_not_a_flat_pin():
    """The budget chain is only auto if the cap that sits on top of it is too.

    A 6,000 default used to pin max_tokens even when the endpoint had reported a real
    window, so the resolved number never reached the scan ceiling. AUTO (0) makes
    RetryLLMProxy._safe_limit and the engine derive the same figure from discovery.
    """

    import subprocess
    import sys

    here = str(pathlib.Path(__file__).resolve().parents[2])
    probe = (
        "import importlib, sys;"
        "sys.path.insert(0, %r);"
        "import src.config.settings as s;"
        "print(s.PROVIDER_SAFE_LIMIT)" % here
    )
    clean = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60)
    assert clean.stdout.strip() == "0", clean
    pinned = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
        env={**__import__("os").environ, "PROVIDER_SAFE_LIMIT": "6000"},
    )
    assert pinned.stdout.strip() == "6000", pinned
