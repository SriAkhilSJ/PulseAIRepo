#!/usr/bin/env python3
"""Live LLM lane verification: one tiny call per lane, keys never printed.

Runs on a machine with keys in env/.env (the sandbox has neither):

    python3 scripts/verify_llm.py                        # main + aux lanes
    python3 scripts/verify_llm.py --lane main            # main only
    python3 scripts/verify_llm.py --lane aux             # aux only
    python3 scripts/verify_llm.py --provider velona --model openai/gpt-4o-mini

Exit 0 = every checked lane answered; non-zero names the failing lane.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROMPT = "Reply with exactly: OK"


def _content_text(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts = [
            str(p.get("text", "")) if isinstance(p, dict) else str(p)
            for p in content
        ]
        content = " ".join(parts)
    return " ".join(str(content or "").split())


def _check(label: str, client) -> bool:
    inner = getattr(client, "_llm", client)
    model = getattr(inner, "model", None) or getattr(inner, "model_name", "?")
    base = str(getattr(inner, "openai_api_base", None) or getattr(client, "base_url", "?"))
    t0 = time.monotonic()
    try:
        response = client.invoke(PROMPT)
    except Exception as exc:  # noqa: BLE001 - the failure IS the report
        print(f"[verify] {label}: provider/model={model} base={base}")
        print(f"[verify] {label}: FAILED after {time.monotonic() - t0:.1f}s: {exc!r}")
        return False
    wall = time.monotonic() - t0
    print(f"[verify] {label}: provider/model={model} base={base}")
    print(f"[verify] {label}: OK in {wall:.1f}s reply={_content_text(response)[:120]!r}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify live LLM lanes.")
    parser.add_argument("--lane", choices=["main", "aux", "both"], default="both")
    parser.add_argument("--provider", default=None, help="Single custom check (needs --model).")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    from src.llm.factory import get_auxiliary_llm, get_llm

    ok = True
    if args.provider and args.model:
        ok &= _check(f"{args.provider}/{args.model}", get_llm(args.provider, args.model))
        return 0 if ok else 1

    if args.lane in {"main", "both"}:
        from src.config.settings import LLM_MODEL, LLM_PROVIDER

        ok &= _check(f"main ({LLM_PROVIDER}/{LLM_MODEL})", get_llm(LLM_PROVIDER, LLM_MODEL))
    if args.lane in {"aux", "both"}:
        aux = get_auxiliary_llm()
        ok &= _check(f"aux ({aux.provider}/{aux.model})", aux)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
