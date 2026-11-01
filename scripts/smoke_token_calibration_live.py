#!/usr/bin/env python3
"""Live check of the D6 token-calibration path against a real provider.

What it proves (and nothing else):
  1. the configured key authenticates against the custom endpoint;
  2. the provider reports `usage.prompt_tokens` (without it, calibration has
     no ground truth and stays inert by design);
  3. our estimate and the provider's bill describe the same request closely
     enough to be worth learning from;
  4. `token_calibration` records samples and starts applying a factor.

It deliberately does NOT assert that the factor equals any particular number —
the point is that the estimator now LEARNS from the bill instead of assuming
cl100k for every model. A ratio near 1.0 across models is a valid result.

The key is never printed: only length and last four characters.

Usage:
  export CUSTOM_API_KEY='...'
  export CUSTOM_BASE_URL='https://velona.in/v1'
  python scripts/smoke_token_calibration_live.py
  python scripts/smoke_token_calibration_live.py --model z-ai/glm-5.3-flash

Exit codes: 0 pipeline verified, 1 a check failed, 2 no key configured.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Executed as `python scripts/...` the interpreter puts scripts/ on sys.path,
# not the repo root, so `import src...` fails — which is exactly how the first
# CI run failed. Make the repo importable regardless of the caller's cwd.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

UA = os.environ.get(
    "CRUSORAI_HTTP_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)
TIMEOUT = float(os.environ.get("VELONA_CHECK_TIMEOUT", "45"))
DEFAULT_BASE = "https://velona.in/v1"
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
SAMPLES = 3

# Code-dense text on purpose: that is where a cl100k fallback diverges most
# from a non-OpenAI vocabulary, so it is the honest probe for this defect.
_PROBE = (
    "def _resolve_bound_tools(state: dict, config: RunnableConfig) -> list:\n"
    "    names = config.get('configurable', {}).get('tool_names') or []\n"
    "    return [_TOOLS_BY_NAME[n] for n in names if n in _TOOLS_BY_NAME]\n"
) * 60


def _fingerprint(key: str) -> str:
    return f"len={len(key)} …{key[-4:]}" if len(key) >= 4 else f"len={len(key)}"


def _post(base: str, key: str, model: str, messages: list[dict]) -> dict:
    body = json.dumps(
        {"model": model, "messages": messages, "max_tokens": 8, "temperature": 0}
    ).encode()
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": UA,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL", DEFAULT_MODEL))
    args = ap.parse_args()

    key = (os.environ.get("CUSTOM_API_KEY") or "").strip()
    base = (os.environ.get("CUSTOM_BASE_URL") or DEFAULT_BASE).strip()
    if not key:
        print("no CUSTOM_API_KEY configured — nothing to check", file=sys.stderr)
        return 2

    print(f"[smoke] key {_fingerprint(key)} base={base} model={args.model}")

    try:
        from src.context.token_budget import count_tokens
        from src.context.token_calibration import (
            calibration_factor,
            record_sample,
            reset_for_tests,
        )
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke] FAIL: could not import the engine path: {exc!r}")
        return 1

    reset_for_tests()
    messages = [
        {"role": "system", "content": "You are a terse code assistant."},
        {"role": "user", "content": _PROBE},
    ]
    lc_messages = [
        SystemMessage(content=messages[0]["content"]),
        HumanMessage(content=messages[1]["content"]),
    ]

    failures: list[str] = []
    ratios: list[float] = []
    reported = 0

    for i in range(SAMPLES):
        estimate = count_tokens(lc_messages, args.model)
        try:
            t0 = time.time()
            data = _post(base, key, args.model, messages)
            elapsed = round(time.time() - t0, 2)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            print(f"[smoke] sample {i+1}: HTTP {exc.code} {detail}")
            failures.append(f"http_{exc.code}")
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"[smoke] sample {i+1}: transport error {exc!r}")
            failures.append("transport")
            continue

        usage = data.get("usage") or {}
        actual = int(usage.get("prompt_tokens") or 0)
        if not actual:
            failures.append("no_usage.prompt_tokens")
            print(f"[smoke] sample {i+1}: provider reported no prompt_tokens")
            continue

        reported += 1
        ratio = actual / estimate if estimate else 0.0
        ratios.append(ratio)
        record_sample(args.model, estimate, actual)
        print(
            f"[smoke] sample {i+1}: est={estimate:,} billed={actual:,} "
            f"ratio={ratio:.3f} ({elapsed}s)"
        )

    print()
    if reported == 0:
        print("[smoke] FAIL: no sample produced a provider-reported prompt_tokens")
        return 1

    factor = calibration_factor(args.model)
    mean_ratio = sum(ratios) / len(ratios)
    print(f"[smoke] samples reported: {reported}/{SAMPLES}")
    print(f"[smoke] mean ratio est→billed: {mean_ratio:.3f}")
    print(f"[smoke] applied calibration factor: {factor:.4f}")
    print(
        "[smoke] interpretation: factor is 1.0 until "
        f"{SAMPLES} samples exist; it now reflects the measured ratio — "
        "the estimator learns from the bill instead of assuming cl100k."
    )

    if failures:
        print(f"[smoke] FAIL: {sorted(set(failures))}")
        return 1

    assert factor != 0.0, "calibration produced a zero factor"
    print("[smoke] PASS: live provider usage drives token calibration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
