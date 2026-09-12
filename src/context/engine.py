"""Pluggable Context Engine ABC — Hermes parity for PulseAI.

Mirrors hermes agent/context_engine.py: ContextEngine(ABC) with token-state
contract, threshold, protect_first/last, sanitize_memory_context, and hooks:
should_compress, prune_tool_results_only, select_context, on_turn_complete.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

MEMORY_CONTEXT_MAX_CHARS = 6_000
_MEMORY_CONTEXT_HEAD_CHARS = 4_000
_MEMORY_CONTEXT_TAIL_CHARS = 1_500
_MEMORY_CONTEXT_TRUNCATION_MARKER = "\n...[memory provider context truncated]...\n"

def sanitize_memory_context(memory_context: str) -> str:
    try:
        from src.utils.redact import redact_sensitive_text
        sanitized = redact_sensitive_text(memory_context.strip(), force=True, redact_url_credentials=True)
    except Exception:
        sanitized = memory_context.strip()
    if len(sanitized) <= MEMORY_CONTEXT_MAX_CHARS:
        return sanitized
    return sanitized[:_MEMORY_CONTEXT_HEAD_CHARS] + _MEMORY_CONTEXT_TRUNCATION_MARKER + sanitized[-_MEMORY_CONTEXT_TAIL_CHARS:]

def automatic_compaction_status_message(engine: Any, *, phase: str, default_message: str, **context: Any) -> str | None:
    if not getattr(engine, "emit_automatic_compaction_status", True):
        return None
    formatter = getattr(engine, "get_automatic_compaction_status_message", None)
    if callable(formatter):
        message = formatter(phase=phase, default_message=default_message, **context)
    else:
        message = default_message
    if message is None:
        return None
    message = str(message).strip()
    return message or None


def _env_float(name: str, default: float) -> float:
    import os
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
        if 0 < v <= 1.0:
            return v
        # allow percent like 75 -> 0.75
        if 1 < v <= 100:
            return v / 100.0
    except Exception:
        pass
    return default

def _env_int(name: str, default: int) -> int:
    import os
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default

def load_model_thresholds_from_env() -> Dict[str, float]:
    """Load per-model threshold overrides from env.

    Env PULSEAI_MODEL_THRESHOLDS = JSON dict like:
      {"gpt-4o": 0.75, "openrouter:claude-3-5-sonnet": 0.6, "astra": 0.85}
    Also supports PULSEAI_THRESHOLD_PERCENT as global default override.
    """
    import json, os
    thresholds: Dict[str, float] = {}
    raw = os.environ.get("PULSEAI_MODEL_THRESHOLDS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for k, v in data.items():
                    try:
                        fv = float(v)
                        if fv > 1:
                            fv = fv / 100.0
                        if 0 < fv <= 1:
                            thresholds[str(k)] = fv
                    except Exception:
                        continue
        except Exception:
            # also support comma-separated key=val pairs: "gpt-4=0.8,claude=0.6"
            try:
                for part in raw.split(","):
                    if "=" not in part:
                        continue
                    k, v = part.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if not k or not v:
                        continue
                    fv = float(v)
                    if fv > 1:
                        fv = fv / 100.0
                    if 0 < fv <= 1:
                        thresholds[k] = fv
            except Exception:
                pass
    return thresholds

def load_proactive_prune_config_from_env() -> Dict[str, int]:
    return {
        "tokens": _env_int("PULSEAI_PROACTIVE_PRUNE_TOKENS", 0),
        "min_chars": _env_int("PULSEAI_PROACTIVE_PRUNE_MIN_CHARS", 8000),
        "min_reclaim": _env_int("PULSEAI_PROACTIVE_PRUNE_MIN_RECLAIM", 4096),
    }

def _model_threshold_key_rank(key: str, model: str, provider: str) -> tuple[int, int] | None:
    """Match rank for one model_thresholds key, or None when it does not apply.

    ``"<provider>:<substr>"`` keys apply only on that provider; bare keys apply
    on every route. Same slug means different windows on different routes
    (Codex caps Astra at 272K; OpenRouter serves full), so bare overrides leak.
    Rank = (substring length, scoped): most specific model match wins, scope breaks ties.
    Ported from hermes-agent context_compressor._model_threshold_key_rank (2026-09).
    """
    scope, sep, substr = key.partition(":")
    if not sep:
        return (len(key), 0) if key in model else None
    return (len(substr), 1) if scope.strip().lower() == provider and substr in model else None


def resolve_model_threshold(
    model: str | None,
    model_thresholds: Dict[str, float] | None,
    default: float,
    provider: str = "",
) -> float:
    """Resolve the effective compression threshold for a given model.

    Ported from hermes-agent ``context_compressor.resolve_model_threshold``
    (re-read at upstream ``4dac5f2`` + provider-scoped rank, 2026-09).
    ``model_thresholds`` maps substring keys to override fractions, optionally
    provider-scoped as ``"<provider>:<substr>"`` (scoped outranks bare of same
    length). LONGEST matching key wins (so ``"glm-5.2-1M"`` beats ``"glm-5.2"``).
    When no override matches, ``default`` is returned unchanged.

    Module-level so plugin context engines can reuse same resolution — same
    reason Hermes exposes it at module scope.
    """
    if not model_thresholds or not model:
        return default
    provider = (provider or "").strip().lower()
    ranked = ((_model_threshold_key_rank(key, model, provider), key) for key in model_thresholds)
    best = max(((rank, key) for rank, key in ranked if rank is not None), default=None)
    if best is not None:
        _, key = best
        return float(model_thresholds[key])
    return default

class ContextEngine(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    last_prompt_tokens: int = 0
    last_completion_tokens: int = 0
    last_total_tokens: int = 0
    threshold_tokens: int = 0
    context_length: int = 0
    compression_count: int = 0

    # Env-driven defaults — all values stored in env per user request
    # PULSEAI_THRESHOLD_PERCENT (0-1 or 0-100), default 0.75 for IDE
    # PULSEAI_PROTECT_LAST_N, PULSEAI_PROTECT_FIRST_N
    threshold_percent: float = 0.75
    protect_first_n: int = 3
    protect_last_n: int = 20  # IDE needs more recent turns than CLI's 6 — aligns with Hermes 20
    emit_automatic_compaction_status: bool = True

    # Proactive prune: deterministic tool-result pruning at low trigger (Hermes parity)
    # All via env: PULSEAI_PROACTIVE_PRUNE_TOKENS, _MIN_CHARS, _MIN_RECLAIM
    proactive_prune_tokens: int = 0
    proactive_prune_min_result_chars: int = 8000
    proactive_prune_min_reclaim_tokens: int = 4096

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Apply env overrides once per subclass creation so instances pick them up
        cls.threshold_percent = _env_float("PULSEAI_THRESHOLD_PERCENT", cls.threshold_percent)
        # protect_last_n via env
        try:
            import os
            raw = os.environ.get("PULSEAI_PROTECT_LAST_N", "").strip()
            if raw:
                cls.protect_last_n = int(raw)
            raw = os.environ.get("PULSEAI_PROTECT_FIRST_N", "").strip()
            if raw:
                cls.protect_first_n = int(raw)
        except Exception:
            pass
        # proactive prune via env helper
        cfg = load_proactive_prune_config_from_env()
        if cfg["tokens"]:
            cls.proactive_prune_tokens = cfg["tokens"]
        if cfg["min_chars"]:
            cls.proactive_prune_min_result_chars = cfg["min_chars"]
        if cfg["min_reclaim"]:
            cls.proactive_prune_min_reclaim_tokens = cfg["min_reclaim"]

    @abstractmethod
    def update_from_response(self, usage: Dict[str, Any]) -> None: ...

    @abstractmethod
    def should_compress(self, prompt_tokens: int = None) -> bool: ...

    def should_compress_info(self, prompt_tokens: int = None) -> tuple[bool, str | None]:
        return self.should_compress(prompt_tokens), None

    @abstractmethod
    def compress(self, messages: List[Dict[str, Any]], current_tokens: Optional[int] = None, focus_topic: Optional[str] = None, force: bool = False, memory_context: str = "") -> List[Dict[str, Any]]: ...

    def prune_tool_results_only(self, messages: List[Dict[str, Any]], current_tokens: int | None = None) -> tuple[List[Dict[str, Any]], int]:
        """Deterministic no-LLM prune gated on proactive_prune_tokens. Override in subclasses."""
        return messages, 0

    def select_context(self, request_messages: List[Dict[str, Any]], *, conversation_messages: List[Dict[str, Any]] = None, incoming_message: Dict[str, Any] = None, budget_tokens: int = 0) -> List[Dict[str, Any]] | None:
        return None

    def on_turn_complete(self, messages: List[Dict[str, Any]], usage: Dict[str, Any] = None, **kwargs: Any) -> None:
        return None

    def should_compress_preflight(self, messages: List[Dict[str, Any]]) -> bool:
        return False
    def should_defer_preflight_to_real_usage(self, rough_tokens: int) -> bool:
        return False
    def get_automatic_compaction_status_message(self, *, phase: str, default_message: str, **context: Any) -> str | None:
        if not self.emit_automatic_compaction_status:
            return None
        return default_message
    def has_content_to_compress(self, messages: List[Dict[str, Any]]) -> bool:
        return True
    def on_session_start(self, session_id: str, **kwargs) -> None: ...
    def on_session_end(self, session_id: str, messages: List[Dict[str, Any]]) -> None: ...
    def on_session_reset(self) -> None:
        self.last_prompt_tokens = 0; self.last_completion_tokens = 0; self.last_total_tokens = 0; self.compression_count = 0
        self._proactive_prune_rearm_tokens = 0
        # Reload env-driven thresholds on reset so env changes take effect without restart
        try:
            self.model_thresholds = {**getattr(self, "model_thresholds", {}), **load_model_thresholds_from_env()}
        except Exception:
            pass
    def get_tool_schemas(self) -> List[Dict[str, Any]]: return []
    def handle_tool_call(self, name: str, args: Dict[str, Any], **kwargs) -> str:
        import json; return json.dumps({"error": f"Unknown context engine tool: {name}"})
    def get_status(self) -> Dict[str, Any]:
        last_prompt = self.last_prompt_tokens if self.last_prompt_tokens > 0 else 0
        return {
            "last_prompt_tokens": last_prompt,
            "threshold_tokens": self.threshold_tokens,
            "context_length": self.context_length,
            "usage_percent": min(100, last_prompt / self.context_length * 100) if self.context_length else 0,
            "compression_count": self.compression_count,
            "threshold_percent": self.threshold_percent,
            "protect_last_n": self.protect_last_n,
            "proactive_prune_tokens": getattr(self, "proactive_prune_tokens", 0),
            "model_thresholds": getattr(self, "model_thresholds", {}),
            "env": {
                "PULSEAI_THRESHOLD_PERCENT": self.threshold_percent,
                "PULSEAI_MODEL_THRESHOLDS": load_model_thresholds_from_env(),
                "PULSEAI_PROACTIVE_PRUNE_TOKENS": getattr(self, "proactive_prune_tokens", 0),
            }
        }
    def update_model(self, model: str, context_length: int, base_url: str = "", api_key: str = "", provider: str = "", api_mode: str = "") -> None:
        self.context_length = context_length
        if not hasattr(self, "_config_threshold_percent"):
            self._config_threshold_percent = _env_float("PULSEAI_THRESHOLD_PERCENT", self.threshold_percent)
        # Merge env thresholds with instance thresholds — env wins
        try:
            env_thresholds = load_model_thresholds_from_env()
            merged = {**getattr(self, "model_thresholds", {}), **env_thresholds}
        except Exception:
            merged = getattr(self, "model_thresholds", {})
        self.model_thresholds = merged
        self._base_threshold_percent = resolve_model_threshold(
            model, merged,
            self._config_threshold_percent,
            provider,
        )
        self.threshold_percent = self._base_threshold_percent
        self.threshold_tokens = int(context_length * self.threshold_percent)
