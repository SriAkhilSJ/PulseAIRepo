"""Unit tests for Model Capability Adapter Layer (Decision D)."""
from __future__ import annotations

import pytest
from src.llm.capabilities import (
    get_model_capability_profile,
    normalize_llm_request_params,
)


def test_registered_model_profiles():
    glm = get_model_capability_profile("z-ai/glm-5.3-flash")
    assert glm["context_window"] == 1_048_576
    assert glm["max_output_tokens"] == 8192
    assert glm["supports_streaming"] is True

    mini = get_model_capability_profile("openai/gpt-4o-mini")
    assert mini["context_window"] == 128_000
    assert mini["max_output_tokens"] == 4096
    # GPT-4o-mini is configured for non-streaming to avoid chunk silence timeouts
    assert mini["supports_streaming"] is False
    assert mini["supports_reasoning_effort"] is False


def test_normalize_request_params_for_gpt_mini():
    mini = get_model_capability_profile("openai/gpt-4o-mini")
    raw_params = {
        "model": "openai/gpt-4o-mini",
        "reasoning_effort": "high",
        "max_tokens": 16000,
        "temperature": 0.2,
    }
    normalized = normalize_llm_request_params(mini, raw_params)

    # stream must be forced False
    assert normalized["stream"] is False
    # reasoning_effort must be stripped because model does not support it
    assert "reasoning_effort" not in normalized
    # max_tokens must be capped to model's maximum supported output tokens
    assert normalized["max_tokens"] == 4096
    assert normalized["temperature"] == 0.2


def test_normalize_request_params_for_glm_flash():
    glm = get_model_capability_profile("z-ai/glm-5.3-flash")
    raw_params = {
        "model": "z-ai/glm-5.3-flash",
        "max_tokens": 8192,
    }
    normalized = normalize_llm_request_params(glm, raw_params)

    assert normalized["stream"] is True
    assert normalized["max_tokens"] == 8192
