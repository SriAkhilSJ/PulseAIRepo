"""Thin forwarder to Pulse's Hermes-parity prompt engine.

Kept as the import path older callers/tests use. The real assembly lives in
``src/prompts/hermes/system_prompt.py`` (3-tier stable/context/volatile,
built once per session, rebuilt only on compaction — see PROVENANCE.md there).
The legacy kwargs form is still honoured so a caller that only wants the
persona guidance keeps getting byte-identical output.
"""
from __future__ import annotations

from typing import Dict, List

from src.prompts.hermes import guidance as _guidance
from src.prompts.hermes.system_prompt import (
    build_system_prompt_parts as _build_parts,
)  # pyrefly: ignore [missing-import]
from src.prompts.hermes.view import PulsePromptView  # pyrefly: ignore [missing-import]

DEFAULT_IDENTITY = _guidance.DEFAULT_AGENT_IDENTITY
TASK_COMPLETION_GUIDANCE = _guidance.TASK_COMPLETION_GUIDANCE
PARALLEL_TOOL_CALL_GUIDANCE = _guidance.PARALLEL_TOOL_CALL_GUIDANCE
TOOL_USE_ENFORCEMENT = _guidance.TOOL_USE_ENFORCEMENT_GUIDANCE

__all__ = [
    "DEFAULT_IDENTITY",
    "PARALLEL_TOOL_CALL_GUIDANCE",
    "TASK_COMPLETION_GUIDANCE",
    "TOOL_USE_ENFORCEMENT",
    "build_system_prompt",
    "build_system_prompt_parts",
]


def build_system_prompt_parts(
    identity: str = "",
    context_files: str = "",
    skills_prompt: str = "",
    memory_block: str = "",
    model: str = "",
    platform: str = "",
) -> Dict[str, str]:
    """Legacy kwargs surface, now backed by the ported engine.

    Each argument maps onto the same tier the engine places it in, so a caller
    that migrates from the old stub gets the real gating instead of a stub.
    """
    from pathlib import Path  # local: keeps this module import-cheap

    view = PulsePromptView(
        identity=identity or "",
        model=model,
        platform=platform,
        skills_enabled=bool(skills_prompt),
        cwd=Path.cwd(),
        skip_context_files=True,
    )
    parts = _build_parts(view)
    stable = parts["stable"]
    context: List[str] = [parts["context"]]
    if context_files:
        context.append(context_files)
    volatile: List[str] = [parts["volatile"]]
    if skills_prompt:
        volatile.insert(0, skills_prompt)
    if memory_block:
        volatile.insert(1 if skills_prompt else 0, memory_block)
    return {
        "stable": stable,
        "context": "\n\n".join(p for p in context if p),
        "volatile": "\n\n".join(p for p in volatile if p),
    }


def build_system_prompt(**kwargs) -> str:
    parts = build_system_prompt_parts(**kwargs)
    return "\n\n".join(p for p in (parts["stable"], parts["context"], parts["volatile"]) if p)
