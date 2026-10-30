"""Dependency-light helpers for verification and recovery identities.

This module deliberately imports no planner, provider SDK, LangGraph, or tool
runtime. Verification gates are used by lean CI contracts that install only the
core message/graph packages; importing a pure failure classifier must not pull
an optional LLM provider into those checks.
"""
from __future__ import annotations

import re
from typing import Any


_ENV_FAILURE_MARKERS = (
    "not recognized as an internal or external command",
    "is not recognized",
    "the syntax of the command is incorrect",
    "command not found",
    "no such file or directory",
    "cannot find the path specified",
    "not found in path",
    "permission denied",
    "exit code: 127",
)

_FLAKY_TIMEOUT_MARKERS = (
    "timeouterror",
    "the operation timed out",
    "operation timed out",
    "connection reset",
    "socket hang up",
    "econnreset",
    "etimedout",
    "timed out after",
)


def classify_env_failure(result: str) -> bool:
    """Whether a failed command needs an environment pivot, not source repair."""
    normalized = str(result or "").lower()
    return any(marker in normalized for marker in _ENV_FAILURE_MARKERS)


def classify_flaky_failure(result: str) -> bool:
    """Whether a failed verification run is a transient network/timeout flake rather than a deterministic code assertion failure."""
    normalized = str(result or "").lower()
    return any(marker in normalized for marker in _FLAKY_TIMEOUT_MARKERS)


def command_fingerprint(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Return one normalized command identity for retry/debt accounting.

    ``tool_name`` remains part of the public helper signature for compatibility
    with progress accounting even though command extraction is alias-neutral.
    """
    del tool_name
    candidate: Any | None = None
    for key in ("command", "code", "cmd", "script"):
        if tool_args.get(key):
            candidate = tool_args.get(key)
            break
    if not candidate:
        return None
    return re.sub(r"\s+", " ", str(candidate)).strip().lower()
