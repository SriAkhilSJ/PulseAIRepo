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

    threshold_percent: float = 0.75
    protect_first_n: int = 3
    protect_last_n: int = 6
    emit_automatic_compaction_status: bool = True

    @abstractmethod
    def update_from_response(self, usage: Dict[str, Any]) -> None: ...

    @abstractmethod
    def should_compress(self, prompt_tokens: int = None) -> bool: ...

    def should_compress_info(self, prompt_tokens: int = None) -> tuple[bool, str | None]:
        return self.should_compress(prompt_tokens), None

    @abstractmethod
    def compress(self, messages: List[Dict[str, Any]], current_tokens: Optional[int] = None, focus_topic: Optional[str] = None, force: bool = False, memory_context: str = "") -> List[Dict[str, Any]]: ...

    def prune_tool_results_only(self, messages: List[Dict[str, Any]], current_tokens: int | None = None) -> tuple[List[Dict[str, Any]], int]:
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
    def get_tool_schemas(self) -> List[Dict[str, Any]]: return []
    def handle_tool_call(self, name: str, args: Dict[str, Any], **kwargs) -> str:
        import json; return json.dumps({"error": f"Unknown context engine tool: {name}"})
    def get_status(self) -> Dict[str, Any]:
        last_prompt = self.last_prompt_tokens if self.last_prompt_tokens > 0 else 0
        return {"last_prompt_tokens": last_prompt, "threshold_tokens": self.threshold_tokens, "context_length": self.context_length, "usage_percent": min(100, last_prompt / self.context_length * 100) if self.context_length else 0, "compression_count": self.compression_count}
    def update_model(self, model: str, context_length: int, base_url: str = "", api_key: str = "", provider: str = "", api_mode: str = "") -> None:
        self.context_length = context_length
        self.threshold_tokens = int(context_length * self.threshold_percent)
