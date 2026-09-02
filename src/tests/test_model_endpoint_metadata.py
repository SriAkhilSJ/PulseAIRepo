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

# Captured before the autouse fixture below replaces them: the cache round-trip test has to exercise the
# real writer, and the fixture that keeps every other test off the disk is exactly what would break it.
_REAL_WRITE_CACHE = mb._write_cache


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
    window, source = mb.resolve_context_window("gpt-4", provider="custom", endpoint_probe=True)
    assert (window, source) == (128_000, "custom-api")


def test_a_known_model_still_answers_from_the_table_without_network():
    window, source = mb.resolve_context_window("gpt-4", provider="groq", allow_network=False)
    assert source == "static-table" and window == mb.MODEL_WINDOWS["gpt-4"]


def test_no_base_url_means_no_probe_and_the_old_default_still_applies(monkeypatch):
    import src.config.settings as settings

    monkeypatch.setattr(settings, "CUSTOM_BASE_URL", None, raising=False)
    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    window, source = mb.resolve_context_window("brand-new-model-xyz", provider="custom", endpoint_probe=True)
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
    window, source = mb.resolve_context_window("m", provider="custom", endpoint_probe=True)
    assert (window, source) == (200_000, "env-override")


def test_the_url_tolerates_a_base_that_already_carries_v1(monkeypatch):
    """`CUSTOM_BASE_URL` is whatever the OpenAI client was given; both shapes are common."""

    seen: list[str] = []

    def fake_get(url, headers=None, timeout=None, **kwargs):
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


# ---------------------------------------------------------------------------
# The blocking-path decision, tested rather than asserted in a comment.
#
# Bumping the timeout alone was the tempting fix and the wrong one: 12s on a
# router turns "ask the provider" into "freeze app startup and every pre-send
# guard check". So the endpoint rung is off by default and reached from the
# engine's warm-up thread. These three tests pin that shape.
# ---------------------------------------------------------------------------

def test_the_default_resolution_never_touches_the_endpoint(monkeypatch):
    import src.config.settings as settings

    calls: list[str] = []
    monkeypatch.setattr(settings, "CUSTOM_BASE_URL", "http://127.0.0.1:8000/v1", raising=False)
    monkeypatch.setattr(mb, "_endpoint_catalog", lambda base: calls.append(base) or [])
    mb.resolve_context_window("some-unknown-model-abc", provider="custom")
    assert calls == [], "the blocking path must not ask the user's server anything"


def test_the_endpoint_gets_a_longer_budget_than_the_public_catalogs():
    """2.5s is right for a CDN-backed catalog and wrong for a 1,572-model localhost router."""

    assert mb._PROBE_TIMEOUT_S == 2.5
    assert mb._ENDPOINT_TIMEOUT_S > 5.0, "measured owner catalog: 5.1s -- anything under that is a false negative"


def test_the_catalog_uses_the_longer_budget(monkeypatch):
    seen: dict[str, object] = {}

    def fake_get(url, headers=None, timeout=None, connect_timeout=None, base_url="", **kwargs):
        seen["timeout"] = timeout
        seen["connect_timeout"] = connect_timeout
        seen["base_url"] = base_url
        return {"data": [{"id": "m", "max_model_len": 4_096}]}

    monkeypatch.setattr(mb, "_http_get_json", fake_get)
    assert mb._endpoint_catalog("http://host:8000/v1")
    assert seen["timeout"] == mb._ENDPOINT_TIMEOUT_S, seen
    # the blackhole key is the SERVER, so it must be passed the caller's base_url, not the probe URL
    assert seen["base_url"] == "http://host:8000/v1", seen
    assert seen["connect_timeout"] == mb._ENDPOINT_CONNECT_TIMEOUT_S, seen


def test_a_router_alias_resolves_to_the_smallest_window_it_could_be_handed(monkeypatch):
    """`auto` is a chooser, not a model. Owning that fact beats asking the user to pin an id.

    The owner's endpoint publishes `auto/best-chat` at 1,048,576 and would have matched nothing under
    `LLM_MODEL=auto`. Taking the MAX of an alias's candidates would be a lie the moment the router picks
    a small model, so the answer is the MIN: a budget every candidate can honour.
    """

    _catalog(
        monkeypatch,
        {"id": "auto/best-chat", "context_length": 1_048_576},
        {"id": "auto/fast", "context_length": 131_072},
        {"id": "unrelated/model", "context_length": 4_096},
    )
    assert mb._probe_custom_endpoint("auto") == 131_072


def test_an_alias_with_one_candidate_is_that_candidate(monkeypatch):
    _catalog(monkeypatch, {"id": "auto/best-chat", "context_length": 1_048_576})
    assert mb._probe_custom_endpoint("auto") == 1_048_576


def test_a_prefix_that_matches_nothing_still_refuses_to_guess(monkeypatch):
    _catalog(monkeypatch, {"id": "other/thing", "context_length": 1_048_576})
    assert mb._probe_custom_endpoint("auto") is None


# ---------------------------------------------------------------------------
# The reply cap. Hermes reads it from the same catalog object; we subtracted a guess instead.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", mb._MAX_COMPLETION_KEYS)
def test_the_reply_cap_is_read_under_each_of_the_three_names(key, monkeypatch):
    _catalog(monkeypatch, {"id": "m", "max_model_len": 131_072, key: 16_384})
    assert mb.probe_endpoint_limits("m") == (131_072, 16_384)


def test_no_cap_stated_means_no_cap_assumed(monkeypatch):
    _catalog(monkeypatch, {"id": "m", "max_model_len": 131_072})
    assert mb.probe_endpoint_limits("m") == (131_072, None)


def test_a_stated_reply_cap_never_touches_the_window_math():
    """The correction to a correction.

    An earlier test here asserted `usable == window - max_output`, i.e. it ENCODED the conflation
    upstream names as a bug (context_length is the TOTAL window; max_tokens is only what the reply may
    use). This test exists so the mistake cannot come back through the "safety margin" door: whatever the
    model can emit, the input budget is unchanged, because the provider enforces the sum.
    """

    window = 1_048_576
    heuristic = window - max(mb.SAFETY_MARGIN, int(window * 0.05))
    assert mb.usable_window_budget(window) == heuristic
    with pytest.raises(TypeError):
        mb.usable_window_budget(window, 512_000)


def test_a_small_window_still_floors_at_min_usable():
    assert mb.usable_window_budget(8_192) == mb._MIN_USABLE


def test_the_alias_pair_comes_from_the_entry_that_was_chosen(monkeypatch):
    """Picking the smallest window and the largest cap from two different models would invent a third."""

    _catalog(
        monkeypatch,
        {"id": "auto/best-chat", "context_length": 1_048_576, "max_tokens": 16_384},
        {"id": "auto/fast", "context_length": 131_072, "max_tokens": 4_096},
    )
    assert mb.probe_endpoint_limits("auto") == (131_072, 4_096)


def test_resolve_budget_reports_the_pair_and_the_number_everyone_spends(tmp_path, monkeypatch):
    """Needs a REAL cache: the cap reaches consumers through the entry the endpoint rung writes.

    The autouse fixture stubs the writer for every other test here (no disk in a unit test), so this one
    restores it against a temp file. That is not ceremony -- it is the actual mechanism: one live ask
    writes window + cap together, and every later reader, including the pre-send guard, gets both from
    that entry without asking anything again.
    """
    import src.config.settings as settings

    monkeypatch.setattr(settings, "CUSTOM_BASE_URL", "http://127.0.0.1:8000/v1", raising=False)
    monkeypatch.setattr(mb, "_cache_path", lambda: str(tmp_path / "model_windows.json"))
    monkeypatch.setattr(mb, "_write_cache", _REAL_WRITE_CACHE)
    _catalog(monkeypatch, {"id": "m", "max_model_len": 131_072, "max_completion_tokens": 32_768})
    limits = mb.resolve_budget("m", provider="custom", endpoint_probe=True)
    # The pair IS reported -- that is the point of fetching it -- and the budget is NOT derived from it.
    assert (limits.window, limits.max_output, limits.source) == (131_072, 32_768, "custom-api")
    assert limits.usable == 131_072 - max(mb.SAFETY_MARGIN, int(131_072 * 0.05))


def test_a_legacy_cache_entry_without_a_cap_falls_back_rather_than_reserving_zero(monkeypatch):
    """Entries written before this existed must not read as 'this model emits nothing'."""

    key = "custom:legacy-model"
    monkeypatch.setattr(mb, "_read_cache", lambda: {key: {"window": 65_536, "ts": mb_time()}})
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    window, cap, fresh = mb._cache_limits_get(key)
    assert (window, cap, fresh) == (65_536, None, True)
    assert mb.usable_window_budget(window) == 65_536 - max(mb.SAFETY_MARGIN, int(65_536 * 0.05))


def mb_time() -> float:
    import time
    return time.time()


def test_the_cap_survives_a_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "_cache_path", lambda: str(tmp_path / "model_windows.json"))
    monkeypatch.setattr(mb, "_write_cache", _REAL_WRITE_CACHE)
    mb._write_cache("custom:round-trip", 131_072, 8_192)
    assert mb._cache_limits_get("custom:round-trip") == (131_072, 8_192, True)
