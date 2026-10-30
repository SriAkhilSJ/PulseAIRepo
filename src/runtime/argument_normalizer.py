"""Strict Schema-Guarded Tool Argument Normalizer for CrusorAI 2.1.

Invariants:
1. Canonical argument precedence: Never overwrite an explicitly supplied canonical argument.
2. Conflict rejection: If both an alias and canonical equivalent are provided with conflicting values,
   reject with CONFLICTING_ARGUMENTS_ERROR.
3. Ambiguity protection: Ambiguous multi-target tools (e.g., copy_file(src, dst)) fail closed if
   ambiguous keys like 'path' are passed.
4. Audit provenance: Every call yields original, normalized, status, and error details.
"""
from __future__ import annotations

from typing import Any, Dict, NamedTuple, Optional, Set


class NormalizationResult(NamedTuple):
    status: str  # "ok", "rejected", "unmodified"
    normalized_args: Dict[str, Any]
    error: Optional[str] = None
    original_args: Optional[Dict[str, Any]] = None


# Explicit unambiguous whitelist: Maps tool -> {alias_key: canonical_key}
# Each alias here targets a tool where only ONE argument of that role exists.
WHITELISTED_ALIASES: Dict[str, Dict[str, str]] = {
    "edit_file": {
        "old_text": "old_string",
        "new_text": "new_string",
        "target": "old_string",
        "replacement": "new_string",
    },
    "read_file": {
        "filepath": "path",
        "file": "path",
        "filename": "path",
        "file_path": "path",
    },
    "write_file": {
        "filepath": "path",
        "file": "path",
        "filename": "path",
        "file_path": "path",
    },
    "terminal": {
        "cmd": "command",
        "exec": "command",
    },
}

# Tools with multiple arguments of the same type/role where naive aliasing is strictly ambiguous.
# For example: passing 'path' to copy_file is ambiguous between 'src' and 'dst'.
AMBIGUOUS_MULTI_TARGET_TOOLS: Set[str] = {
    "copy_file",
    "move_file",
    "diff_files",
}


def normalize_tool_arguments(tool_name: str, args: Dict[str, Any]) -> NormalizationResult:
    """Normalize tool arguments strictly according to canonical schemas and unambiguous whitelists."""
    if not isinstance(args, dict):
        return NormalizationResult(
            status="rejected",
            normalized_args={},
            error="INVALID_ARGUMENTS_TYPE: Expected JSON object / dictionary.",
            original_args={"raw": args},
        )

    # 1. Ambiguity Guard: Fail closed if ambiguous parameters are sent to multi-target tools
    if tool_name in AMBIGUOUS_MULTI_TARGET_TOOLS:
        ambiguous_keys = {"path", "filepath", "file", "target"}
        intersect = set(args.keys()) & ambiguous_keys
        if intersect:
            return NormalizationResult(
                status="rejected",
                normalized_args={},
                error=(
                    f"AMBIGUOUS_ARGUMENT_ERROR: Tool '{tool_name}' has multiple targets and cannot resolve "
                    f"ambiguous parameter(s) {list(intersect)}. Must explicitly provide canonical parameters."
                ),
                original_args=dict(args),
            )

    aliases = WHITELISTED_ALIASES.get(tool_name)
    if not aliases:
        # Tool has no aliases defined; return unmodified
        return NormalizationResult(
            status="unmodified",
            normalized_args=dict(args),
            original_args=dict(args),
        )

    normalized = dict(args)
    applied_changes = False

    for alias_key, canonical_key in aliases.items():
        if alias_key in args:
            alias_val = args[alias_key]

            # Invariant 2: Conflict rejection if canonical also supplied with conflicting value
            if canonical_key in args:
                canonical_val = args[canonical_key]
                if alias_val != canonical_val:
                    return NormalizationResult(
                        status="rejected",
                        normalized_args={},
                        error=(
                            f"CONFLICTING_ARGUMENTS_ERROR: Both alias '{alias_key}' (value: {alias_val!r}) "
                            f"and canonical '{canonical_key}' (value: {canonical_val!r}) provided with conflicting values."
                        ),
                        original_args=dict(args),
                    )
                # If values match exactly, safely drop alias and keep canonical
                normalized.pop(alias_key, None)
                applied_changes = True
            else:
                # Invariant 1: Promote alias to canonical when canonical is absent
                normalized[canonical_key] = alias_val
                normalized.pop(alias_key, None)
                applied_changes = True

    return NormalizationResult(
        status="ok" if applied_changes else "unmodified",
        normalized_args=normalized,
        original_args=dict(args),
    )
