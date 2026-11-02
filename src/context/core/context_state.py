"""
Context State — State Management and Lifecycle Tracking for Context Engine
==========================================================================

Owns workspace context, conversation context message transformations, state hashing,
differential cache tracking, frozen workspace snapshots, and session lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.context.bounded_scan import SCAN_SKIP_DIRS

# D26 (§44): keys the layer builders are allowed to depend on.
HASHED_STATE_KEYS: frozenset[str] = frozenset({
    "current_task", "latest_instruction", "user_interest", "workspace",
    "_autonomous_workspace",
    "plan", "plan_goal",
    "steps_completed", "failed_steps",
    "recovery_mode", "recovery_attempts", "recovery_command",
    "replan_count", "prior_attempts",
    "thread_id",
})


def hash_state(
    state: dict[str, Any],
    hashed_keys: frozenset[str] = HASHED_STATE_KEYS,
) -> str:
    """Hash ONLY the keys layers read (messages excluded by design;
    token_usage/execution_trace excluded as measured noise)."""
    payload = json.dumps(
        {k: str(state.get(k)) for k in sorted(hashed_keys)},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def workspace_exceeds_budget(workspace: str, cap: int) -> bool:
    """Bounded probe: does the workspace hold MORE entries than the scan
    budget could ever consider? Counting stops as soon as the total
    exceeds cap."""
    seen = 0
    roots = 0
    try:
        if os.path.isfile(workspace):
            return False
        for _root, dirs, files in os.walk(workspace):
            dirs[:] = [
                d for d in dirs
                if d not in SCAN_SKIP_DIRS and not d.startswith(".")
            ]
            seen += len(dirs) + len(files)
            roots += 1
            if seen > cap or roots > 2 * cap:
                break
    except Exception:
        return False
    return seen > cap


def wire_dicts_to_messages(dicts: List[Dict[str, Any]]) -> list[BaseMessage]:
    """Convert Hermes/OpenAI wire dicts ({role,type} + content) to LangChain messages."""
    role_map = {
        "human": HumanMessage, "user": HumanMessage,
        "ai": AIMessage, "assistant": AIMessage,
        "system": SystemMessage,
    }
    out: list[BaseMessage] = []
    for d in dicts:
        role = str(d.get("type") or d.get("role") or "human").lower()
        content = d.get("content", "")
        if role == "tool":
            out.append(ToolMessage(
                content=content,
                tool_call_id=str(d.get("tool_call_id") or d.get("id") or ""),
                name=str(d.get("name") or "tool"),
            ))
        else:
            cls = role_map.get(role, HumanMessage)
            msg = cls(content=content)
            if role in ("ai", "assistant") and d.get("tool_calls"):
                try:
                    msg.tool_calls = [
                        (
                            tc if isinstance(tc, dict)
                            else tc.model_dump()
                        )
                        for tc in d["tool_calls"]
                    ]
                except Exception:
                    pass
            out.append(msg)
    return out


class ContextState:
    """Tracks session-level and turn-level state for the Context Engine."""

    def __init__(self, thread_id: str | None = None):
        self.thread_id: str | None = thread_id
        self.active_thread_id: str | None = None
        self.active_workspace: str | None = None
        self.last_state_hash: Optional[str] = None
        self.active_state_hash: Optional[str] = None
        self.layer_cache: dict[str, Any] = {}
        self.current_task: Optional[str] = None
        self.last_layers_sent: list[str] = []

        self.frozen_workspace_snapshot: Dict[str, str] = {}
        self.frozen_workspace_cwd: str = ""

        self.cache_audit: Any = None
        self.prompt_cache_scope: str | None = None
        self.by_design_receipt_emitted: bool = False
        self.cache_break_receipt_emitted: bool = False

        self.active_pool: Any = None
        self.active_budget: Any = None

    def reset_session(self) -> None:
        """Reset state on session reset."""
        self.last_state_hash = None
        self.active_state_hash = None
        self.layer_cache.clear()
        self.current_task = None
        self.last_layers_sent.clear()
        self.frozen_workspace_snapshot.clear()
        self.frozen_workspace_cwd = ""
        self.cache_audit = None
        self.prompt_cache_scope = None
        self.by_design_receipt_emitted = False
        self.cache_break_receipt_emitted = False

    def invalidate_layer(self, name: str) -> None:
        """Evict one layer from the cache."""
        self.layer_cache.pop(name, None)

    def freeze_workspace_snapshot(self, cwd: str, content: str) -> None:
        """Pin workspace snapshot for prompt-cache stability."""
        try:
            key = f"{self.thread_id}:{cwd}"
            self.frozen_workspace_snapshot[key] = content
            self.frozen_workspace_cwd = cwd
        except Exception:
            pass

    def get_frozen_workspace_snapshot(self, cwd: str = "") -> str:
        cwd = cwd or self.frozen_workspace_cwd or "."
        key = f"{self.thread_id}:{cwd}"
        return self.frozen_workspace_snapshot.get(key, "")

    def hash_state(self, state: dict[str, Any]) -> str:
        return hash_state(state, HASHED_STATE_KEYS)


__all__ = [
    "HASHED_STATE_KEYS",
    "hash_state",
    "workspace_exceeds_budget",
    "wire_dicts_to_messages",
    "ContextState",
]
