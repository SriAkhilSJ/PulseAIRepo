"""Token-estimate calibration (D6, 2026-10-31).

The problem
-----------
``token_budget.count_tokens`` resolves its encoder with
``tiktoken.encoding_for_model(model)`` — which only knows OpenAI models — and
falls back to ``cl100k_base``. Production runs on Velona/z-ai, Groq-hosted
Llama, Gemini and NVIDIA, whose vocabularies are NOT cl100k. The resulting
error is systematic per family (typically 10-25% on code-dense text), and it
propagates into every sizing decision: ``allocate_budget``'s task splits,
``assemble_hierarchical``'s fit test, ``compress_layer``'s truncation target,
and ``deduplicate_layers``' near-duplicate threshold.

The fix
-------
The provider already tells us the truth: ``usage.prompt_tokens``. We compare it
against our own estimate for the SAME request, keep an exponential moving
average of the ratio per model, and scale future estimates by it.

Calibration policy (deliberately conservative)
----------------------------------------------
* Only samples where estimate and bill describe the same thing are recorded.
  A tools-bound call bills the bound tool schemas too, which are not part of
  the message estimate — so callers must pass the schema term in. The ai_node
  wiring does exactly that, and skips sampling when it cannot.
* A factor is only APPLIED after ``MIN_SAMPLES`` observations, and is clamped
  to ``[MIN_FACTOR, MAX_FACTOR]`` so one pathological call cannot poison the
  budgets.
* Everything is best-effort: a failure here returns 1.0 (no scaling) and can
  never break a turn.
* ``CRUSORAI_TOKEN_CALIBRATION=off`` disables it entirely.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

MIN_SAMPLES = 3
ALPHA = 0.2
MIN_FACTOR = 0.5
MAX_FACTOR = 2.0
# Ignore absurd samples (a provider reporting a wildly different unit, or an
# estimate that lost most of the request) rather than learning from them.
_MIN_RATIO = 0.25
_MAX_RATIO = 4.0

_LOCK = threading.Lock()
_CACHE: dict[str, dict] | None = None


def _enabled() -> bool:
    raw = (os.environ.get("CRUSORAI_TOKEN_CALIBRATION", "1") or "").strip().lower()
    return raw not in {"0", "off", "false", "no"}


def _store_path() -> Path:
    override = os.environ.get("CRUSORAI_TOKEN_CALIBRATION_PATH")
    if override:
        return Path(override)
    home = os.environ.get("CRUSORAI_HOME") or str(Path.home() / ".crusorai")
    return Path(home) / "token_calibration.json"


def _norm(model: str | None) -> str:
    return (model or "").strip().lower() or "unknown"


def _load() -> dict[str, dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    data: dict[str, dict] = {}
    try:
        path = _store_path()
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8") or "{}")
            if isinstance(raw, dict):
                data = {k: v for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        data = {}
    _CACHE = data
    return data


def _flush(data: dict[str, dict]) -> None:
    try:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass  # calibration is telemetry; it never blocks a turn


def record_sample(
    model: str | None,
    estimated_tokens: int,
    actual_tokens: int,
) -> float | None:
    """Record one (estimate, bill) pair. Returns the new factor, or None."""
    if not _enabled():
        return None
    try:
        est = int(estimated_tokens or 0)
        act = int(actual_tokens or 0)
        if est < 200 or act <= 0:
            # Too small to be informative (message overhead dominates) or no
            # bill to compare against.
            return None
        ratio = act / est
        if not (_MIN_RATIO <= ratio <= _MAX_RATIO):
            return None
        key = _norm(model)
        with _LOCK:
            data = _load()
            entry = data.get(key) or {"factor": 1.0, "samples": 0}
            prev = float(entry.get("factor") or 1.0)
            if int(entry.get("samples") or 0) == 0:
                new = ratio
            else:
                new = prev * (1.0 - ALPHA) + ratio * ALPHA
            new = max(MIN_FACTOR, min(MAX_FACTOR, new))
            data[key] = {
                "factor": round(new, 4),
                "samples": int(entry.get("samples") or 0) + 1,
                "last_ratio": round(ratio, 4),
                "last_est": est,
                "last_actual": act,
                "updated_at": time.time(),
            }
            _flush(data)
            return new
    except Exception:
        return None


def calibration_factor(model: str | None) -> float:
    """Multiplier to apply to a raw estimate for ``model``. 1.0 = no scaling.

    Returns 1.0 until MIN_SAMPLES observations exist, so a single odd call
    never changes a budget.
    """
    if not _enabled():
        return 1.0
    try:
        with _LOCK:
            entry = _load().get(_norm(model))
        if not entry:
            return 1.0
        if int(entry.get("samples") or 0) < MIN_SAMPLES:
            return 1.0
        return max(MIN_FACTOR, min(MAX_FACTOR, float(entry.get("factor") or 1.0)))
    except Exception:
        return 1.0


def reset_for_tests() -> None:
    global _CACHE
    with _LOCK:
        _CACHE = {}
