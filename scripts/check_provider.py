#!/usr/bin/env python3
"""CrusorAI — provider readiness check, run before a real turn.

The desktop app is a bad place to discover that a key is missing: the engine spawns,
the pane shows an error card, and the reason is several layers away from the symptom.
This script answers the question in one command, outside the app.

    python scripts/check_provider.py            # no network, no cost: what is configured
    python scripts/check_provider.py --live     # one real 2-token request

Resolved through ``src.config.settings``, so what it prints is what the engine sees —
including the part that surprises people: ``.env`` is loaded with ``override=True``, so a
key sitting in the repo-root ``.env`` *beats* one exported in your shell. If the app and
your terminal disagree, that file is why.

Secrets are never printed. The live probe is opt-in (``--live``) so that running this by
accident cannot spend anything, and it is the only path that imports the provider SDKs.
Exit code: 0 = ready, 1 = not ready.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Which variable each provider reads. `cheap` is the env-configured OpenAI-compatible
#: offload (a local server counts), `custom` is a named OpenAI-compatible endpoint.
KEY_VARS = {
    "groq": ("GROQ_API_KEY", None),
    "openai": ("OPENAI_API_KEY", None),
    "gemini": ("GEMINI_API_KEY", None),
    "nvidia": ("NVIDIA_API_KEY", None),
    "custom": ("CUSTOM_API_KEY", "CUSTOM_BASE_URL"),
    "cheap": ("CRUSORAI_CHEAP_API_KEY", "CRUSORAI_CHEAP_BASE_URL"),
}

#: Providers whose client the factory can actually build. Anything else is a typo in
#: LLM_PROVIDER, which otherwise fails deep inside the turn.
KNOWN_PROVIDERS = tuple(KEY_VARS)


def redact(value: str | None) -> str:
    """Show enough to tell two keys apart, never enough to use one."""
    if not value:
        return "(not set)"
    tail = value[-4:] if len(value) > 4 else ""
    return f"set, ...{tail} ({len(value)} chars)" if tail else "set (short!)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--live", action="store_true",
        help="send one tiny real request (costs a fraction of a cent) instead of only reporting config",
    )
    args = parser.parse_args()

    # Importing settings is what loads .env — in the same order the engine loads it.
    try:
        from src.config import settings
    except Exception as exc:  # pragma: no cover - a broken checkout, reported not traced
        print(f"FAIL  could not import src.config.settings: {exc}")
        return 1

    provider = (settings.LLM_PROVIDER or "").strip().lower()
    model = (settings.LLM_MODEL or "").strip()
    print(f"provider      : {provider or '(unset)'}")
    print(f"model         : {model or '(unset)'}")

    key_var, url_var = KEY_VARS.get(provider, (None, None))
    if key_var is None:
        print(f"known providers: {', '.join(KNOWN_PROVIDERS)}")
        print(f"FAIL  LLM_PROVIDER={provider!r} is not one of them — set it in {REPO_ROOT / '.env'}")
        return 1

    key = getattr(settings, key_var, None)
    print(f"{key_var:<14}: {redact(key)}")
    if url_var:
        base = getattr(settings, url_var, None) or ""
        print(f"{url_var:<14}: {base or '(not set)'}")

    env_file = REPO_ROOT / ".env"
    print(f".env file     : {'present' if env_file.is_file() else 'absent'} ({env_file})")
    print("                note: .env overrides exported variables (load_dotenv(override=True))")

    missing = []
    if not key:
        missing.append(key_var)
    if not model:
        missing.append("LLM_MODEL")
    if url_var and not (getattr(settings, url_var, None) or "").strip():
        missing.append(url_var)
    if missing:
        print(f"FAIL  missing: {', '.join(missing)}")
        print(f"      fill them in {env_file} (copy .env.example if it does not exist yet)")
        return 1

    if not args.live:
        print("ok    configuration is complete. Re-run with --live to prove the key works:")
        print("        python scripts/check_provider.py --live")
        return 0

    # --- the only network path -------------------------------------------------
    print("live  sending one 2-token request through the engine's own client ...")
    try:
        from src.llm.factory import get_llm
    except Exception as exc:
        print(f"FAIL  provider SDKs are not importable: {exc}")
        print("      run this with the engine's venv (python in the repo .venv), not a bare interpreter")
        return 1

    started = time.monotonic()
    try:
        llm = get_llm(provider, model, max_attempts=1, request_timeout=30.0)
        reply = llm.invoke("Reply with only the single word READY.")
        text = getattr(reply, "content", reply)
        elapsed = time.monotonic() - started
        preview = str(text).strip().replace("\n", " ")[:80]
        print(f"ok    {provider}/{model} answered in {elapsed:.1f}s: {preview!r}")
        print("      real turns will work in the app. Launch WITHOUT CRUSORAI_BRIDGE_RUNNER.")
        return 0
    except Exception as exc:  # noqa: BLE001 - classified below, never re-raised raw
        elapsed = time.monotonic() - started
        print(f"FAIL  {type(exc).__name__} after {elapsed:.1f}s")
        detail = str(exc).strip().replace("\n", " ")[:300]
        print(f"      {detail}")
        try:
            from src.llm.error_classifier import classify_api_error

            verdict = classify_api_error(exc, provider=provider, model=model)
            print(f"      classified as: {verdict.reason.value} (retryable={verdict.retryable})")
            if verdict.is_auth:
                print(f"      -> the key is wrong, expired, or belongs to another provider: {key_var}")
            elif verdict.billing_unverified:
                print("      -> the provider refused for billing/credit reasons. Check your plan balance.")
            elif verdict.status_code == 404:
                print(f"      -> the model id is likely wrong for this account: {model!r}")
        except Exception:  # pragma: no cover - classifier is best-effort
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
