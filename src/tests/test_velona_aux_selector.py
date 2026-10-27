from __future__ import annotations

import json

import pytest

from scripts import select_velona_aux as selector


def _entry(
    model: str,
    context: int | None,
    input_price: float,
    output_price: float,
    *,
    currency: str = "USD",
) -> dict:
    entry = {
        "id": model,
        "pricing": {
            "input_per_1m_usd": input_price,
            "output_per_1m_usd": output_price,
            "currency": currency,
        },
    }
    if context is not None:
        entry["context_window"] = context
    return entry


def _catalog() -> dict:
    return {
        "data": {
            "models": [
                _entry("z-ai/glm-5.3-flash", 262_144, 0.018, 0.121),
                _entry("small/cheap-but-short", 131_072, 0.001, 0.001),
                _entry("deepseek/deepseek-v4-flash", 1_310_720, 0.02, 0.20),
                _entry("qwen/qwen3.7-flash", 1_000_000, 0.03, 0.13),
            ]
        }
    }


def test_selects_cheapest_priced_model_at_or_above_one_million():
    receipt = selector.select_cheapest_aux(
        _catalog(), main_model="z-ai/glm-5.3-flash"
    )

    assert receipt["selected"] == {
        "model": "qwen/qwen3.7-flash",
        "context_window": 1_000_000,
        "input_per_1m": 0.03,
        "output_per_1m": 0.13,
        "equal_volume_per_1m": 0.16,
        "currency": "USD",
    }
    assert receipt["eligible_count"] == 2
    assert receipt["main"]["catalog_present"] is True


def test_short_or_unpriced_models_cannot_win():
    payload = _catalog()
    payload["data"]["models"].extend(
        [
            _entry("too-short", 999_999, 0.0, 0.0),
            {"id": "free-looking-but-unpriced", "context_window": 2_000_000},
        ]
    )

    receipt = selector.select_cheapest_aux(
        payload, main_model="z-ai/glm-5.3-flash"
    )

    assert receipt["selected"]["model"] == "qwen/qwen3.7-flash"
    assert {row["model"] for row in receipt["eligible"]} == {
        "qwen/qwen3.7-flash",
        "deepseek/deepseek-v4-flash",
    }


def test_required_main_model_must_be_live():
    with pytest.raises(selector.CatalogSelectionError, match="required main model"):
        selector.select_cheapest_aux(_catalog(), main_model="missing/main")


def test_does_not_compare_different_currencies():
    payload = _catalog()
    payload["data"]["models"][-1]["pricing"] = {
        "input_per_1m": 1.0,
        "output_per_1m": 2.0,
        "currency": "INR",
    }

    with pytest.raises(selector.CatalogSelectionError, match="across currencies"):
        selector.select_cheapest_aux(
            payload, main_model="z-ai/glm-5.3-flash"
        )


def test_live_fetch_skips_openai_catalog_without_context(monkeypatch):
    openai_shape = {
        "data": [
            {"id": "z-ai/glm-5.3-flash"},
            {"id": "qwen/qwen3.7-flash"},
        ]
    }
    seen = []

    def fake_get(url, key, timeout):
        seen.append((url, key, timeout))
        return _catalog() if "/gateway/" in url else openai_shape

    monkeypatch.setattr(selector.pricing, "_http_get_json", fake_get)
    receipt = selector.fetch_live_selection(
        base_url="https://velona.example/v1",
        api_key="secret-not-for-receipt",
        main_model="z-ai/glm-5.3-flash",
    )

    assert receipt["source_url"] == "https://velona.example/gateway/v1/models"
    assert receipt["selected"]["model"] == "qwen/qwen3.7-flash"
    assert all("secret-not-for-receipt" not in json.dumps(value) for value in receipt.values())
    assert len(seen) == 2


def test_github_env_contains_only_selected_public_metadata(tmp_path):
    receipt = selector.select_cheapest_aux(
        _catalog(), main_model="z-ai/glm-5.3-flash"
    )
    destination = tmp_path / "github-env"

    selector._append_github_env(destination, receipt)

    assert destination.read_text(encoding="utf-8") == (
        "AUX_LLM_MODEL=qwen/qwen3.7-flash\n"
        "VELONA_AUX_CONTEXT_WINDOW=1000000\n"
    )


def test_github_annotation_is_bounded_and_workflow_escaped(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    selector._github_annotation("notice", "AUX%", "line one\nline two")

    assert capsys.readouterr().out == (
        "::notice title=AUX%25::line one%0Aline two\n"
    )
