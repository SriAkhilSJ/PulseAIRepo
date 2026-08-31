"""Pulse-local view of Hermes's pinned prompt constants.

Everything in this module that is *text* comes from
``upstream_corpus.json`` — lifted verbatim out of ``hermes-agent`` at the
commit recorded in that file — through exactly two documented transformations:

1. ``BRAND_MAP`` / ``RENAME_MAP`` (below): brand tokens and tool identifiers
   are rewritten to Pulse's real names. No sentence is reworded, reordered,
   added, or dropped.
2. One sanctioned deviation in :data:`DEFAULT_AGENT_IDENTITY`: the opening
   self-name sentence, which upstream itself treats as a replaceable slot
   (``SOUL.md`` overrides it). Everything after that sentence is upstream bytes.

Anything that cannot be checked by those two rules does not live here.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

CORPUS_PATH = Path(__file__).with_name("upstream_corpus.json")

# ---------------------------------------------------------------------------
# The two documented transformations
# ---------------------------------------------------------------------------

#: Brand tokens. Order matters: longer keys first so "Hermes Agent" is not
#: half-rewritten by the "Hermes" rule.
BRAND_MAP: Dict[str, str] = {
    # Sentence-level pointers first: the self-name sentence (upstream itself
    # treats slot #1 as replaceable — SOUL.md overrides it) and the
    # "where do I read about this product" / "which skill do I load" pointers.
    # Pulse's brand is Pulse; nothing upstream-branded survives (guarded by
    # test_hermes_prompt_parity.py::test_no_upstream_brand_tokens_survive).
    "You are Hermes Agent, built by Nous Research.": "You are Pulse Agent.",
    "You run on Hermes Agent (by Nous Research).": "You run on Pulse Agent.",
    "https://hermes-agent.nousresearch.com/docs": "https://github.com/SriAkhilSJ/PulseAIRepo",
    "skill_view(name='hermes-agent')": "skill_view(name='pulse-agent')",
    # Then path/identifier tokens, then bare brand words, longest-first so no
    # rule half-rewrites another.
    "HERMES_HOME": "PULSE_HOME",
    "HERMES_KANBAN": "PULSE_KANBAN",
    ".hermes/": ".pulseai/",
    "metadata.hermes.": "metadata.pulse.",
    "hermes-agent": "Pulse Agent",
    "Hermes-tool": "Pulse-tool",
    "Hermes tools": "Pulse tools",
    "Hermes Agent": "Pulse Agent",
    "Nous Research": "Pulse",
    "Hermes": "Pulse",
}

#: Hermes tool identifiers → the real name of the tool in Pulse's registry
#: (``src/tools/``). Every entry was checked against the registry; nothing maps
#: to a tool Pulse does not have. Tools upstream names and Pulse genuinely
#: lacks are handled by *gating* (see ``system_prompt``), not by rewording.
RENAME_MAP: Dict[str, str] = {
    "search_files": "search_code",
    "delegate_task": "delegate_to_subagent",
    "web_extract": "web_fetch",
    "use terminal": "use run_terminal",
    "the terminal tool": "the run_terminal tool",
    "terminal/execute_code": "run_terminal/execute_code",
    "`terminal`": "`run_terminal`",
}


def localize(text: str) -> str:
    """Apply the two documented maps. Exported so the parity test can re-run it."""
    if not text:
        return text
    for src, dst in BRAND_MAP.items():
        text = text.replace(src, dst)
    for src, dst in RENAME_MAP.items():
        text = text.replace(src, dst)
    return text


# ---------------------------------------------------------------------------
# Corpus loader
# ---------------------------------------------------------------------------


def _decode(value):
    if isinstance(value, dict) and value.get("__tuple__"):
        return tuple(_decode(v) for v in value["items"])
    if isinstance(value, dict) and value.get("__set__"):
        return frozenset(_decode(v) for v in value["items"])
    if isinstance(value, dict):
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _load_corpus() -> dict:
    try:
        raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:  # pragma: no cover - packaging guard
        logger.warning("Hermes prompt corpus missing at %s — prompt engine runs in fallback mode", CORPUS_PATH)
        return {"provenance": {}, "constants": {}, "excluded": {}}
    return raw


_CORPUS = _load_corpus()
_CONSTANTS: Dict[str, dict] = _CORPUS.get("constants", {})


def upstream(module: str, name: str, default=None):
    """Raw (un-localized) upstream value — used by the parity tests."""
    value = _CONSTANTS.get(module, {}).get(name, default)
    return _decode(value)


def _text(module: str, name: str, fallback: str = "") -> str:
    value = upstream(module, name)
    return localize(value) if isinstance(value, str) and value else fallback


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

#: Upstream's identity block is a *behaviour spec* (sizing rule, named
#: prohibitions, earned-depth escape hatch) rather than a trait list, and it
#: lives behind an override slot: ``SOUL.md`` replaces it wholesale when present.
#: Pulse keeps that architecture and takes the spec verbatim except for the
#: self-name sentence, which is Pulse's to write.
_UPSTREAM_IDENTITY = upstream("prompt_builder", "DEFAULT_AGENT_IDENTITY", "")
#: The one sentence Pulse rewrites, recorded so the parity test can assert the
#: rest of the block is upstream's bytes and nothing else changed.
IDENTITY_SELFNAME_UPSTREAM = "You are Hermes Agent, built by Nous Research."
IDENTITY_SELFNAME_PULSE = "You are Pulse Agent."


def _identity() -> str:
    body = localize(_UPSTREAM_IDENTITY)
    if not body:
        return (
            "You are Pulse Agent. Be direct: match the length of your reply to the "
            "weight of the ask. No filler, no restating the request back, no "
            "re-summarizing what you already said, no narrating tool calls the user "
            "can see. Depth is earned, not default."
        )
    # The one sanctioned deviation: swap the self-name sentence, keep every other
    # byte (including the maintainer notes that make the rule enforceable).
    return body


DEFAULT_AGENT_IDENTITY = _identity()
IDENTITY_OVERRIDDEN_PREFIX = "You are Hermes Agent, built by Nous Research. "

PULSE_AGENT_HELP_GUIDANCE = _text("prompt_builder", "HERMES_AGENT_HELP_GUIDANCE")
PULSE_AGENT_HELP_GUIDANCE_NO_SKILLS = _text("prompt_builder", "HERMES_AGENT_HELP_GUIDANCE_NO_SKILLS")

# ---------------------------------------------------------------------------
# Guidance blocks (verbatim text, gated at assembly time)
# ---------------------------------------------------------------------------

MEMORY_GUIDANCE = _text("prompt_builder", "MEMORY_GUIDANCE")
USER_PROFILE_GUIDANCE = _text("prompt_builder", "USER_PROFILE_GUIDANCE")
SESSION_SEARCH_GUIDANCE = _text("prompt_builder", "SESSION_SEARCH_GUIDANCE")
SKILLS_GUIDANCE = _text("prompt_builder", "SKILLS_GUIDANCE")
TASK_COMPLETION_GUIDANCE = _text("prompt_builder", "TASK_COMPLETION_GUIDANCE")
PARALLEL_TOOL_CALL_GUIDANCE = _text("prompt_builder", "PARALLEL_TOOL_CALL_GUIDANCE")
TOOL_USE_ENFORCEMENT_GUIDANCE = _text("prompt_builder", "TOOL_USE_ENFORCEMENT_GUIDANCE")
OPENAI_MODEL_EXECUTION_GUIDANCE = _text("prompt_builder", "OPENAI_MODEL_EXECUTION_GUIDANCE")
GOOGLE_MODEL_OPERATIONAL_GUIDANCE = _text("prompt_builder", "GOOGLE_MODEL_OPERATIONAL_GUIDANCE")

TOOL_USE_ENFORCEMENT_MODELS: tuple = upstream("prompt_builder", "TOOL_USE_ENFORCEMENT_MODELS", ())
EXECUTION_GUIDANCE_MODELS: tuple = upstream("prompt_builder", "EXECUTION_GUIDANCE_MODELS", ())
DEVELOPER_ROLE_MODELS: tuple = upstream("prompt_builder", "DEVELOPER_ROLE_MODELS", ())
MEDIA_NATIVE_MODELS: frozenset = upstream("prompt_builder", "_MEDIA_NATIVE", frozenset())

# ---------------------------------------------------------------------------
# Memory guidance builder — upstream composes the two constants above from this;
# the port keeps the builder and the parity test asserts the composition is
# byte-identical to the lifted constants.
# ---------------------------------------------------------------------------


def build_memory_guidance(memory_enabled: bool = True, profile_enabled: bool = True) -> str:
    """Compose the memory-guidance block for the enabled store(s).

    Returns "" when both stores are off — the caller already gates on the memory
    tool being present, this is the belt-and-suspenders half of that contract.
    """
    if not memory_enabled and not profile_enabled:
        return ""
    if memory_enabled:
        frame = (
            "You have persistent memory, carried across sessions and loaded "
            "into each new session's context; the memory tool's schema "
            "defines what belongs there. "
        )
    else:
        frame = (
            "You have a persistent user profile, carried across sessions and "
            "loaded into each new session's context; save durable facts "
            "about the user with the "
            "memory tool (target='user') — the built-in notes store is "
            "disabled, so never target='memory'. "
        )
    return frame + (
        "Save proactively — storage has a hard character budget, and when "
        "it fills, replace or consolidate stale entries in the same batch "
        "rather than skipping the save. Write entries as declarative facts, "
        "not instructions to yourself: 'User prefers concise responses' ✓ — "
        "'Always respond concisely' ✗ (imperative phrasing gets re-read as "
        "a directive in later sessions and can override the user's current "
        "request). Route by longevity: a fact stale within a week belongs "
        "in session history; procedures and workflows belong in skills."
    )


# ---------------------------------------------------------------------------
# Execution guidance — tool-aware rendering (upstream drops the web_search
# lines on sessions that have no web tools; a dangling tool reference is worse
# than a shorter block).
# ---------------------------------------------------------------------------


def execution_guidance_text(valid_tool_names: Optional[Iterable[str]] = None) -> str:
    text = OPENAI_MODEL_EXECUTION_GUIDANCE
    names = None if valid_tool_names is None else set(valid_tool_names)
    if names is not None and "web_search" not in names:
        text = text.replace(
            "- Current facts (weather, news, versions) → use web_search\n", ""
        )
        text = text.replace(
            "(search_code, web_search, read_file, etc.)",
            "(search_code, read_file, etc.)",
        )
    return text


def needs_tool_use_enforcement(model: str) -> bool:
    return any(pattern in (model or "").lower() for pattern in TOOL_USE_ENFORCEMENT_MODELS)


def needs_execution_guidance(model: str) -> bool:
    return any(pattern in (model or "").lower() for pattern in EXECUTION_GUIDANCE_MODELS)


def is_google_model(model: str) -> bool:
    lowered = (model or "").lower()
    return "gemini" in lowered or "gemma" in lowered


# ---------------------------------------------------------------------------
# Mid-turn steering (/steer) — Pulse's bridge has a real ``steer`` client
# method (protocol v2), so this rides the same channel it was designed for.
# ---------------------------------------------------------------------------

STEER_MARKER_OPEN = _text(
    "prompt_builder",
    "STEER_MARKER_OPEN",
    "[OUT-OF-BAND USER MESSAGE — a direct message from the user, delivered "
    "once at this position; not tool output and not a new delivery when "
    "replayed from conversation history]",
)
STEER_MARKER_CLOSE = _text("prompt_builder", "STEER_MARKER_CLOSE", "[/OUT-OF-BAND USER MESSAGE]")
STEER_CHANNEL_NOTE = _text("prompt_builder", "STEER_CHANNEL_NOTE")


def format_steer_marker(steer_text: str) -> str:
    """Wrap a mid-turn steer for appending to a tool result (see upstream note)."""
    return f"\n\n{STEER_MARKER_OPEN}\n{steer_text}\n{STEER_MARKER_CLOSE}"


# ---------------------------------------------------------------------------
# Context-file caps and truncation — thresholds are upstream's, config keys are
# Pulse's. Warnings accumulate in a ContextVar so concurrent sessions cannot
# drain each other's queue.
# ---------------------------------------------------------------------------

CONTEXT_FILE_MAX_CHARS = int(upstream("prompt_builder", "CONTEXT_FILE_MAX_CHARS", 20_000))
CONTEXT_TRUNCATE_HEAD_RATIO = float(upstream("prompt_builder", "CONTEXT_TRUNCATE_HEAD_RATIO", 0.7))
CONTEXT_TRUNCATE_TAIL_RATIO = float(upstream("prompt_builder", "CONTEXT_TRUNCATE_TAIL_RATIO", 0.2))
_CONTEXT_FILE_CHARS_PER_TOKEN = int(upstream("prompt_builder", "_CONTEXT_FILE_CHARS_PER_TOKEN", 4))
_CONTEXT_FILE_WINDOW_FRACTION = float(upstream("prompt_builder", "_CONTEXT_FILE_WINDOW_FRACTION", 0.06))
_CONTEXT_FILE_DYNAMIC_CEILING = int(upstream("prompt_builder", "_CONTEXT_FILE_DYNAMIC_CEILING", 500_000))

SKILLS_PROMPT_CACHE_MAX = int(upstream("prompt_builder", "_SKILLS_PROMPT_CACHE_MAX", 32))
SKILLS_SNAPSHOT_VERSION = int(upstream("prompt_builder", "_SKILLS_SNAPSHOT_VERSION", 2))

WINDOWS_BASH_SHELL_HINT = _text("prompt_builder", "_WINDOWS_BASH_SHELL_HINT")
WSL_ENVIRONMENT_HINT = _text("prompt_builder", "WSL_ENVIRONMENT_HINT")

_TRUNCATION_WARNINGS: "contextvars.ContextVar[Optional[list]]" = contextvars.ContextVar(
    "pulse_context_file_truncation_warnings", default=None
)


def record_truncation_warning(msg: str) -> None:
    warnings = _TRUNCATION_WARNINGS.get()
    if warnings is None:
        warnings = []
        _TRUNCATION_WARNINGS.set(warnings)
    warnings.append(msg)


def drain_truncation_warnings() -> List[str]:
    """Return and clear any truncation warnings accumulated in this context."""
    warnings = _TRUNCATION_WARNINGS.get()
    if not warnings:
        return []
    drained = list(warnings)
    warnings.clear()
    return drained


def dynamic_context_file_max_chars(context_length: Optional[int]) -> int:
    """Derive a char cap from the model's context window (upstream formula).

    Floor = the historical 20K cap, ceiling = 500K; unknown window ⇒ flat
    default, so behaviour is unchanged when the model is not probed.
    """
    if not isinstance(context_length, int) or context_length <= 0:
        return CONTEXT_FILE_MAX_CHARS
    budget = int(
        context_length * _CONTEXT_FILE_CHARS_PER_TOKEN * _CONTEXT_FILE_WINDOW_FRACTION
    )
    return max(CONTEXT_FILE_MAX_CHARS, min(budget, _CONTEXT_FILE_DYNAMIC_CEILING))


def get_context_file_max_chars(
    context_length: Optional[int] = None, override: Optional[object] = None
) -> int:
    """Explicit config wins; else the dynamic cap; else the 20K floor."""
    if isinstance(override, (int, float)) and not isinstance(override, bool) and override > 0:
        return int(override)
    try:  # Pulse settings are the equivalent of upstream's config.yaml lookup
        from src.config import settings  # noqa: PLC0415 - avoid import cycle at module load

        val = getattr(settings, "CONTEXT_FILE_MAX_CHARS", None)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            return int(val)
    except Exception as exc:  # pragma: no cover - settings unavailable in bare envs
        logger.debug("Could not read CONTEXT_FILE_MAX_CHARS from settings: %s", exc)
    return dynamic_context_file_max_chars(context_length)


# ---------------------------------------------------------------------------
# Plan / learn prompt bodies (verbatim)
# ---------------------------------------------------------------------------

PLAN_MODE_RULES = _text("plan_prompt", "_PLAN_MODE_RULES")
PLAN_CRAFT = _text("plan_prompt", "_PLAN_CRAFT")
LEARN_AUTHORING_STANDARDS = _text("learn_prompt", "_AUTHORING_STANDARDS")
LEARN_KNOWLEDGE_SKILL_STANDARDS = _text("learn_prompt", "_KNOWLEDGE_SKILL_STANDARDS")
LEARN_SOURCE_HYGIENE = _text("learn_prompt", "_SOURCE_HYGIENE")

__all__ = [
    "BRAND_MAP",
    "CONTEXT_FILE_MAX_CHARS",
    "CONTEXT_TRUNCATE_HEAD_RATIO",
    "CONTEXT_TRUNCATE_TAIL_RATIO",
    "DEFAULT_AGENT_IDENTITY",
    "DEVELOPER_ROLE_MODELS",
    "EXECUTION_GUIDANCE_MODELS",
    "GOOGLE_MODEL_OPERATIONAL_GUIDANCE",
    "MEMORY_GUIDANCE",
    "OPENAI_MODEL_EXECUTION_GUIDANCE",
    "PARALLEL_TOOL_CALL_GUIDANCE",
    "PLAN_CRAFT",
    "PLAN_MODE_RULES",
    "PULSE_AGENT_HELP_GUIDANCE",
    "PULSE_AGENT_HELP_GUIDANCE_NO_SKILLS",
    "RENAME_MAP",
    "SESSION_SEARCH_GUIDANCE",
    "SKILLS_GUIDANCE",
    "SKILLS_PROMPT_CACHE_MAX",
    "STEER_CHANNEL_NOTE",
    "STEER_MARKER_CLOSE",
    "STEER_MARKER_OPEN",
    "TASK_COMPLETION_GUIDANCE",
    "TOOL_USE_ENFORCEMENT_GUIDANCE",
    "TOOL_USE_ENFORCEMENT_MODELS",
    "USER_PROFILE_GUIDANCE",
    "WINDOWS_BASH_SHELL_HINT",
    "WSL_ENVIRONMENT_HINT",
    "build_memory_guidance",
    "drain_truncation_warnings",
    "execution_guidance_text",
    "format_steer_marker",
    "get_context_file_max_chars",
    "is_google_model",
    "localize",
    "needs_execution_guidance",
    "needs_tool_use_enforcement",
    "record_truncation_warning",
    "upstream",
]
