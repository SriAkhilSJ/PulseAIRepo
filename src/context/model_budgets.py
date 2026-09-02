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
from typing import NamedTuple
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


def margin_for(window: int, max_output: int | None = None) -> int:
    """What we withhold from a window for the reply and for token-count divergence.

    With a stated cap we withhold that cap -- the provider's own number beats our estimate -- clamped
    between SAFETY_MARGIN and a quarter of the window so a generous claim cannot starve the context.
    Without one, the pre-existing heuristic applies unchanged, so nothing that works today moves.
    """
    heuristic = max(SAFETY_MARGIN, int(window * 0.05))
    if not max_output or window <= 0:
        return heuristic
    ceiling = max(SAFETY_MARGIN, int(window * _MAX_OUTPUT_RESERVATION_FRACTION))
    return max(SAFETY_MARGIN, min(int(max_output), ceiling))


def usable_window_budget(window: int, max_output: int | None = None) -> int:
    """The single budget formula shared by ContextEngine AND RetryLLMProxy
    (they must agree to the token).

    Margin = max(4096, 5% of window): the flat margin alone under-covers
    tokenizer divergence for models tiktoken doesn't natively know — our
    counting elsewhere is cl100k-based, and approximations scale with
    window size. 5% headroom price for never shipping an oversized payload.
    """
    if window <= 0:
        return _MIN_USABLE
    margin = margin_for(window, max_output)
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

# Hermes does not use one number per request, and neither do we now. Captured from
# agent/model_metadata.py @ 8cab422:
#   - `timeout=(5, 10)` -- "flat timeout=10 means urllib3 can block 10s per retry stage through
#     proxies that 403 CONNECT, ballooning to minutes (#46620). 5s connect / 10s read fails fast on
#     unreachable hosts."
#   - `_is_connect_timeout`: "Read timeouts are deliberately excluded: those mean the server
#     accepted the connection, which is the opposite of the blackhole this guards."
#   - `_ENDPOINT_BLACKHOLE_TTL_SECONDS = 30.0`, keyed host:port: a routable-but-dead address blackholes
#     TCP so "a probe waits out its full timeout instead of failing fast", and "the stalls stack into a
#     minute-long hang before the banner renders". Short-circuiting on a recorded observation "adds no
#     probe for callers or tests to mock, and it can only ever fire after a real timeout has already been
#     paid, so it cannot suppress a probe that would have worked."
#   - `_localhost_to_ipv4`: on Windows dual-stack machines `localhost` resolves to `::1` first and
#     "pays a ~2s IPv6 connect timeout before falling back to IPv4 when the local server only listens on
#     IPv4". Owner's engine is http://localhost:20128 -- part of his measured 5.1s is that penalty.
#   - `_ENDPOINT_PROBE_FAILURE_TTL_SECONDS = 300.0` vs 3600 for success: a failed verdict is remembered
#     only briefly, "so a transient failure (server starting up, key being fixed)" recovers in minutes
#     instead of pinning "undetected" for an hour.
_PROBE_CONNECT_TIMEOUT_S = 2.5   # nothing listening? find out fast
_PROBE_TIMEOUT_S = 2.5          # public catalogs: a slow answer means the internet is down
_ENDPOINT_TIMEOUT_S = 12.0       # the user's own server may be thinking about a big registry
_ENDPOINT_CONNECT_TIMEOUT_S = 5.0
_BLACKHOLE_TTL_S = 30.0
_FAILURE_TTL_S = 300.0

# In-process only, on purpose: a failure verdict must not survive to the next launch, and a disk entry
# would be indistinguishable from a real window in the JSON shape the loader reads.
_failures: dict[str, float] = {}
_blackholed: dict[str, float] = {}


def _host_key(base_url: str) -> str:
    """host:port for one server, so every probe path shares a verdict (Hermes _endpoint_host_key)."""
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return ""
    url = normalized if "://" in normalized else f"http://{normalized}"
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if not parsed.hostname:
            return ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return f"{parsed.hostname.lower()}:{port}"
    except (ValueError, TypeError):
        return ""


def _now() -> float:
    import time as _time
    return _time.monotonic()


def _is_blackholed(base_url: str) -> bool:
    key = _host_key(base_url)
    if not key:
        return False
    seen = _blackholed.get(key)
    if seen is None:
        return False
    if _now() - seen > _BLACKHOLE_TTL_S:
        _blackholed.pop(key, None)
        return False
    return True


def _note_blackhole(base_url: str) -> None:
    key = _host_key(base_url)
    if key:
        _blackholed[key] = _now()


def _is_connect_timeout(exc: BaseException) -> bool:
    """Connect-phase only. A read timeout means the server is alive and slow -- the opposite case."""
    try:
        import httpx
        if isinstance(exc, httpx.ConnectTimeout) or isinstance(exc, httpx.ConnectError):
            return True
    except Exception:
        pass
    return False


def _remember_failure(cache_key: str) -> None:
    if cache_key:
        _failures[cache_key] = _now()


def _failure_is_fresh(cache_key: str) -> bool:
    seen = _failures.get(cache_key)
    if seen is None:
        return False
    if _now() - seen > _FAILURE_TTL_S:
        _failures.pop(cache_key, None)
        return False
    return True


def _localhost_to_ipv4(url: str) -> str:
    """Probe 127.0.0.1 instead of `localhost` -- skips the Windows dual-stack IPv6 penalty."""
    if not url or not isinstance(url, str):
        return url
    from urllib.parse import urlparse, urlunparse
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if (parsed.hostname or "").lower() != "localhost":
        return url
    netloc = parsed.netloc.replace("localhost", "127.0.0.1", 1)
    return urlunparse(parsed._replace(netloc=netloc))



# A self-hosted router's catalog is not a small API call. Measured on the owner's box, localhost:20128
# answered /v1/models in 5.1s with 503 KB and 1,572 models; at the 2.5s public-catalog timeout the read
# was cut off, the catalog came back empty, and the engine reported that the endpoint "published no
# window" -- a conclusion that was really about our patience, not about his provider. Ask longer where
# the answer is a whole registry; keep the short budget for the big public catalogs, which are fast and
# whose slowness means the internet is down rather than that a model list is big.
_ENDPOINT_TIMEOUT_S = 12.0
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


def _write_cache(key: str, window: int, max_output: int | None = None) -> None:
    """Best-effort cache write; a cache failure must never break resolution."""
    try:
        data = _read_cache()
        entry: dict = {"window": window, "ts": time.time()}
        if max_output:
            # Written only when the provider actually stated it: an absent key is the same shape as an
            # entry cached before this existed, and both must fall back to the heuristic, not to zero.
            entry["max_output"] = int(max_output)
        data[key] = entry
        os.makedirs(os.path.dirname(_cache_path()), exist_ok=True)
        with open(_cache_path(), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def _cache_limits_get(key: str) -> tuple[int, int | None, bool] | None:
    """(window, max_output, is_fresh) or None.

    Entries written before the reply cap existed simply carry no `max_output` key, and that must read as
    "unknown" -- falling back to the heuristic margin -- rather than as zero, which would reserve
    nothing and start sending oversized payloads again.
    """
    entry = _read_cache().get(key)
    if not isinstance(entry, dict):
        return None
    window = entry.get("window")
    ts = entry.get("ts", 0)
    if not isinstance(window, int) or window <= 0:
        return None
    cap = entry.get("max_output")
    if not isinstance(cap, int) or cap <= 0:
        cap = None
    return window, cap, (time.time() - ts) < _CACHE_TTL_S


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


def _http_get_json(
    url: str,
    headers: dict | None = None,
    timeout: float | None = None,
    connect_timeout: float | None = None,
    base_url: str = "",
) -> dict | None:
    """GET JSON with a HARD deadline. Any failure -> None (callers degrade, never crash).

    Two budgets, not one: `connect_timeout` is how long we wait to learn whether anything is there,
    `timeout` is how long we let a live server think. Collapsing them is what made a 5.1s catalog look
    like an endpoint that publishes no window, and letting a dead host charge both is what turns a
    startup into a minute of stalls. `base_url` is the blackhole key when it differs from `url`.
    """
    read_timeout = timeout or _PROBE_TIMEOUT_S
    conn = _PROBE_CONNECT_TIMEOUT_S if connect_timeout is None else connect_timeout
    try:
        import httpx
        resp = httpx.get(
            _localhost_to_ipv4(url),
            headers=headers or {},
            timeout=httpx.Timeout(read_timeout, connect=min(conn, read_timeout)),
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        if _is_connect_timeout(exc):
            _note_blackhole(base_url or url)
            print(f"[model_budgets] {(_host_key(base_url or url) or 'endpoint')} refused or failed to connect; "
                  f"skipping it for {int(_BLACKHOLE_TTL_S)}s (a dead host must not be charged to every probe)")
        else:
            print(f"[model_budgets] {url} read timed out or failed ({type(exc).__name__}) -- the server is "
                  "alive, so this is NOT recorded as an unreachable endpoint")
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


# Hermes reads the OUTPUT cap off the same catalog object (agent/model_metadata.py @ 8cab422):
# "max_completion_tokens", "max_output_tokens", "max_tokens". It matters because the margin we
# subtract from a window is a reservation for the reply: guessing it costs context on big windows
# (5% of 1,048,576 is 52,428 tokens withheld from a model that only ever emits 8,192) and can
# under-reserve on small ones. One shared function below means the engine and the pre-send guard
# cannot disagree about it -- the invariant the usable-window docstring has always claimed.
_MAX_COMPLETION_KEYS = ("max_completion_tokens", "max_output_tokens", "max_tokens")

# A provider may claim it can emit 600k tokens on a 128k window; honouring that literally would
# starve the context we came here to build. Reserving a quarter of the window is the most we will
# give up, and the floor keeps the old heuristic from ever getting worse than it was.
_MAX_OUTPUT_RESERVATION_FRACTION = 0.25


def _max_output_from(entry: dict) -> int | None:
    for key in _MAX_COMPLETION_KEYS:
        value = entry.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            return value
    nested = entry.get("meta") or entry.get("metadata") or {}
    if isinstance(nested, dict):
        for key in _MAX_COMPLETION_KEYS:
            value = nested.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
    return None


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
    if _is_blackholed(base_url):
        return []
    probe_base = _localhost_to_ipv4(base)
    candidates = [
        f"{probe_base}/models" if probe_base.endswith("/v1")
        else f"{probe_base}/v1/models"
    ]
    if not probe_base.endswith("/v1"):
        candidates.append(f"{probe_base}/models")
    for url in candidates:
        data = _http_get_json(
            url,
            _endpoint_auth_headers(),
            timeout=_ENDPOINT_TIMEOUT_S,
            connect_timeout=_ENDPOINT_CONNECT_TIMEOUT_S,
            base_url=base_url,
        )
        if isinstance(data, dict):
            entries = data.get("data") or data.get("models") or []
            if isinstance(entries, list):
                return [e for e in entries if isinstance(e, dict)]
    return []


def _endpoint_auth_headers() -> dict:
    key = _settings_key("CUSTOM_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}


def probe_endpoint_limits(model_name: str) -> tuple[int, int | None] | None:
    """(window, max_output) from the endpoint's own catalog entry, or None.

    This is Hermes' ladder step 2 ("active endpoint metadata"), which sits ABOVE the
    hardcoded defaults: a self-hosted server knows its own `max_model_len` AND how much
    it is willing to emit, and both deserve to beat a table of cloud-model windows.
    Asking once for the pair is also why this function returns it together -- a caller that
    wanted the reply cap used to need a second HTTP round trip to get it.
    """
    try:
        from src.config.settings import CUSTOM_BASE_URL
        base_url = CUSTOM_BASE_URL or ""
    except Exception:
        base_url = os.getenv("CUSTOM_BASE_URL", "")
    if _is_blackholed(base_url):
        return None
    wanted = (model_name or "").strip()
    entries = _endpoint_catalog(base_url)
    for entry in entries:
        if _model_id_matches(wanted, str(entry.get("id") or entry.get("name") or "")):
            window = _window_from_metadata(entry)
            if window:
                return window, _max_output_from(entry)

    # Router aliases: `auto` names no model, it names a CHOOSER, and the catalog lists its options as
    # `auto/best-chat`, `auto/fast`, ... Exact matching alone left the owner's real setup -- which DOES
    # publish context_length -- resolving to nothing, and the workaround offered back to him was to
    # hardcode LLM_MODEL. That is the thing this file exists to avoid. The safe reading of an alias is
    # the smallest window among its candidates: the router may hand us any of them, so promising more
    # than the weakest would reintroduce the HTTP 400 this module was written against.
    prefix = wanted.lower().rstrip("/") + "/"
    candidates = [
        _window_from_metadata(e)
        for e in entries
        if str(e.get("id") or e.get("name") or "").strip().lower().startswith(prefix)
    ]
    usable_candidates = [w for w in candidates if w]
    if usable_candidates:
        chosen = min(usable_candidates)
        # The reply cap must come from the entry we actually chose, not from the first candidate the
        # loop happened to see -- an alias whose smallest window belongs to a different model than its
        # largest output would otherwise pair two models into one budget that neither supports.
        chosen_entry = next(
            (e for e in entries
             if str(e.get("id") or e.get("name") or "").strip().lower().startswith(prefix)
             and _window_from_metadata(e) == chosen),
            None,
        )
        print(
            f"[model_budgets] {wanted!r} is a router alias, not a model id: {len(usable_candidates)}"
            f" candidate(s) published, smallest window {chosen:,} taken so the budget holds for"
            " whichever one the router picks"
        )
        return chosen, _max_output_from(chosen_entry) if chosen_entry else None
    return None


def _probe_custom_endpoint(model_name: str) -> int | None:
    """Window only -- the shape callers (and tests) that don't care about the reply cap use."""
    limits = probe_endpoint_limits(model_name)
    return limits[0] if limits else None


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


# NOTE: `custom` is deliberately NOT listed here. Its catalog is the user's own server and can be
# slow (measured: 1,572 models, 503 KB, 5.1s), and every caller of resolve_context_window sits on a
# path somebody is waiting on -- engine construction, history shaping, the pre-send guard. So the
# slow ask has its own rung below and is driven from the engine's background warm-up thread; the
# three public catalogs above answer in well under a second and stay synchronous.
_PROBES = {
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


class BudgetLimits(NamedTuple):
    """What one resolution pass learns about a model, kept together on purpose.

    `window`, the reply cap the provider stated (None when it said nothing), the usable budget after
    the margin, and which rung answered. The triple exists so no caller can read the window and forget
    the cap: the engine's context and RetryLLMProxy's pre-send guard are then computed by the same
    function from the same numbers, which is the agreement this module has always claimed but only
    enforced by comment.
    """

    window: int
    max_output: int | None
    usable: int
    source: str


def resolve_budget(
    model_name: str | None,
    provider: str | None = None,
    allow_network: bool = True,
    endpoint_probe: bool = False,
) -> BudgetLimits:
    """Resolve window + reply cap + usable budget in one pass. See `_resolve_limits` for the ladder."""
    # No second request: resolve_context_window is the seam every caller (and every test) patches, and a
    # cap learned from the endpoint is written to the cache in the same pass that resolves the window, so
    # reading it back here costs nothing and cannot disagree with the window beside it.
    # Forwarded the way each caller already calls it: fakes that patch resolve_context_window with a
    # narrower signature stay valid, which matters more than tidiness here.
    if endpoint_probe:
        window, source = resolve_context_window(
            model_name, provider, allow_network, endpoint_probe=True
        )
    else:
        window, source = resolve_context_window(model_name, provider, allow_network)
    cap = max_output_for(model_name, provider)
    return BudgetLimits(window, cap, usable_window_budget(window, cap), source)


def max_output_for(model_name: str | None, provider: str | None = None) -> int | None:
    """The reply cap the endpoint stated for this model, or None.

    Cache-only by design. A second live ask would double the one cost this whole module is trying to
    avoid, and a cap that arrived on the background thread is already in the cache entry beside the
    window -- which is exactly the case this exists for.
    """
    raw = (model_name or "").strip().lower()
    if provider is None:
        try:
            from src.config.settings import LLM_PROVIDER
            provider = LLM_PROVIDER
        except Exception:
            provider = os.getenv("LLM_PROVIDER", "")
    norm = provider or ""
    key = f"{_effective_provider(norm)}:{raw}"
    entry = _cache_limits_get(key)
    return entry[1] if entry else None


def resolve_context_window(
    model_name: str | None,
    provider: str | None = None,
    allow_network: bool = True,
    endpoint_probe: bool = False,
) -> tuple[int, str]:
    """Resolve the context window dynamically. Returns (window, source).

    `source` says which rung of the chain answered — "env-override",
    "cache", "custom-api", "static-table", "<provider>-api", "cache-stale", or "default".

    `endpoint_probe` defaults to False on purpose. Asking the user's own server for its whole model
    registry costs seconds on a router, and the callers here are all blocking paths: engine init,
    history shaping, and RetryLLMProxy's pre-send guard. A bigger timeout in those places is only a
    longer freeze -- which is how a healthy localhost endpoint came to be reported as one that
    "publishes no window". The slow ask belongs to the engine's background warm-up, which writes the
    cache for the next build. A caller that is explicitly a diagnostic passes True.
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

    # 1) Explicit user override always wins. It states a window, not a reply cap, so the margin stays
    # the heuristic -- overriding one number must not silently invent the other.
    override = os.getenv("LLM_CONTEXT_WINDOW", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override), "env-override"

    # 2) Fresh cache: we've asked this provider before; trust it, cap included.
    cached = _cache_limits_get(cache_key)
    if cached and cached[2]:
        return cached[0], "cache"

    # 2b) A custom endpoint is authoritative about what it serves, so it is asked BEFORE the
    # table -- Hermes puts "active endpoint metadata" above the hardcoded defaults for this reason
    # (a vLLM exposing the id "gpt-4" may well serve 128k, and a table of cloud windows cannot know).
    if allow_network and endpoint_probe and provider == "custom":
        # A recent "asked and got nothing" is retried within minutes, not on every construction and not
        # never: Hermes caches a failed verdict for 300s against 3600 for a success, because "server
        # starting up, key being fixed" is a transient state, while a per-turn waterfall is a real cost.
        if not _failure_is_fresh(cache_key):
            limits = probe_endpoint_limits(raw)
            if limits:
                _failures.pop(cache_key, None)
                # Both numbers land in ONE entry: the background thread that finds them later, or a
                # cold start that asks now, leave the same pair for every reader of this cache key.
                _write_cache(cache_key, limits[0], limits[1])
                return limits[0], "custom-api"
            _remember_failure(cache_key)

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
                # Public catalogs here answer with a window only; the reply cap stays unknown, which is
                # the honest state, not a gap to paper over with a made-up number.
                _write_cache(cache_key, window)
                return window, f"{provider}-api"

    # 5) Stale cache beats nothing; otherwise conservative default.
    if cached:
        return cached[0], "cache-stale"
    return MODEL_WINDOWS["default"], "default"
