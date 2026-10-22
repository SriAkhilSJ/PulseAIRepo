"""Dynamic model pricing — NO hardcoded prices, NO hardcoded model list.

The call ledger (call_ledger.py) needs a price per model id to turn token
counts into money. Prices live with the PROVIDER, not in this repo: every
OpenAI-compatible endpoint answers ``GET {base}/models`` and many (Velona,
OpenRouter-style gateways) include per-model pricing in that catalog.
This module fetches that catalog with the same credentials the engine
already uses (CUSTOM_BASE_URL / CUSTOM_API_KEY), tolerantly parses the
pricing shapes providers actually return, caches it for a day under the
telemetry dir, and resolves a rate for ANY model id the ledger meets —
exact id, vendor-prefixed (``z-ai/glm-5.3-flash`` vs ``glm-5.3-flash``),
or substring. Nothing about a specific provider or model is baked in;
the parser knows FIELD SHAPES, never values.

Layering (call_ledger.load_rate_card): manual rates (CRUSORAI_RATE_CARD
env / rates.json) override this dynamic catalog; a provider-reported
per-call cost in the response usage overrides both. When nothing is
known, cost stays honestly unknown.

Currency: taken from the catalog payload when present, else
CRUSORAI_PRICING_CURRENCY (e.g. ``INR`` for Velona's live INR pricing),
else ``USD``. Refresh is explicit (``--refresh-pricing``) or backgrounded
from record_call when the cache is stale — the model-call path never
blocks on a pricing fetch. Kill-switch: CRUSORAI_PRICING=off.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

_CACHE_FILE = "pricing-cache.json"
_ATTEMPT_FILE = "pricing-attempt.stamp"
_DEFAULT_TTL_S = 24 * 3600
_ATTEMPT_THROTTLE_S = 3600
_OFF_VALUES = {"off", "0", "false", "no"}
_refresh_in_flight = False


def pricing_enabled() -> bool:
    return os.environ.get("CRUSORAI_PRICING", "on").strip().lower() not in _OFF_VALUES


def provider_config() -> tuple[str, str]:
    """(base_url, api_key) from the engine's existing provider env."""
    base = (
        os.environ.get("CRUSORAI_PRICING_BASE_URL")
        or os.environ.get("CUSTOM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or ""
    ).rstrip("/")
    key = (
        os.environ.get("CRUSORAI_PRICING_API_KEY")
        or os.environ.get("CUSTOM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )
    return base, key


def _fallback_currency() -> str:
    return os.environ.get("CRUSORAI_PRICING_CURRENCY", "").strip() or "USD"


# --------------------------------------------------------------------------
# Catalog parsing — field shapes, never values
# --------------------------------------------------------------------------

_PER_1M_HINTS = ("per_1m", "per_million", "per-1m", "1m_tokens", "_1m", "per_m")
_INPUT_KEYS = ("input_per_1m", "input_price_per_1m", "prompt_per_1m", "prompt_price_per_1m",
               "input_price_per_million", "prompt_price_per_million", "input", "prompt", "input_price", "prompt_price")
_OUTPUT_KEYS = ("output_per_1m", "output_price_per_1m", "completion_per_1m", "completion_price_per_1m",
                "output_price_per_million", "completion_price_per_million", "output", "completion", "output_price", "completion_price")


def _as_float(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _pick(pricing: dict, keys: tuple[str, ...]) -> tuple[float | None, bool]:
    """(value, explicitly_per_1m) for the first known key present."""
    for key in keys:
        if key in pricing:
            number = _as_float(pricing.get(key))
            if number is not None:
                return number, any(hint in key for hint in _PER_1M_HINTS)
    return None, False


def _parse_entry(entry: dict, default_currency: str) -> tuple[str, dict] | None:
    if not isinstance(entry, dict):
        return None
    model_id = str(entry.get("id") or entry.get("model") or entry.get("name") or entry.get("slug") or "").strip()
    if not model_id:
        return None
    pricing = entry.get("pricing")
    pricing = pricing if isinstance(pricing, dict) else entry
    input_price, input_1m = _pick(pricing, _INPUT_KEYS)
    output_price, output_1m = _pick(pricing, _OUTPUT_KEYS)
    if input_price is None or output_price is None:
        return None
    # Scale: explicit per-1M keys are taken as-is. Bare prompt/completion
    # fields (OpenRouter convention) are per-TOKEN — unless the magnitude
    # is impossible per token (>= 0.01 would mean >= $10k per 1M tokens),
    # in which case the provider clearly quoted per-1M already.
    def _to_per_1m(value: float, explicit: bool) -> float:
        if explicit or value >= 0.01:
            return value
        return value * 1_000_000

    currency = str(
        (pricing.get("currency") if isinstance(pricing, dict) else None)
        or entry.get("currency")
        or default_currency
    )
    return model_id, {
        "input_per_1m": round(_to_per_1m(input_price, input_1m), 6),
        "output_per_1m": round(_to_per_1m(output_price, output_1m), 6),
        "currency": currency,
        "source": "provider-catalog",
    }


def parse_catalog(payload, default_currency: str = "") -> dict[str, dict]:
    """Parse a provider /models payload into {model_id: rate}. {} if the
    catalog carries no usable pricing (reported honestly upstream)."""
    currency = default_currency or _fallback_currency()
    entries: list = []
    if isinstance(payload, dict):
        currency = str(payload.get("currency") or currency)
        for key in ("data", "models", "result"):
            if isinstance(payload.get(key), list):
                entries = payload[key]
                break
        if not entries and ("pricing" in payload or "id" in payload):
            entries = [payload]
    elif isinstance(payload, list):
        entries = payload
    rates: dict[str, dict] = {}
    for entry in entries:
        parsed = _parse_entry(entry, currency)
        if parsed:
            model_id, rate = parsed
            rates[model_id] = rate
    return rates


# --------------------------------------------------------------------------
# Fetch + cache
# --------------------------------------------------------------------------

def _http_get_json(url: str, api_key: str, timeout: float) -> object:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - provider URL from founder env
        return json.loads(response.read().decode("utf-8", errors="replace"))


def candidate_urls(base: str) -> list[str]:
    """Where a provider may publish its priced catalog. {base}/models is
    the OpenAI-compatible standard; {origin}/api/v1/models is the
    OpenRouter-style gateway layout. Both are tried, first usable wins."""
    base = base.rstrip("/")
    urls = [base + "/models"] if base else []
    if base.endswith("/v1"):
        origin = base[: -len("/v1")]
        urls.append(origin + "/api/v1/models")
        urls.append(origin + "/api/models")
    return urls


def fetch_rates(base_url: str, api_key: str, timeout: float = 8.0) -> tuple[dict[str, dict], str]:
    """Fetch + parse the provider catalog. Returns (rates, source_url);
    rates is {} when the catalog carries no pricing. Raises on transport
    errors only for URLs that answered — callers decide how to report."""
    last_error: Exception | None = None
    for url in candidate_urls(base_url):
        try:
            payload = _http_get_json(url, api_key, timeout)
        except Exception as exc:  # try the next candidate layout
            last_error = exc
            continue
        rates = parse_catalog(payload)
        if rates:
            return rates, url
        last_error = ValueError(f"{url} answered but carried no parseable pricing")
    if last_error is not None:
        raise last_error
    raise ValueError("no provider base URL configured")


def cache_path(directory: str | None = None) -> str:
    from src.telemetry.call_ledger import telemetry_dir

    return os.path.join(directory or telemetry_dir(), _CACHE_FILE)


def load_cached_rates(directory: str | None = None) -> dict[str, dict]:
    try:
        with open(cache_path(directory), "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        rates = parsed.get("rates") if isinstance(parsed, dict) else None
        return rates if isinstance(rates, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _cache_age_s(directory: str | None) -> float | None:
    try:
        return time.time() - os.path.getmtime(cache_path(directory))
    except OSError:
        return None


def save_cache(rates: dict[str, dict], source: str, directory: str | None = None) -> None:
    try:
        path = cache_path(directory)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": source, "rates": rates},
                handle,
                indent=1,
            )
    except OSError:
        pass  # pricing is best-effort; never break the caller


def refresh(directory: str | None = None, timeout: float = 8.0) -> tuple[dict[str, dict], str]:
    """Synchronous refresh (CLI path). Raises with an honest reason."""
    base, key = provider_config()
    if not base or not key:
        raise ValueError(
            "provider not configured: set CUSTOM_BASE_URL + CUSTOM_API_KEY "
            "(or CRUSORAI_PRICING_BASE_URL + CRUSORAI_PRICING_API_KEY)"
        )
    rates, source = fetch_rates(base, key, timeout=timeout)
    if rates:
        save_cache(rates, source, directory=directory)
    return rates, source


def ensure_pricing_async(directory: str | None = None) -> None:
    """Background refresh when the cache is stale. Called per recorded
    call, so every check is a cheap stat; the fetch runs on a daemon
    thread, throttled to one attempt per hour. Never raises, never blocks."""
    global _refresh_in_flight
    if not pricing_enabled() or _refresh_in_flight:
        return
    try:
        age = _cache_age_s(directory)
        if age is not None and age < _DEFAULT_TTL_S:
            return
        attempt = os.path.join(directory or _default_dir(), _ATTEMPT_FILE)
        try:
            if time.time() - os.path.getmtime(attempt) < _ATTEMPT_THROTTLE_S:
                return
        except OSError:
            pass
        base, key = provider_config()
        if not base or not key:
            return
        os.makedirs(os.path.dirname(attempt), exist_ok=True)
        with open(attempt, "w", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return

    def _work() -> None:
        global _refresh_in_flight
        try:
            rates, source = fetch_rates(base, key, timeout=8.0)
            if rates:
                save_cache(rates, source, directory=directory)
        except Exception:
            pass
        finally:
            _refresh_in_flight = False

    _refresh_in_flight = True
    threading.Thread(target=_work, name="crusorai-pricing-refresh", daemon=True).start()


def _default_dir() -> str:
    from src.telemetry.call_ledger import telemetry_dir

    return telemetry_dir()


# --------------------------------------------------------------------------
# Resolution — any model id, no list baked in
# --------------------------------------------------------------------------

def resolve_rate(model: str, rates: dict[str, dict]) -> dict | None:
    """Exact id → bare name (vendor/model vs model) → substring, either way."""
    wanted = (model or "").strip().lower()
    if not wanted or not rates:
        return None
    lowered = {str(key).lower(): rate for key, rate in rates.items()}
    if wanted in lowered:
        return lowered[wanted]
    bare = wanted.rsplit("/", 1)[-1]
    for key, rate in lowered.items():
        if key.rsplit("/", 1)[-1] == bare:
            return rate
    for key, rate in lowered.items():
        if wanted in key or key in wanted:
            return rate
    return None
