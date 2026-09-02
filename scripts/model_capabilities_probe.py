"""What does my provider actually say about this model? Print it, don't guess.

Pulse now derives the context window from the endpoint's own `/models` metadata, the way Hermes does. If a turn
still reports `source: default`, that is a fact about the endpoint, not a bug to hunt through the engine -- this
script says which it is in one read: the URL asked, whether it answered, whether the configured id was found,
which of the twelve window keys the entry carries, and the budget the engine will therefore build.

Run from the repo root, on the same interpreter the app uses, so `.env` is read the same way:

    python scripts/model_capabilities_probe.py            # uses settings' provider + model
    python scripts/model_capabilities_probe.py --model gpt-4o --provider custom

Exits 0 either way: this is a report, not a gate.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# The twelve names Hermes accepts, mirrored so this report and the resolver cannot disagree.
from src.context.model_budgets import _CONTEXT_LENGTH_KEYS, MODEL_WINDOWS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="model id to look for (default: settings.LLM_MODEL)")
    parser.add_argument("--provider", default=None, help="provider name (default: settings.LLM_PROVIDER)")
    parser.add_argument("--json", action="store_true", help="dump the matched catalog entry verbatim")
    parser.add_argument("--fresh", action="store_true",
                        help="drop this provider+model entry from the 7-day on-disk cache first, so a stale "
                             "window cannot impersonate a live answer")
    args = parser.parse_args()

    from src.config import settings

    model = args.model or getattr(settings, "LLM_MODEL", "") or ""
    provider = args.provider or getattr(settings, "LLM_PROVIDER", "") or ""
    base_url = getattr(settings, "CUSTOM_BASE_URL", None) or ""
    api_key = getattr(settings, "CUSTOM_API_KEY", None) or ""

    print(f"provider       : {provider or '(unset)'}")
    print(f"model id       : {model or '(unset)'}")
    print(f"base url       : {base_url or '(unset -- custom probes are skipped)'}")
    print(f"api key        : {'present' if api_key else 'absent (endpoint may reject an anonymous /models)'}")

    if not base_url:
        print("\nNo CUSTOM_BASE_URL, so there is no endpoint to ask. The window comes from the table or the")
        print("8,192 fallback, and only LLM_MODEL / LLM_CONTEXT_WINDOW can change that. Nothing is broken;")
        print("the auto path simply does not apply to this provider.")
        return 0

    from src.context.model_budgets import _endpoint_catalog, _window_from_metadata

    normalized = base_url.strip().rstrip("/")
    url = f"{normalized}/models" if normalized.endswith("/v1") else f"{normalized}/v1/models"
    print(f"\nasking         : {url}")
    catalog = _endpoint_catalog(base_url)
    if not catalog:
        print("answer         : nothing usable. Either the route does not exist, it needs auth, or it")
        print("                 returned non-JSON. Providers are allowed to omit /models; this is the case")
        print("                 where naming LLM_MODEL is the real fix rather than a workaround.")
        return 0

    print(f"answer         : {len(catalog)} model(s) listed")
    ids = [str(e.get("id") or e.get("name") or "") for e in catalog]
    if model and model not in ids:
        print(f"note           : {model!r} is not an exact id here. Matching also tolerates provider prefixes,")
        print("                 :quant suffixes and date tails, so this may still resolve -- see the verdict.")
    if ids:
        print(f"first ids       : {', '.join(ids[:6])}{' ...' if len(ids) > 6 else ''}")

    matched = None
    for entry in catalog:
        from src.context.model_budgets import _model_id_matches

        if _model_id_matches(model, str(entry.get("id") or entry.get("name") or "")):
            matched = entry
            break

    print("\n-- what the endpoint reports --")
    if matched is None:
        print("no entry matched the configured model id")
    else:
        found = {k: matched[k] for k in _CONTEXT_LENGTH_KEYS if k in matched}
        print(json.dumps(found or {"(no window key present)": sorted(matched)[:8]}, indent=2)[:900])
        window = _window_from_metadata(matched)
        print(f"window from metadata: {window:,}" if window else "window from metadata: none -- see keys above")
        if args.json:
            print("\n-- raw entry --")
            print(json.dumps(matched, indent=2)[:2000])

    print("\n-- what the engine will use --")
    from src.context.model_budgets import resolve_context_window, usable_window_budget

    from src.context.model_budgets import _cache_path, _effective_provider, _read_cache
    cache_key = f"{_effective_provider(provider)}:{(model or '').strip().lower()}"
    cached = _read_cache().get(cache_key)
    if args.fresh and isinstance(cached, dict):
        data = _read_cache()
        data.pop(cache_key, None)
        try:
            with open(_cache_path(), "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            print(f"\ncleared cached entry {cache_key!r} (was {cached.get('window'):,}) -- asking live now")
            cached = None
        except OSError as exc:  # a read-only profile is not this script's problem to fix
            print(f"\ncould not clear the cache ({exc}); the cached value may still be reported")

    # endpoint_probe=True: this script exists to wait for the truth, unlike every production caller.
    resolved, source = resolve_context_window(
        model, provider=provider, allow_network=True, endpoint_probe=True
    )
    usable = usable_window_budget(resolved)
    safe_limit = int(getattr(settings, "PROVIDER_SAFE_LIMIT", 0) or 0)
    cap = usable if safe_limit <= 0 else min(usable, safe_limit)
    max_tokens = max(min(usable, cap), 4_096)
    print(f"window   : {resolved:,}  (source: {source})")
    print(f"usable   : {usable:,}")
    print(f"max_tokens: {max_tokens:,}   context_budget: {int(0.4 * max_tokens):,}")
    if source == "cache" and isinstance(cached, dict):
        age_h = (time.time() - float(cached.get("ts") or 0)) / 3600
        print(f"\nnote: this came from the on-disk cache, {age_h:.1f}h old, {int(cached.get('window') or 0):,} tokens"
              f"\n      ({_cache_path()}). A window cached from a previous endpoint or model swap will keep")
        print("      being trusted for 7 days -- re-run with --fresh to force a live ask before believing it.")
    if source == "default":
        print(f"\nThis is the assumed-window case: the fallback is {MODEL_WINDOWS['default']:,}, which is what")
        print("bounded the workspace scan on a greeting. PROVIDER_SAFE_LIMIT is AUTO"
              if safe_limit <= 0 else f"\nPROVIDER_SAFE_LIMIT={safe_limit:,} is capping the budget -- set it to 0 for AUTO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
