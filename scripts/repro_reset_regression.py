"""Repro: does _AbortState.reset() break the next sync invoke?

Sends up to 2 tiny requests through the engine's own client:
  1. baseline invoke (no reset) -> expect READY
  2. proxy._abort_state.reset() then invoke -> expect ??? (hypothesis:
     ValueError 'Sync client is not available...')
"""
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import settings  # noqa: F401  (loads .env)
from src.llm.factory import get_llm

provider = (settings.LLM_PROVIDER or "").strip().lower()
model = (settings.LLM_MODEL or "").strip()

llm = get_llm(provider, model, max_attempts=1, request_timeout=30.0)

t0 = time.monotonic()
try:
    reply = llm.invoke("Reply with only the single word READY.")
    print(f"BASELINE ok in {time.monotonic()-t0:.1f}s: {str(getattr(reply,'content',reply)).strip()[:40]!r}")
except Exception as exc:
    print(f"BASELINE FAIL {type(exc).__name__}: {str(exc)[:200]}")
    raise SystemExit(1)

print(f"client is None before reset: {llm._llm.client is None}")
llm._abort_state.reset()
print(f"client is None after reset: {llm._llm.client is None}")

t0 = time.monotonic()
try:
    reply = llm.invoke("Reply with only the single word READY.")
    print(f"POST-RESET ok in {time.monotonic()-t0:.1f}s: {str(getattr(reply,'content',reply)).strip()[:40]!r}")
except Exception as exc:
    print(f"POST-RESET FAIL {type(exc).__name__} after {time.monotonic()-t0:.1f}s")
    print(f"  {str(exc)[:300]}")
    raise SystemExit(2)

# Phase 3: the Esc cycle — abort() closes transports (incl. langchain-openai's
# lru-cached shared httpx client); reset() must evict + rebuild, not reuse it.
llm._abort_state.abort()
print("aborted (simulates Esc mid-turn)")
llm._abort_state.reset()
print("reset after abort done")

t0 = time.monotonic()
try:
    reply = llm.invoke("Reply with only the single word READY.")
    print(f"POST-ABORT-RESET ok in {time.monotonic()-t0:.1f}s: {str(getattr(reply,'content',reply)).strip()[:40]!r}")
except Exception as exc:
    print(f"POST-ABORT-RESET FAIL {type(exc).__name__} after {time.monotonic()-t0:.1f}s")
    print(f"  {str(exc)[:300]}")
    raise SystemExit(3)

print("ALL GREEN: baseline, reset, and abort-reset cycles all answer.")
