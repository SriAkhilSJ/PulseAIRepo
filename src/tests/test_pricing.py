"""Dynamic pricing pins (founder 2026-10-21: "setup dynamically add the
pricing for any model id — no hardcoding is needed").

The contract under test: prices come from the PROVIDER's catalog (or its
own per-call bill, or a manual override) — never from a price table in
this repo. The parser must tolerate the catalog shapes providers really
return, resolution must work for ANY model id, and unknown must stay
unknown rather than silently becoming a made-up number.
"""
from __future__ import annotations

import json

import pytest

from src.telemetry import call_ledger, pricing


# --------------------------------------------------------------------------
# Catalog parsing: shapes, never values
# --------------------------------------------------------------------------

def test_parse_openrouter_style_per_token_strings():
    payload = {"data": [
        {"id": "z-ai/glm-5.3-flash", "pricing": {"prompt": "0.0000005", "completion": "0.0000015"}},
        {"id": "openai/gpt-4o", "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
    ]}
    rates = pricing.parse_catalog(payload, default_currency="USD")
    assert rates["z-ai/glm-5.3-flash"]["input_per_1m"] == pytest.approx(0.5)
    assert rates["z-ai/glm-5.3-flash"]["output_per_1m"] == pytest.approx(1.5)
    assert rates["openai/gpt-4o"]["output_per_1m"] == pytest.approx(10.0)


def test_parse_explicit_per_1m_fields_are_not_rescaled():
    payload = {"models": [
        {"id": "some/model", "input_per_1m": 0.3, "output_per_1m": 1.2, "currency": "INR"},
    ]}
    rates = pricing.parse_catalog(payload)
    assert rates["some/model"]["input_per_1m"] == pytest.approx(0.3)
    assert rates["some/model"]["currency"] == "INR"


def test_parse_catalog_without_pricing_is_empty_not_invented():
    payload = {"data": [{"id": "a/b"}, {"id": "c/d", "pricing": {"prompt": "free"}}]}
    assert pricing.parse_catalog(payload) == {}


def test_candidate_urls_cover_compatible_and_gateway_layouts():
    assert pricing.candidate_urls("https://velona.example/v1") == [
        "https://velona.example/v1/models",
        "https://velona.example/api/v1/models",
        "https://velona.example/api/models",
    ]


# --------------------------------------------------------------------------
# Resolution: any model id
# --------------------------------------------------------------------------

_RATES = {
    "z-ai/glm-5.3-flash": {"input_per_1m": 0.5, "output_per_1m": 1.5, "currency": "INR"},
    "openai/gpt-4o": {"input_per_1m": 2.5, "output_per_1m": 10.0, "currency": "USD"},
}


def test_resolve_exact_bare_and_prefixed_ids():
    assert pricing.resolve_rate("openai/gpt-4o", _RATES)["input_per_1m"] == 2.5
    assert pricing.resolve_rate("glm-5.3-flash", _RATES) is _RATES["z-ai/glm-5.3-flash"]
    assert pricing.resolve_rate("z-ai/glm-5.3-flash", _RATES) is _RATES["z-ai/glm-5.3-flash"]


def test_resolve_unknown_model_stays_unknown():
    assert pricing.resolve_rate("nobody/never-heard-of-it-9", _RATES) is None
    assert pricing.resolve_rate("", _RATES) is None


# --------------------------------------------------------------------------
# Fetch + cache + ledger layering
# --------------------------------------------------------------------------

def test_refresh_caches_catalog_and_ledger_uses_it(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTOM_BASE_URL", "https://velona.example/v1")
    monkeypatch.setenv("CUSTOM_API_KEY", "test-key")
    monkeypatch.delenv("CRUSORAI_RATE_CARD", raising=False)
    monkeypatch.delenv("CRUSORAI_PRICING", raising=False)

    def fake_get(url, api_key, timeout):
        assert api_key == "test-key"
        return {"data": [{"id": "z-ai/glm-5.3-flash",
                          "pricing": {"prompt": "0.0000005", "completion": "0.0000015"},
                          "currency": "INR"}]}

    monkeypatch.setattr(pricing, "_http_get_json", fake_get)
    rates, source = pricing.refresh(directory=str(tmp_path))
    assert source.endswith("/v1/models") and "z-ai/glm-5.3-flash" in rates
    assert (tmp_path / "pricing-cache.json").is_file()

    # The ledger now prices calls with NO manual card anywhere.
    call_ledger.record_call(
        "t1", "custom", "z-ai/glm-5.3-flash", 1.0,
        input_tokens=1_000_000, output_tokens=1_000_000, total_tokens=2_000_000,
        directory=str(tmp_path),
    )
    summary = call_ledger.summarize(directory=str(tmp_path))
    assert summary["cost"] == pytest.approx(2.0)  # 0.5 in + 1.5 out
    assert summary["currency"] == "INR"


def test_manual_card_overrides_dynamic_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CRUSORAI_RATE_CARD",
        json.dumps({"glm": {"input_per_1m": 9.0, "output_per_1m": 9.0, "currency": "USD"}}),
    )
    pricing.save_cache(
        {"z-ai/glm-5.3-flash": {"input_per_1m": 0.5, "output_per_1m": 1.5, "currency": "INR", "source": "provider-catalog"}},
        "test", directory=str(tmp_path),
    )
    call_ledger.record_call(
        "t1", "custom", "z-ai/glm-5.3-flash", 1.0,
        input_tokens=1_000_000, output_tokens=0, total_tokens=1_000_000,
        directory=str(tmp_path),
    )
    summary = call_ledger.summarize(directory=str(tmp_path))
    assert summary["cost"] == pytest.approx(9.0), "founder's manual price must beat the catalog"
    assert summary["currency"] == "USD"


def test_provider_reported_cost_wins_over_every_card(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CRUSORAI_RATE_CARD",
        json.dumps({"glm": {"input_per_1m": 9.0, "output_per_1m": 9.0, "currency": "USD"}}),
    )
    call_ledger.record_call(
        "t1", "custom", "z-ai/glm-5.3-flash", 1.0,
        input_tokens=1_000_000, output_tokens=1_000_000, total_tokens=2_000_000,
        provider_cost=0.42, directory=str(tmp_path),
    )
    summary = call_ledger.summarize(directory=str(tmp_path))
    assert summary["cost"] == pytest.approx(0.42), "the provider's own bill is ground truth"


def test_fetch_raises_honestly_when_catalog_has_no_pricing(monkeypatch):
    monkeypatch.setattr(pricing, "_http_get_json", lambda url, key, timeout: {"data": [{"id": "a/b"}]})
    with pytest.raises(ValueError, match="no parseable pricing"):
        pricing.fetch_rates("https://x.example/v1", "k")


def test_cli_model_lookup_for_any_id(tmp_path, monkeypatch, capsys):
    pricing.save_cache(dict(_RATES), "test", directory=str(tmp_path))
    monkeypatch.delenv("CRUSORAI_RATE_CARD", raising=False)
    assert call_ledger.main(["--dir", str(tmp_path), "--model", "glm-5.3-flash"]) == 0
    out = capsys.readouterr().out
    assert "input 0.5/1M" in out and "INR" in out
    assert call_ledger.main(["--dir", str(tmp_path), "--model", "ghost/model-9"]) == 1
    assert "unknown" in capsys.readouterr().out
