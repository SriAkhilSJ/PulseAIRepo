"""Live session context-window breakdown for IDE surfaces.

Ported from hermes-agent agent/context_breakdown.py (2026-09) + IDE layers.
Estimates system prompt tiers, tool schemas, and conversation history for the
category breakdown. Overall occupancy retains its provider-usage or estimate
provenance; category estimates are not exact tokenizer counts or gate authority.

Env values:
- PULSEAI_CONTEXT_BREAKDOWN=off to disable
- All token estimates use chars//4 heuristic unless tiktoken available.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# id -> (label, dashboard color var, /context glyph); declaration order is display order.
_CATEGORIES = {
    "system_prompt": ("System prompt", "var(--context-usage-system)", "■"),
    "tool_definitions": ("Tool definitions", "var(--context-usage-tools)", "▣"),
    "rules": ("Rules", "var(--context-usage-rules)", "▩"),
    "skills": ("Skills", "var(--context-usage-skills)", "▤"),
    "memory": ("Memory", "var(--context-usage-memory)", "▧"),
    "repo_map": ("Repo map", "var(--context-usage-repo-map)", "▨"),
    "relevant_chunks": ("Relevant chunks", "var(--context-usage-chunks)", "▭"),
    "git_context": ("Git context", "var(--context-usage-git)", "▯"),
    "conventions": ("Conventions", "var(--context-usage-conventions)", "◫"),
    "conversation": ("Conversation", "var(--context-usage-conversation)", "⬚"),
}
_FREE_GLYPH = "·"
_GRID_COLUMNS = 20
_GRID_ROWS = 5  # 100 cells → 1 cell per percent
_DETAILS_TABLE_LIMIT = 15

def breakdown_enabled() -> bool:
    return os.environ.get("PULSEAI_CONTEXT_BREAKDOWN", "on").lower() not in {"0","off","false","no"}

def _chars_to_tokens(text: str) -> int:
    return (len(text) + 3) // 4

def _json_tokens(value: Any) -> int:
    if not value:
        return 0
    try:
        return _chars_to_tokens(json.dumps(value, ensure_ascii=False))
    except Exception:
        return _chars_to_tokens(str(value))

def _glyph(cat: Dict[str, Any]) -> str:
    return _CATEGORIES.get(str(cat.get("id") or ""), (None, None, "▪"))[2]

def _split_tools(tools: Sequence[dict]) -> Tuple[List[dict], List[dict]]:
    builtin: List[dict] = []
    mcp: List[dict] = []  # Pulse doesn't have MCP yet but keep parity
    for tool in tools:
        fn = tool.get("function") if isinstance(tool, dict) else None
        name = str((fn if isinstance(fn, dict) else tool).get("name") or "") if isinstance(tool, (dict)) else str(getattr(tool, "name", "") or "")
        # For IDE, no mcp_ prefix yet
        bucket = mcp if name.startswith("mcp_") else builtin
        bucket.append(tool)
    return builtin, mcp

def compute_session_context_breakdown(
    engine: Any = None,
    messages: Optional[List[dict]] = None,
    *,
    tools: Optional[List[dict]] = None,
    layers: Optional[Dict[str, str]] = None,
    system_prompt_text: str = "",
) -> Dict[str, Any]:
    """Return IDE-aware context breakdown.

    Args:
        engine: ContextEngine with context_length, last_prompt_tokens
        messages: conversation history (dict or BaseMessage)
        tools: tool definitions
        layers: dict layer_name -> content (for IDE categories)
        system_prompt_text: full system prompt if available
    """
    messages = messages or []
    layers = layers or {}
    # Token estimates per category
    tokens_by_id: Dict[str, int] = {cid: 0 for cid in _CATEGORIES}

    # System prompt
    if system_prompt_text:
        tokens_by_id["system_prompt"] = _chars_to_tokens(system_prompt_text)
    else:
        # Estimate from engine's cached view if available
        try:
            from src.prompts.hermes.session import session_stats
            tid = getattr(engine, "thread_id", "") or "default"
            stats = session_stats({"configurable": {"thread_id": tid}})
            if stats.get("cached"):
                total = (stats.get("stable_chars", 0) or 0) + (stats.get("context_chars", 0) or 0) + (stats.get("volatile_chars", 0) or 0)
                tokens_by_id["system_prompt"] = _chars_to_tokens("x" * total)
        except Exception:
            pass

    # Tools
    if tools:
        builtin, mcp = _split_tools(tools)
        tokens_by_id["tool_definitions"] = _json_tokens(builtin)
    else:
        # Try engine tools
        try:
            t = getattr(engine, "tools", None) or []
            tokens_by_id["tool_definitions"] = _json_tokens(t)
        except Exception:
            pass

    # Layers -> map to categories
    for name, content in layers.items():
        if not content:
            continue
        t = _chars_to_tokens(content)
        if name in ("repo_map",):
            tokens_by_id["repo_map"] += t
        elif name in ("relevant_chunks",):
            tokens_by_id["relevant_chunks"] += t
        elif name in ("git_context",):
            tokens_by_id["git_context"] += t
        elif name in ("conventions",):
            tokens_by_id["conventions"] += t
        elif name in ("skills",):
            tokens_by_id["skills"] += t
        elif name in ("long_term_memory", "tool_memory", "memory_validation", "reflections"):
            tokens_by_id["memory"] += t
        elif name in ("task", "plan", "progress", "recovery", "replan", "attempt_history", "ambiguity", "tone", "quality"):
            tokens_by_id["rules"] += t
        else:
            # fallback to system_prompt
            tokens_by_id["system_prompt"] += t

    # Conversation
    try:
        from src.context.model_budgets import estimate_messages_tokens_rough
        # Handle BaseMessage list
        if messages and not isinstance(messages[0], dict):
            from src.context.token_budget import count_tokens
            model = getattr(engine, "model", None) or "gpt-4o"
            conv_tokens = sum(count_tokens([m], model) for m in messages)
        else:
            conv_tokens = estimate_messages_tokens_rough(messages)  # type: ignore
        tokens_by_id["conversation"] = conv_tokens
    except Exception:
        # Fallback chars
        total_chars = sum(len(str(getattr(m, "content", "") or m.get("content","") if isinstance(m, dict) else "")) for m in messages)
        tokens_by_id["conversation"] = _chars_to_tokens("x" * total_chars)

    estimated_total = sum(tokens_by_id.values())

    # Context window & usage
    context_max = 0
    context_used = 0
    source = "local_estimate"
    if engine:
        context_max = int(getattr(engine, "context_length", 0) or getattr(engine, "context_window", 0) or 0)
        last = int(getattr(engine, "last_prompt_tokens", 0) or 0)
        if last > 0:
            context_used = last
            source = "provider_usage"
        else:
            context_used = estimated_total

    if context_max == 0:
        context_max = estimated_total or 1

    categories = [
        {"color": color, "id": cid, "label": label, "tokens": tokens_by_id[cid]}
        for cid, (label, color, _g) in _CATEGORIES.items()
        if tokens_by_id[cid] > 0
    ]
    # Sort by tokens desc for display, but keep glyph order for grid? Use declaration order for grid
    categories_sorted = sorted(categories, key=lambda c: c["tokens"], reverse=True)

    return {
        "categories": categories_sorted,
        "categories_by_id": tokens_by_id,
        "context_max": context_max,
        "context_percent": max(0, min(100, round(context_used / context_max * 100))) if context_max else 0,
        "context_used": context_used,
        "context_source": source,
        "context_estimated": source != "provider_usage",
        "estimated_total": estimated_total,
        "model": getattr(engine, "model", "") if engine else "",
        "breakdown_enabled": breakdown_enabled(),
    }

def render_context_grid(payload: Dict[str, Any]) -> List[str]:
    context_max = int(payload.get("context_max") or 0)
    total_cells = _GRID_COLUMNS * _GRID_ROWS
    cells: List[str] = []
    if context_max > 0:
        # Use declaration order for grid fill
        for cid in _CATEGORIES:
            # find cat
            cat = next((c for c in payload.get("categories") or [] if c.get("id")==cid), None)
            if not cat:
                continue
            tokens = int(cat.get("tokens") or 0)
            n = round(tokens / context_max * total_cells) or (1 if tokens > 0 else 0)
            cells.extend([_glyph(cat)] * n)
        cells = cells[:total_cells]
    cells.extend([_FREE_GLYPH] * (total_cells - len(cells)))
    return [" ".join(cells[row * _GRID_COLUMNS:(row + 1) * _GRID_COLUMNS]) for row in range(_GRID_ROWS)]

def render_context_category_lines(payload: Dict[str, Any]) -> List[str]:
    categories = payload.get("categories") or []
    context_max = int(payload.get("context_max") or 0)
    estimated_total = int(payload.get("estimated_total") or 0)
    denom = context_max or estimated_total or 1
    lines = ["Estimated usage by category"]
    if not categories:
        return [*lines, "  (no data yet — send a message first)"]
    width = max(len("Free space"), *(len(str(cat.get("label") or "")) for cat in categories))
    for cat in categories:
        tokens, label = int(cat.get("tokens") or 0), str(cat.get("label") or cat.get("id") or "")
        lines.append(f"{_glyph(cat)} {label:<{width}} ~{tokens:>9,} tokens ~{tokens / denom * 100 if denom else 0.0:>5.1f}%")
    if context_max > 0:
        free = max(0, context_max - estimated_total)
        lines.append(f"{_FREE_GLYPH} {'Free space':<{width}} ~{free:>9,} tokens ~{free / context_max * 100:>5.1f}%")
    return lines

def render_context_breakdown_lines(payload: Dict[str, Any], *, grid: bool = True) -> List[str]:
    lines: List[str] = [*render_context_grid(payload), ""] if grid else []
    lines.extend(render_context_category_lines(payload))
    context_max = int(payload.get("context_max") or 0)
    if context_max > 0:
        used, pct = int(payload.get("context_used") or 0), int(payload.get("context_percent") or 0)
        mark = "~" if payload.get("context_estimated") else ""
        lines.extend(["", f"Context window: {mark}{used:,} / {context_max:,} tokens ({mark}{pct}%)"])
        source = payload.get("context_source")
        if source:
            labels = {"local_estimate": "local estimate", "provider_usage": "provider usage", "provider_usage_plus_estimate": "provider usage + estimated new messages"}
            lines.append(f"Source: {labels.get(source, source)}; category counts are local estimates.")
    return lines

__all__ = [
    "breakdown_enabled",
    "compute_session_context_breakdown",
    "render_context_breakdown_lines",
    "render_context_category_lines",
    "render_context_grid",
]
