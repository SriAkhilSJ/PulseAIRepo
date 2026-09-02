"""Model-aware context window budgets.

Replaces the historical hardcoded 8000-token cap in ContextEngine with a
per-model lookup, so a 128K/200K/1M-window model is not squeezed into the
same budget as gpt-3.5.

Matching is intentionally conservative:
- exact match first,
- then trailing date suffixes are stripped ("-20241022", "-2024-08-06",
  "-0613") and re-tried,
- then the LONGEST table key that is a proper name-prefix wins.

The longest-prefix rule matters: a naive startswith("gpt") style match once
handed gpt-4-0613 a 128K budget (real window: 8192) — a 16x overshoot that
providers answer with HTTP 400. Unknown models used to fall back to 8192 on purpose:
undershooting costs context, overshooting costs the whole request.

NOTE: this is the *model* window. The effective engine budget is further
capped by PROVIDER_SAFE_LIMIT (the pre-send token guard in RetryLLMProxy) —
see ContextEngine.__init__.
"""

from __future__ import annotations

import json
import os
import re
import time

MODEL_WINDOWS: dict[str, int] = {
    # Anthropic
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-7-sonnet": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-opus-4": 200_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 1_047_576,
    "gpt-4.1-mini": 1_047_576,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    # Google
    "gemini-1.5-pro": 1_048_576,
    "gemini-1.5-flash": 1_048_576,
    "gemini-2.0-flash": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
    "gemini-2.5-pro": 1_048_576,
    # Groq-hosted open models (documented 131072 context)
    "llama-3.3-70b-versatile": 131_072,
    "llama-3.1-8b-instant": 131_072,
    "gpt-oss-120b": 131_072,
    "gpt-oss-20b": 131_072,
    "mixtral-8x7b-32768": 32_768,
    # Sarvam AI (api.sarvam.ai) — sarvam-105b verified to accept ≥40k input;
    # registered conservatively inside verified territory so the context
    # engine uses the real window instead of the 8k unknown-model default.
    "sarvam-105b": 32_768,
    "sarvam-105b-conversations": 32_768,
    # Unknown / local / unverified: deliberately small.
    "default": 8_192,
}

# Reserve for the model's reply; never let the input budget eat the whole
# window, or completions get truncated (or rejected outright).
SAFETY_MARGIN = 4_096

# Never return less than this, even for tiny/unknown windows.
_MIN_USABLE = 4_096

_DATE_SUFFIX = re.compile(r"-(?:\d{8}|\d{4}-\d{2}-\d{2}|\d{4})$")


def _normalize(model_name: str) -> str:
    """Lowercase, strip whitespace, and drop a provider prefix.

    The repo's own LLM_MODEL default is provider-prefixed
    ("qwen/qwen3.6-27b"); openrouter-style names too. Without this, every
    prefixed name silently falls through to the 8192 default.
    """
    n = model_name.strip().lower()
    if "/" in n:
        n = n.rsplit("/", 1)[1]
    return n


def _table_lookup(model_name: str | None) -> int | None:
    """Static-table lookup; None when the model is genuinely unknown."""
    if not model_name:
        return None

    n = _normalize(model_name)

    # 1) exact
    if n in MODEL_WINDOWS:
        return MODEL_WINDOWS[n]

    # 2) strip trailing revision dates ("-20241022", "-2024-08-06", "-0613")
    stripped = n
    while True:
        new = _DATE_SUFFIX.sub("", stripped)
        if new == stripped:
            break
        stripped = new
        if stripped in MODEL_WINDOWS:
            return MODEL_WINDOWS[stripped]

    # 3) longest proper prefix ("gpt-4o-2024-08-06" -> "gpt-4o", NOT "gpt-4")
    best_key: str | None = None
    for key in MODEL_WINDOWS:
        if key == "default":
            continue
        if stripped == key or stripped.startswith(key + "-"):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    if best_key is not None:
        return MODEL_WINDOWS[best_key]

    return None


def model_window(model_name: str | None) -> int:
    """Static table only — no network. Unknown models get the safe default.

    For runtime-aware resolution (env override / cache / live provider
    probe), use resolve_context_window() instead.
    """
    found = _table_lookup(model_name)
    return found if found is not None else MODEL_WINDOWS["default"]


def usable_budget(model_name: str | None) -> int:
    """Window minus reply headroom — the most the input should ever use."""
    return max(model_window(model_name) - SAFETY_MARGIN, _MIN_USABLE)


def usable_window_budget(window: int) -> int:
    """The single budget formula shared by ContextEngine AND RetryLLMProxy
    (they must agree to the token).

    Margin = max(4096, 5% of window): the flat margin alone under-covers
    tokenizer divergence for models tiktoken doesn't natively know — our
    counting elsewhere is cl100k-based, and approximations scale with
    window size. 5% headroom price for never shipping an oversized payload.
    """
    if window <= 0:
        return _MIN_USABLE
    margin = max(SAFETY_MARGIN, int(window * 0.05))
    return max(window - margin, _MIN_USABLE)


# =====================================================================
# DYNAMIC CONTEXT-WINDOW DISCOVERY
# =====================================================================
#
# The static table above can't know every model — the repo's own default
# (e.g. "qwen/..." on Groq) isn't in anyone's hardcoded list. So at runtime
# we resolve the window through a priority chain:
#
#   1. LLM_CONTEXT_WINDOW env override          (user always wins)
#   2. fresh on-disk cache                      (no cold-boot network cost)
#   3. static table                             (zero network for known models)
#   4. LIVE provider probe                      (Groq/Gemini/OpenRouter expose it)
#   5. stale cache, else the conservative default
#
# OpenAI and Anthropic do NOT publish window sizes in their model APIs —
# for those providers the static table (step 3) is the authoritative source.
# Probes are read-only GET requests with a hard timeout; every failure
# degrades to the next rung, never to a crash.

_PROBE_TIMEOUT_S = 2.5
_CACHE_TTL_S = 7 * 24 * 3600


def _cache_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".pulseai", "model_windows.json")


def _read_cache() -> dict:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_cache(key: str, window: int) -> None:
    """Best-effort cache write; a cache failure must never break resolution."""
    try:
        data = _read_cache()
        data[key] = {"window": window, "ts": time.time()}
        os.makedirs(os.path.dirname(_cache_path()), exist_ok=True)
        with open(_cache_path(), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def _cache_get(key: str) -> tuple[int, bool] | None:
    """Return (window, is_fresh) or None."""
    entry = _read_cache().get(key)
    if not isinstance(entry, dict):
        return None
    window = entry.get("window")
    ts = entry.get("ts", 0)
    if not isinstance(window, int) or window <= 0:
        return None
    return window, (time.time() - ts) < _CACHE_TTL_S


def _http_get_json(url: str, headers: dict | None = None) -> dict | None:
    """GET JSON with a hard timeout. Any failure -> None (callers degrade)."""
    try:
        import httpx
        resp = httpx.get(url, headers=headers or {}, timeout=_PROBE_TIMEOUT_S)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _settings_key(name: str) -> str | None:
    """API key via settings first (.env is loaded there), raw env as fallback.

    Reading os.getenv directly here would silently skip probes for users who
    keep keys in .env without exporting them — same trap as the provider
    resolution once had, fixed the same way.
    """
    try:
        from src.config import settings
        value = getattr(settings, name, None)
    except Exception:
        value = None
    return value or os.getenv(name)


# ---------------------------------------------------------------------------
# Endpoint metadata, per Hermes (agent/model_metadata.py:728 @ 5f24f29)
# ---------------------------------------------------------------------------
# A provider describes its own limits, but not under one agreed key: an
# OpenAI-compatible server may say `max_model_len` (vLLM), `n_ctx` (llama.cpp),
# `context_length` (Groq, OpenRouter), `context_window`, or `max_position_embeddings`
# (Hugging Face text-generation-inference). Hermes reads all twelve; probing one
# field name per provider is why `custom` -- Pulse's generic OpenAI-compatible
# route, and therefore most self-hosted and router endpoints -- had no live path
# at all and fell to the 8,192 guess. That guess is what bounded the owner's
# workspace scan on a `hi` turn: window 8,192 -> budget 4,096 -> context budget
# ~1,638 -> "workspace exceeds scan budget - bounded by design".
_CONTEXT_LENGTH_KEYS = (
    "context_length",
    "context_window",
    "context_size",
    "max_context_length",
    "max_position_embeddings",
    "max_model_len",
    "max_input_tokens",
    "max_sequence_length",
    "max_seq_len",
    "n_ctx_train",
    "n_ctx",
    "ctx_size",
)

# The next rung, deliberately not taken here: Hermes also reads the OUTPUT cap off
# the same object (max_completion_tokens / max_output_tokens / max_tokens) instead of
# a flat reserve, where ours is SAFETY_MARGIN. Threading it through would change
# resolve_context_window's return shape for every caller and the budget tests, so it
# waits for a pass where those can move together -- an unused constant would only make
# it look done.


def _model_id_matches(wanted: str, candidate: str) -> bool:
    """Match a served model id to the configured name, tolerating routing styles.

    `custom/llama-3.3-70b`, `llama-3.3-70b:free`, and `llama-3.3-70b-20241001` are
    one model to a provider and must one to us: strip the provider prefix, the
    `:quant`/`:variant` suffix, and a trailing date -- the same normalisations
    Hermes applies before comparing ids.
    """
    if not candidate:
        return False
    left = _normalize(wanted)
    right = _normalize(candidate)
    if left == right:
        return True
    # Substring only in the specific direction that means "this entry serves that model":
    # a bare-name id whose tail is the date we dropped, or a prefixed id whose tail is the name.
    return (right.endswith("/" + left) or left.endswith("/" + right)
            or _DATE_SUFFIX.sub("", right) == left or _DATE_SUFFIX.sub("", left) == right)


def _window_from_metadata(entry: dict) -> int | None:
    """First positive integer under any of the twelve keys, in Hermes' order."""
    for key in _CONTEXT_LENGTH_KEYS:
        value = entry.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.strip().isdigit() and int(value) > 0:
            return int(value)
    nested = entry.get("meta") or entry.get("metadata") or {}
    if isinstance(nested, dict):
        for key in _CONTEXT_LENGTH_KEYS:
            value = nested.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
    return None


def _endpoint_catalog(base_url: str) -> list[dict]:
    """`{base}/models`, tolerating whether the configured base already carries /v1."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return []
    candidates = [f"{base}/models"] if base.endswith("/v1") else [f"{base}/v1/models", f"{base}/models"]
    for url in candidates:
        data = _http_get_json(url, _endpoint_auth_headers())
        if isinstance(data, dict):
            entries = data.get("data") or data.get("models") or []
            if isinstance(entries, list):
                return [e for e in entries if isinstance(e, dict)]
    return []


def _endpoint_auth_headers() -> dict:
    key = _settings_key("CUSTOM_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _probe_custom_endpoint(model_name: str) -> int | None:
    """Ask the endpoint we are about to send the turn to what it serves.

    This is Hermes' ladder step 2 ("active endpoint metadata"), which sits ABOVE the
    hardcoded defaults: a self-hosted server knows its own `max_model_len` and we
    should believe it over any table of cloud-model windows.
    """
    try:
        from src.config.settings import CUSTOM_BASE_URL
        base_url = CUSTOM_BASE_URL or ""
    except Exception:
        base_url = os.getenv("CUSTOM_BASE_URL", "")
    wanted = (model_name or "").strip()
    for entry in _endpoint_catalog(base_url):
        if _model_id_matches(wanted, str(entry.get("id") or entry.get("name") or "")):
            window = _window_from_metadata(entry)
            if window:
                return window
    return None


def _probe_groq(model_name: str) -> int | None:
    """Groq's /models objects carry a real `context_window` field."""
    api_key = _settings_key("GROQ_API_KEY")
    if not api_key:
        return None
    data = _http_get_json(
        "https://api.groq.com/openai/v1/models",
        {"Authorization": f"Bearer {api_key}"},
    )
    if not data:
        return None
    wanted = {model_name.strip().lower(), _normalize(model_name)}
    for m in data.get("data", []):
        if str(m.get("id", "")).lower() in wanted:
            window = m.get("context_window") or m.get("max_tokens")
            if isinstance(window, int) and window > 0:
                return window
    return None


def _probe_gemini(model_name: str) -> int | None:
    """Gemini's models.get returns `inputTokenLimit`."""
    api_key = _settings_key("GEMINI_API_KEY")
    if not api_key:
        return None
    data = _http_get_json(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_normalize(model_name)}?key={api_key}"
    )
    if not data:
        return None
    window = data.get("inputTokenLimit")
    return window if isinstance(window, int) and window > 0 else None


def _probe_openrouter(model_name: str) -> int | None:
    """OpenRouter's public catalog carries `context_length` (no auth needed)."""
    data = _http_get_json("https://openrouter.ai/api/v1/models")
    if not data:
        return None
    wanted = {model_name.strip().lower(), _normalize(model_name)}
    for m in data.get("data", []):
        if str(m.get("id", "")).lower() in wanted:
            window = m.get("context_length")
            if isinstance(window, int) and window > 0:
                return window
    return None


_PROBES = {
    "custom": _probe_custom_endpoint,
    "groq": _probe_groq,
    "gemini": _probe_gemini,
    "google": _probe_gemini,
    "openrouter": _probe_openrouter,
}


def _effective_provider(provider: str) -> str:
    """Recognize routed providers without changing the configured transport.

    OpenRouter is intentionally configured through Pulse's generic
    OpenAI-compatible ``custom`` route. Budget discovery still needs its public
    model catalog rather than the unknown-provider 8k fallback.
    """
    normalized = provider.strip().lower()
    if normalized in {"custom", "openai", "openai-compatible"}:
        try:
            from src.config.settings import CUSTOM_BASE_URL
            base_url = CUSTOM_BASE_URL or ""
        except Exception:
            base_url = os.getenv("CUSTOM_BASE_URL", "")
        try:
            from urllib.parse import urlparse
            host = (urlparse(base_url).hostname or "").lower()
        except ValueError:
            host = ""
        if host == "openrouter.ai" or host.endswith(".openrouter.ai"):
            return "openrouter"
    return normalized


def resolve_context_window(
    model_name: str | None,
    provider: str | None = None,
    allow_network: bool = True,
) -> tuple[int, str]:
    """Resolve the context window dynamically. Returns (window, source).

    `source` says which rung of the chain answered — "env-override",
    "cache", "static-table", "<provider>-api", "cache-stale", or "default".
    """
    raw = (model_name or "").strip().lower()
    if provider is None:
        # Go through settings (not raw env): its .env loading AND its
        # "groq" default must apply here, or an unset env var silently
        # disables the probe while the LLM factory happily uses Groq.
        try:
            from src.config.settings import LLM_PROVIDER
            provider = LLM_PROVIDER
        except Exception:
            provider = os.getenv("LLM_PROVIDER", "")
    provider = _effective_provider(provider)
    cache_key = f"{provider}:{raw}"

    # 1) Explicit user override always wins.
    override = os.getenv("LLM_CONTEXT_WINDOW", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override), "env-override"

    # 2) Fresh cache: we've asked this provider before; trust it.
    cached = _cache_get(cache_key)
    if cached and cached[1]:
        return cached[0], "cache"

    # 2b) A custom endpoint is authoritative about what it serves, so it is asked BEFORE the
    # table -- Hermes puts "active endpoint metadata" above the hardcoded defaults for this reason
    # (a vLLM exposing the id "gpt-4" may well serve 128k, and a table of cloud windows cannot know).
    if allow_network and provider == "custom":
        endpoint_window = _probe_custom_endpoint(raw)
        if endpoint_window:
            _write_cache(cache_key, endpoint_window)
            return endpoint_window, "custom-api"

    # 3) Static table: zero network for models we already know.
    table = _table_lookup(model_name)
    if table is not None:
        return table, "static-table"

    # 4) Live provider probe (only for genuinely unknown models).
    if allow_network:
        probe = _PROBES.get(provider)
        if probe is not None:
            window = probe(raw)
            if window is not None:
                _write_cache(cache_key, window)
                return window, f"{provider}-api"

    # 5) Stale cache beats nothing; otherwise conservative default.
    if cached:
        return cached[0], "cache-stale"
    return MODEL_WINDOWS["default"], "default"
