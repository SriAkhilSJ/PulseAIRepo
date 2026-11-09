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

from langchain_core.messages import AIMessage


class ScriptedChatModel:
    """Minimal deterministic chat model returning a fixed message sequence."""

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self._steps = list(steps)
        self._index = 0
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
    def _next(self) -> AIMessage:
        if self._index < len(self._steps):
            step = self._steps[self._index]
            call_index = self._index
            self._index += 1
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
        # The graph only executes tool_calls when the provider signals
        # finish_reason=tool_calls; a real provider carries it in metadata.
        if tool_calls:
            message.response_metadata = {"finish_reason": "tool_calls"}
        return message

    def invoke(self, messages: Any, config: Any = None, **kwargs: Any) -> AIMessage:
        if os.environ.get("CRUSORAI_TEST_LLM_DEBUG") == "1":
            import sys as _sys
            print(f"[scripted-model] invoke #{self._index}", file=_sys.stderr, flush=True)
        return self._next()

    def stream(self, messages: Any, config: Any = None, **kwargs: Any):
        yield self._next()

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
