"""
Prompt-cache plan (P2 Hermes 4-breakpoint)
============================================
Port of hermes ``agent/prompt_caching.py`` 4-breakpoint ``build_prompt_cache_plan``
(static prefix + last tool + last 2 endpoints) into Pulse's LangChain
BaseMessage world. Pure functions, never raises, never touches provider
framing — only decorates ``additional_kwargs['cache_control']`` which the
failover stripper already knows how to remove.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, List

from src.context.prompt_cache_boundary import find_stable_prefix

_DEFAULT_CACHEABLE_PROVIDERS = frozenset({"openai","groq","gemini"})
_CACHE_BREAKPOINTS = 4
_TTL = "5m"
ALIBABA_FAMILY_PROVIDERS = frozenset({"opencode","opencode-zen","opencode-go","alibaba"})

def _cache_enabled(provider: str | None = None, model: str | None = None) -> bool:
    val = os.environ.get("PULSEAI_PROMPT_CACHE", "").strip().lower()
    if val not in ("1", "true", "yes", "on"):
        return False
    if provider and provider.strip().lower() in _DEFAULT_CACHEABLE_PROVIDERS:
        return True
    if provider and provider.strip().lower() == "custom":
        allow = os.environ.get("PULSEAI_PROMPT_CACHE_CUSTOM", "").strip().lower()
        return allow in ("1", "true", "yes", "on")
    return False

def _build_marker(ttl: str) -> Dict[str, str]:
    marker: Dict[str, str] = {"type": "ephemeral"}
    if ttl == "1h":
        marker["ttl"] = "1h"
    return marker

def is_qwen_model(model: str) -> bool:
    return "qwen" in (model or "").lower()

def effective_cache_ttl(ttl: str | None, *, model: str = "", provider: str = "") -> str:
    if ttl != "1h":
        return ttl or "5m"
    if is_qwen_model(model):
        return "5m"
    if (provider or "").lower() in ALIBABA_FAMILY_PROVIDERS:
        return "5m"
    return "1h"

def _copy_msg(msg: Any, **update) -> Any | None:
    try:
        return msg.model_copy(update=update)
    except Exception:
        pass
    try:
        return msg.copy(update=update)
    except Exception:
        return None

def _can_carry_marker_msg(msg: Any, native_anthropic: bool = False) -> bool:
    if native_anthropic:
        return True
    content = getattr(msg, "content", None)
    if content is None or content == "":
        return False
    if isinstance(content, list):
        return bool(content) and isinstance(content[-1], dict)
    return isinstance(content, str)

def _apply_cache_marker_msg(msg: Any, cache_marker: dict, native_anthropic: bool = False) -> Any | None:
    role = type(msg).__name__
    content = getattr(msg, "content", None)
    if content is None or content == "":
        if role == "ToolMessage" and not native_anthropic:
            return None
        if role == "AIMessage" and not native_anthropic:
            return None
        kw = dict(getattr(msg, "additional_kwargs", None) or {})
        kw["cache_control"] = dict(cache_marker)
        return _copy_msg(msg, additional_kwargs=kw)
    if isinstance(content, str):
        if role == "HumanMessage":
            stable = find_stable_prefix(content)
            if stable is not None:
                kw = dict(getattr(msg, "additional_kwargs", None) or {})
                kw["cache_control"] = dict(cache_marker)
                kw["_stable_prefix_len"] = len(stable)
                return _copy_msg(msg, additional_kwargs=kw)
        kw = dict(getattr(msg, "additional_kwargs", None) or {})
        kw["cache_control"] = dict(cache_marker)
        return _copy_msg(msg, additional_kwargs=kw)
    if isinstance(content, list) and content:
        new_content = list(content)
        last = new_content[-1]
        if isinstance(last, dict):
            new_last = dict(last)
            new_last["cache_control"] = dict(cache_marker)
            new_content[-1] = new_last
            return _copy_msg(msg, content=new_content)
    return None

def _completed_transaction_endpoint_indexes_msg(messages: List[Any], *, native_anthropic: bool = False) -> List[int]:
    endpoints: List[int] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        kind = type(msg).__name__
        if kind == "SystemMessage":
            i += 1
            continue
        tool_calls = getattr(msg, "tool_calls", None)
        if kind == "AIMessage" and tool_calls:
            result_start = i + 1
            result_end = result_start
            while result_end < len(messages) and type(messages[result_end]).__name__ == "ToolMessage":
                result_end += 1
            if result_end > result_start:
                endpoint = result_end - 1
                if _can_carry_marker_msg(messages[endpoint], native_anthropic):
                    endpoints.append(endpoint)
            i = result_end
            continue
        if kind == "ToolMessage":
            while i < len(messages) and type(messages[i]).__name__ == "ToolMessage":
                i += 1
            continue
        if kind == "HumanMessage" and i + 1 < len(messages):
            i += 1
            continue
        content = getattr(msg, "content", None)
        if kind == "AIMessage" and content in (None, ""):
            i += 1
            continue
        if _can_carry_marker_msg(msg, native_anthropic):
            endpoints.append(i)
        i += 1
    return endpoints

def _apply_system_cache_markers_msg(message: Any, cache_marker: dict, static_system_prefix: str | None, *, native_anthropic: bool = False, mark_suffix: bool = True, fallback_to_whole: bool = True) -> int:
    content = getattr(message, "content", None)
    if isinstance(static_system_prefix, str) and static_system_prefix and isinstance(content, str) and content.startswith(static_system_prefix):
        suffix = content[len(static_system_prefix):]
        if suffix:
            return 2 if mark_suffix else 1
        return 1
    if not fallback_to_whole:
        return 0
    return 1

def _apply_cache_marker_dict(msg: dict, cache_marker: dict, native_anthropic: bool = False) -> None:
    role = msg.get("role", "")
    content = msg.get("content")
    if role == "tool" and native_anthropic:
        msg["cache_control"] = dict(cache_marker)
        return
    if content is None or content == "":
        if role == "tool" and not native_anthropic:
            return
        if role == "assistant" and not native_anthropic:
            return
        msg["cache_control"] = dict(cache_marker)
        return
    if isinstance(content, str):
        if role == "user":
            sp = find_stable_prefix(content)
            if sp is not None:
                msg["content"] = [{"type": "text", "text": sp, "cache_control": dict(cache_marker)}, {"type": "text", "text": content[len(sp):]}]
                return
        msg["content"] = [{"type": "text", "text": content, "cache_control": dict(cache_marker)}]
        return
    if isinstance(content, list) and content:
        last = content[-1]
        if isinstance(last, dict):
            last["cache_control"] = dict(cache_marker)

def _can_carry_marker_dict(msg: dict, native_anthropic: bool) -> bool:
    if native_anthropic:
        return True
    content = msg.get("content")
    if content is None or content == "":
        return False
    if isinstance(content, list):
        return bool(content) and isinstance(content[-1], dict)
    return isinstance(content, str)

def _completed_transaction_endpoint_indexes_dict(messages: List[Dict[str, Any]], *, native_anthropic: bool) -> List[int]:
    endpoints: List[int] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if not isinstance(message, dict) or message.get("role") == "system":
            index += 1
            continue
        if message.get("role") == "assistant" and message.get("tool_calls"):
            result_start = index + 1
            result_end = result_start
            while result_end < len(messages):
                result = messages[result_end]
                if not isinstance(result, dict) or result.get("role") != "tool":
                    break
                result_end += 1
            if result_end > result_start:
                endpoint = result_end - 1
                if _can_carry_marker_dict(messages[endpoint], native_anthropic):
                    endpoints.append(endpoint)
            index = result_end
            continue
        if message.get("role") == "tool":
            while index < len(messages):
                result = messages[index]
                if not isinstance(result, dict) or result.get("role") != "tool":
                    break
                index += 1
            continue
        if message.get("role") == "user" and index + 1 < len(messages):
            index += 1
            continue
        if message.get("role") == "assistant" and message.get("content") in (None, ""):
            index += 1
            continue
        if _can_carry_marker_dict(message, native_anthropic):
            endpoints.append(index)
        index += 1
    return endpoints

def _apply_system_cache_markers_dict(message: dict, cache_marker: dict, static_system_prefix: str | None, *, native_anthropic: bool, mark_suffix: bool = True, fallback_to_whole: bool = True) -> int:
    content = message.get("content")
    if isinstance(static_system_prefix, str) and static_system_prefix and isinstance(content, str) and content.startswith(static_system_prefix):
        suffix = content[len(static_system_prefix):]
        if suffix:
            suffix_part: dict = {"type": "text", "text": suffix}
            if mark_suffix:
                suffix_part["cache_control"] = dict(cache_marker)
            message["content"] = [{"type": "text", "text": static_system_prefix, "cache_control": dict(cache_marker)}, suffix_part]
            return 2 if mark_suffix else 1
        _apply_cache_marker_dict(message, cache_marker, native_anthropic=native_anthropic)
        return 1
    if not fallback_to_whole:
        return 0
    _apply_cache_marker_dict(message, cache_marker, native_anthropic=native_anthropic)
    return 1

def strip_anthropic_cache_control_dict(api_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for msg in api_messages:
        if not isinstance(msg, dict):
            continue
        msg.pop("cache_control", None)
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        skill_split_shape = (msg.get("role") == "user" and len(content) == 2 and isinstance(content[0], dict) and isinstance(content[1], dict) and "cache_control" in content[0] and "cache_control" not in content[1])
        if any(isinstance(part, dict) and "cache_control" in part for part in content):
            content = [{k: v for k, v in part.items() if k != "cache_control"} if isinstance(part, dict) and "cache_control" in part else part for part in content]
            msg["content"] = content
        decoration_shape = content and all(isinstance(part, dict) and part.get("type", "text") == "text" and isinstance(part.get("text"), str) and set(part.keys()) <= {"type", "text"} for part in content) and (len(content) == 1 or (msg.get("role") == "system" and len(content) == 2) or skill_split_shape)
        if decoration_shape:
            msg["content"] = "".join(part["text"] for part in content)
    return api_messages

def strip_anthropic_tool_cache_control_dict(tools: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    cleaned = copy.deepcopy(tools or [])
    for tool in cleaned:
        if isinstance(tool, dict):
            tool.pop("cache_control", None)
    return cleaned

def strip_cache_control(messages: list) -> tuple[list, int]:
    stripped = 0
    out = []
    changed = False
    for msg in messages:
        kw = getattr(msg, "additional_kwargs", None) or {}
        if "cache_control" in kw or "_stable_prefix_len" in kw:
            new_kw = dict(kw)
            if "cache_control" in new_kw:
                new_kw.pop("cache_control")
                stripped += 1
            new_kw.pop("_stable_prefix_len", None)
            new_msg = _copy_msg(msg, additional_kwargs=new_kw)
            if new_msg is None:
                out.append(msg)
                continue
            out.append(new_msg)
            changed = True
        else:
            content = getattr(msg, "content", None)
            if isinstance(content, list) and any(isinstance(p, dict) and "cache_control" in p for p in content):
                new_content = [{k: v for k, v in p.items() if k != "cache_control"} if isinstance(p, dict) else p for p in content]
                new_msg = _copy_msg(msg, content=new_content)
                if new_msg is not None:
                    out.append(new_msg)
                    stripped += 1
                    changed = True
                    continue
            out.append(msg)
    if changed:
        return out, stripped
    return messages, stripped

def build_prompt_cache_plan(messages: list, provider: str | None = None, model: str | None = None, *, static_system_prefix: str | None = None, tools: List[Dict[str, Any]] | None = None, cache_ttl: str | None = "5m", native_anthropic: bool = False, direct_native_tool_cache: bool = False) -> tuple[list, dict[str, Any]]:
    if not isinstance(messages, list) or not messages:
        return messages, {"enabled": False, "markers": 0, "reason": "empty"}
    if not _cache_enabled(provider, model):
        return messages, {"enabled": False, "markers": 0, "reason": "opt-in"}
    if messages and isinstance(messages[0], dict) and "role" in messages[0]:
        ttl = effective_cache_ttl(cache_ttl or "5m", model=model or "", provider=provider or "")
        marker = _build_marker(ttl)
        msgs = copy.deepcopy(messages or [])
        strip_anthropic_cache_control_dict(msgs)
        planned_tools = strip_anthropic_tool_cache_control_dict(tools)
        if not direct_native_tool_cache or not planned_tools:
            breakpoints_used = 0
            if msgs and isinstance(msgs[0], dict) and msgs[0].get("role") == "system":
                breakpoints_used = _apply_system_cache_markers_dict(msgs[0], marker, static_system_prefix, native_anthropic=native_anthropic)
            remaining = 4 - breakpoints_used
            non_sys = [i for i in range(len(msgs)) if msgs[i].get("role") != "system" and _can_carry_marker_dict(msgs[i], native_anthropic)]
            for idx in non_sys[-remaining:]:
                _apply_cache_marker_dict(msgs[idx], marker, native_anthropic=native_anthropic)
            mcount = sum(1 for m in msgs if "cache_control" in m) + sum(1 for m in msgs if isinstance(m.get("content"), list) for p in m["content"] if isinstance(p, dict) and "cache_control" in p) + sum(1 for t in planned_tools if "cache_control" in t)
            return msgs, {"enabled": True, "markers": mcount, "reason": "applied", "hit_rate_hint": None, "tools": planned_tools}
        else:
            if msgs and isinstance(msgs[0], dict) and msgs[0].get("role") == "system":
                _apply_system_cache_markers_dict(msgs[0], marker, static_system_prefix, native_anthropic=True, mark_suffix=False, fallback_to_whole=False)
            planned_tools[-1]["cache_control"] = dict(marker)
            for ep in _completed_transaction_endpoint_indexes_dict(msgs, native_anthropic=True)[-2:]:
                _apply_cache_marker_dict(msgs[ep], marker, native_anthropic=True)
            mcount = sum(1 for m in msgs if "cache_control" in m) + sum(1 for m in msgs if isinstance(m.get("content"), list) for p in m["content"] if isinstance(p, dict) and "cache_control" in p) + sum(1 for t in planned_tools if "cache_control" in t)
            return msgs, {"enabled": True, "markers": mcount, "reason": "applied", "hit_rate_hint": None, "tools": planned_tools}
    ttl = effective_cache_ttl(cache_ttl or "5m", model=model or "", provider=provider or "")
    marker = _build_marker(ttl)
    stripped_msgs, _ = strip_cache_control(list(messages))
    msgs = list(stripped_msgs)
    planned_tools = strip_anthropic_tool_cache_control_dict(tools) if tools else []
    if direct_native_tool_cache and planned_tools:
        breakpoints_used = 0
        if msgs and type(msgs[0]).__name__ == "SystemMessage":
            cnt = _apply_system_cache_markers_msg(msgs[0], marker, static_system_prefix, native_anthropic=True, mark_suffix=False, fallback_to_whole=False)
            if cnt > 0:
                kw = dict(getattr(msgs[0], "additional_kwargs", None) or {})
                kw["cache_control"] = dict(marker)
                new = _copy_msg(msgs[0], additional_kwargs=kw)
                if new is not None:
                    msgs[0] = new
            breakpoints_used = cnt
        planned_tools[-1]["cache_control"] = dict(marker)
        endpoints = _completed_transaction_endpoint_indexes_msg(msgs, native_anthropic=True)
        for idx in endpoints[-2:]:
            new = _apply_cache_marker_msg(msgs[idx], marker, native_anthropic=True)
            if new is not None:
                msgs[idx] = new
        marked = sum(1 for m in msgs if (getattr(m, "additional_kwargs", None) or {}).get("cache_control")) + sum(1 for t in planned_tools if "cache_control" in t)
        return msgs, {"enabled": True, "markers": marked, "reason": "applied", "hit_rate_hint": None, "tools": planned_tools}
    breakpoints_used = 0
    if msgs and type(msgs[0]).__name__ == "SystemMessage":
        content = getattr(msgs[0], "content", "")
        is_prefix = isinstance(static_system_prefix, str) and static_system_prefix and isinstance(content, str) and content.startswith(static_system_prefix)
        suffix = content[len(static_system_prefix):] if is_prefix else ""
        if is_prefix:
            kw = dict(getattr(msgs[0], "additional_kwargs", None) or {})
            kw["cache_control"] = dict(marker)
            new = _copy_msg(msgs[0], additional_kwargs=kw)
            if new is not None:
                msgs[0] = new
            breakpoints_used = 2 if suffix else 1
        else:
            kw = dict(getattr(msgs[0], "additional_kwargs", None) or {})
            kw["cache_control"] = dict(marker)
            new = _copy_msg(msgs[0], additional_kwargs=kw)
            if new is not None:
                msgs[0] = new
            breakpoints_used = 1
    remaining = _CACHE_BREAKPOINTS - breakpoints_used
    non_sys = [i for i in range(len(msgs)) if type(msgs[i]).__name__ != "SystemMessage" and _can_carry_marker_msg(msgs[i], native_anthropic)]
    for idx in non_sys[-remaining:] if remaining > 0 else []:
        new = _apply_cache_marker_msg(msgs[idx], marker, native_anthropic=native_anthropic)
        if new is not None:
            msgs[idx] = new
    marked = sum(1 for m in msgs if (getattr(m, "additional_kwargs", None) or {}).get("cache_control"))
    marked += sum(1 for t in planned_tools if "cache_control" in t)
    if marked == 0:
        return messages, {"enabled": True, "markers": 0, "reason": "no_carryable", "hit_rate_hint": None}
    return msgs, {"enabled": True, "markers": marked, "reason": "applied", "hit_rate_hint": None}
