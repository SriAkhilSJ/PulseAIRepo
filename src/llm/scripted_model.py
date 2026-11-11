"""Env-gated deterministic chat model for provider-free desktop qualification.

The desktop qualification needs to drive the REAL Agent Core pipeline (graph,
tool dispatch, SafeToolNode approval policy, mutation execution, bridge,
persistence) without a paid provider. This module is the single substitution
point: it implements the small chat-model surface the graph uses and returns a
scripted sequence of messages.

Safety:
- Active only when BOTH ``CRUSORAI_TEST_MODE=1`` and
  ``CRUSORAI_TEST_LLM_SCRIPT`` (inline JSON) are set. Unset in normal runs.
- No network, no SDK, no credentials.
- After the script is exhausted it returns a plain text completion, never a
  repeated tool call, so a turn cannot loop on the fake.
"""
from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk

# A graph turn asks the factory for a model client more than once. Each client
# must continue the SAME script, not restart it, or the turn repeats step 1.
# Cursor is keyed by script identity + session/turn metadata from the gateway.
_SCRIPT_CURSORS: dict[str, int] = {}


class ScriptedChatModel:
    """Minimal deterministic chat model returning a fixed message sequence."""

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self._steps = list(steps)
        self._last_chunks: list[str] = []
        self._script_key = json.dumps(self._steps, sort_keys=True, ensure_ascii=False)
        self.model_name = "scripted-deterministic"
        self.model = self.model_name

    # --- binding surface the graph calls --------------------------------
    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def bind(self, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def with_config(self, *args: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def with_retry(self, *args: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    # --- generation -----------------------------------------------------
    def _chunks_for(self, step: dict[str, Any]) -> list[str]:
        raw = step.get("chunks")
        if isinstance(raw, list) and raw:
            return [str(item) for item in raw]
        content = str(step.get("content") or "")
        return [content] if content else []

    def _cursor_key(self, config: Any) -> str:
        metadata: dict[str, Any] = {}
        if isinstance(config, dict):
            raw = config.get("metadata")
            if isinstance(raw, dict):
                metadata = raw
            configurable = config.get("configurable")
            if isinstance(configurable, dict):
                metadata = {**metadata, **configurable}
        identity = str(
            metadata.get("crusor_session_id")
            or metadata.get("thread_id")
            or metadata.get("crusor_turn_id")
            or metadata.get("crusor_task_id")
            or ""
        )
        return f"{self._script_key}:{identity}"

    def _next(self, config: Any = None) -> AIMessage:
        key = self._cursor_key(config)
        index = _SCRIPT_CURSORS.get(key, 0)
        if index < len(self._steps):
            step = self._steps[index]
            call_index = index
            _SCRIPT_CURSORS[key] = index + 1
        else:
            step = {"content": "Scripted turn complete."}
            call_index = -1
        tool_calls = []
        for i, call in enumerate(step.get("tool_calls") or []):
            if not isinstance(call, dict) or not isinstance(call.get("name"), str):
                continue
            tool_calls.append({
                "name": call["name"],
                "args": call.get("args") or {},
                "id": str(call.get("id") or f"call_scripted_{call_index}_{i}"),
                "type": "tool_call",
            })
        message = AIMessage(content=str(step.get("content") or ""), tool_calls=tool_calls)
        usage = step.get("usage")
        if isinstance(usage, dict):
            message.usage_metadata = {
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
            }
        self._last_chunks = self._chunks_for(step)
        # The graph only executes tool_calls when the provider signals
        # finish_reason=tool_calls; a real provider carries it in metadata.
        if tool_calls:
            message.response_metadata = {"finish_reason": "tool_calls"}
        return message

    @staticmethod
    def _callback_handlers(config: Any) -> list[Any]:
        if config is None:
            return []
        raw = config.get("callbacks") if isinstance(config, dict) else getattr(config, "callbacks", None)
        if raw is None:
            return []
        return list(raw) if isinstance(raw, (list, tuple)) else [raw]

    def _emit_stream(self, chunks: list[str], config: Any) -> bool:
        """Deliver provider-style token callbacks before the aggregate return."""
        emitted = False
        for handler in self._callback_handlers(config):
            callback = getattr(handler, "on_llm_new_token", None)
            if not callable(callback):
                continue
            for chunk in chunks:
                callback(chunk)
                emitted = True
        return emitted

    def invoke(self, messages: Any, config: Any = None, **kwargs: Any) -> AIMessage:
        if os.environ.get("CRUSORAI_TEST_LLM_DEBUG") == "1":
            import sys as _sys
            print(f"[scripted-model] invoke key={self._cursor_key(config)}", file=_sys.stderr, flush=True)
        message = self._next(config)
        self._emit_stream(getattr(self, "_last_chunks", []), config)
        return message

    def stream(self, messages: Any, config: Any = None, **kwargs: Any):
        message = self._next(config)
        chunks = getattr(self, "_last_chunks", [])
        if chunks and not message.tool_calls:
            for chunk in chunks:
                yield AIMessageChunk(content=chunk)
            return
        yield message

    def generate(self, messages: Any, **kwargs: Any):
        message = self._next()
        return type("GenerationResult", (), {"generations": [[type("Gen", (), {"message": message})()]]})()


def scripted_model_from_env() -> ScriptedChatModel:
    raw = os.environ.get("CRUSORAI_TEST_LLM_SCRIPT", "").strip()
    if not raw:
        raise RuntimeError("CRUSORAI_TEST_LLM_SCRIPT is empty")
    steps = json.loads(raw)
    if not isinstance(steps, list):
        raise RuntimeError("CRUSORAI_TEST_LLM_SCRIPT must be a JSON array of messages")
    return ScriptedChatModel(steps)


def scripted_model_active() -> bool:
    return (
        os.environ.get("CRUSORAI_TEST_MODE", "").strip() == "1"
        and bool(os.environ.get("CRUSORAI_TEST_LLM_SCRIPT", "").strip())
    )
