"""Per-1M-token price table for the paper's cost equation: Σ tokens × cost/token.

Receipts already carry `estimated_cost_usd` from the engine; the table is the
fallback for receipts without cost and the source for cache-discounted math.
Override wholesale with CRUSORAI_OPS_PRICES (JSON: {"model-substring": [in, out, cache]}).
"""
from __future__ import annotations

import json
import os

# [input, output, cache-read] USD per 1M tokens.
DEFAULT_TABLE: dict[str, list[float]] = {
    "gemini": [1.25, 5.0, 0.31],
    "gpt-4o": [2.5, 10.0, 1.25],
    "gpt-4": [10.0, 30.0, 5.0],
    "o4": [1.1, 4.4, 0.275],
    "llama": [0.2, 0.6, 0.05],
    "qwen": [0.3, 1.2, 0.075],
    "deepseek": [0.27, 1.1, 0.07],
}
FALLBACK = [2.5, 10.0, 0.25]


def table() -> dict[str, list[float]]:
    raw = os.environ.get("CRUSORAI_OPS_PRICES", "").strip()
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                return {str(k): [float(x) for x in v] for k, v in loaded.items()}
        except Exception:
            pass
    return DEFAULT_TABLE


def prices_for(model: str) -> list[float]:
    model_l = (model or "").lower()
    for key, val in table().items():
        if key.lower() in model_l:
            return val
    return FALLBACK


def cost_usd(model: str, in_tok: int, out_tok: int, cache_tok: int) -> float:
    p_in, p_out, p_cache = prices_for(model)
    return (in_tok * p_in + out_tok * p_out + cache_tok * p_cache) / 1_000_000.0


def turn_cost(record: dict) -> float:
    eng = float(record.get("estimated_cost_usd") or 0.0)
    if eng > 0:
        return eng
    tokens = record.get("tokens") or {}
    return cost_usd(
        record.get("model", ""),
        int(tokens.get("input") or 0),
        int(tokens.get("output") or 0),
        int(tokens.get("cache") or 0),
    )
