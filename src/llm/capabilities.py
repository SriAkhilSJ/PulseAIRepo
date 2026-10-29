"""Model Capability Registry and Request Normalization Adapter.

Implements Decision D & Refinement 3 of CrusorAI 2.0 Architecture:
1. Explicit capability profile per model/provider with origin source attribution.
2. Conservative bounds when provider capabilities cannot be verified online.
3. Centralized request parameter normalization.
"""
from __future__ import annotations

from typing import Any, Literal
from typing_extensions import TypedDict


CapabilitySource = Literal["pinned_catalog", "provider_metadata", "conservative_fallback"]


class ModelCapabilityProfile(TypedDict):
    model_id: str
    provider: str
    context_window: int
    max_output_tokens: int
    supports_streaming: bool
    supports_native_tool_calling: bool
    supports_reasoning_effort: bool
    default_reasoning_effort: str | None
    chunk_stall_timeout_s: int
    source: CapabilitySource


_CAPABILITY_REGISTRY: dict[str, ModelCapabilityProfile] = {
    "z-ai/glm-5.3-flash": {
        "model_id": "z-ai/glm-5.3-flash",
        "provider": "custom",
        "context_window": 1_048_576,
        "max_output_tokens": 8_192,
        "supports_streaming": True,
        "supports_native_tool_calling": True,
        "supports_reasoning_effort": True,
        "default_reasoning_effort": None,
        "chunk_stall_timeout_s": 180,
        "source": "pinned_catalog",
    },
    "deepseek/deepseek-v4.1-flash": {
        "model_id": "deepseek/deepseek-v4.1-flash",
        "provider": "custom",
        "context_window": 1_048_576,
        "max_output_tokens": 8_192,
        "supports_streaming": True,
        "supports_native_tool_calling": True,
        "supports_reasoning_effort": True,
        "default_reasoning_effort": None,
        "chunk_stall_timeout_s": 180,
        "source": "pinned_catalog",
    },
    "openai/gpt-4o-mini": {
        "model_id": "openai/gpt-4o-mini",
        "provider": "custom",
        "context_window": 128_000,
        "max_output_tokens": 4_096,
        # Buffered gateways require non-streaming for GPT models to avoid 35s chunk silence timeouts
        "supports_streaming": False,
        "supports_native_tool_calling": True,
        "supports_reasoning_effort": False,
        "default_reasoning_effort": "none",
        "chunk_stall_timeout_s": 180,
        "source": "pinned_catalog",
    },
}

_CONSERVATIVE_FALLBACK: ModelCapabilityProfile = {
    "model_id": "generic_fallback",
    "provider": "custom",
    "context_window": 32_000,      # Conservative fallback context
    "max_output_tokens": 2_048,    # Conservative output limit
    "supports_streaming": False,   # Conservative non-streaming default
    "supports_native_tool_calling": True,
    "supports_reasoning_effort": False,
    "default_reasoning_effort": None,
    "chunk_stall_timeout_s": 120,
    "source": "conservative_fallback",
}


def get_model_capability_profile(model_id: str, provider: str = "custom") -> ModelCapabilityProfile:
    """Retrieve the capability profile for a model with provenance tracking."""
    low_id = model_id.lower().strip()
    for key, profile in _CAPABILITY_REGISTRY.items():
        if key.lower() == low_id or low_id in key.lower():
            return dict(profile)  # type: ignore[return-value]

    fallback = dict(_CONSERVATIVE_FALLBACK)
    fallback["model_id"] = model_id
    fallback["provider"] = provider
    if "mini" in low_id:
        fallback["max_output_tokens"] = 4096
        fallback["context_window"] = 128_000
        fallback["supports_streaming"] = False
        fallback["source"] = "provider_metadata"
    elif "flash" in low_id:
        fallback["context_window"] = 1_048_576
        fallback["max_output_tokens"] = 8192
        fallback["supports_streaming"] = True
        fallback["source"] = "provider_metadata"
    return fallback  # type: ignore[return-value]


def normalize_llm_request_params(
    profile: ModelCapabilityProfile,
    base_params: dict[str, Any],
) -> dict[str, Any]:
    """Normalize parameters for provider invocation based on capability profile."""
    params = dict(base_params)

    # Apply streaming capability
    if not profile["supports_streaming"]:
        params["stream"] = False
    elif "stream" not in params:
        params["stream"] = True

    # Strip reasoning_effort if not supported
    if not profile["supports_reasoning_effort"]:
        params.pop("reasoning_effort", None)
    elif profile["default_reasoning_effort"]:
        params.setdefault("reasoning_effort", profile["default_reasoning_effort"])

    # Bound max_tokens to model ceiling
    requested_max = params.get("max_tokens")
    if requested_max is None or int(requested_max) > profile["max_output_tokens"]:
        params["max_tokens"] = profile["max_output_tokens"]

    return params
