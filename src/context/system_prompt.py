"""3-tier system prompt: stable / context / volatile (Hermes parity).

Call once per session, cached on ContextEngine. Only volatile rebuilds;
stable is byte-stable for prompt caching.
"""
from __future__ import annotations
from typing import Dict, List

DEFAULT_IDENTITY = "You are PulseAI, a helpful AI coding assistant. Be direct, execute with tools, verify before claiming success."
TASK_COMPLETION_GUIDANCE = "When asked to build/run/verify, deliver working artifact backed by real tool output — not description. If blocked, report blocker honestly, never fabricate."
PARALLEL_TOOL_CALL_GUIDANCE = "When you need several independent reads/searches, batch them in one turn — runtime runs them concurrently, saves context resend cost."
TOOL_USE_ENFORCEMENT = "You MUST use tools to act — never end turn with promise of future action. Every response either contains tool calls or final result."

def build_system_prompt_parts(identity: str = "", context_files: str = "", skills_prompt: str = "", memory_block: str = "", model: str = "", platform: str = "") -> Dict[str, str]:
    stable: List[str] = [identity or DEFAULT_IDENTITY, TASK_COMPLETION_GUIDANCE, PARALLEL_TOOL_CALL_GUIDANCE, TOOL_USE_ENFORCEMENT]
    context: List[str] = []
    if context_files: context.append(context_files)
    volatile: List[str] = []
    if skills_prompt: volatile.append(skills_prompt)
    if memory_block: volatile.append(memory_block)
    import datetime
    volatile.append(f"Date: {datetime.date.today().isoformat()}  Model: {model}  Platform: {platform}".strip())
    return {"stable": "\n\n".join(p for p in stable if p), "context": "\n\n".join(context), "volatile": "\n\n".join(volatile)}

def build_system_prompt(**kwargs) -> str:
    parts = build_system_prompt_parts(**kwargs)
    return "\n\n".join(p for p in (parts["stable"], parts["context"], parts["volatile"]) if p)
