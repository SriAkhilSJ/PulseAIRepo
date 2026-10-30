"""Strict Schema-Guarded Tool Argument Normalizer for CrusorAI 2.1 (Phase 1 Complete).

Canonical Tool Parameter Truth in CrusorAI:
- edit_file(path, old_text, new_text) -> Canonical: old_text, new_text
- read_file(path) -> Canonical: path
- write_file(path, content) -> Canonical: path, content
- terminal(command) -> Canonical: command

Invariants & Safeguards:
1. Canonical argument precedence: Never overwrite an explicitly supplied canonical argument.
2. Conflict rejection: If both an alias and canonical equivalent are provided with conflicting values,
   reject with CONFLICTING_ARGUMENTS_ERROR.
3. Strict whitelisting: No ambiguous 'target' or 'replacement'. Only unambiguous single-role aliases.
4. Ambiguity protection: Ambiguous multi-target tools (copy_file, move_file, diff_files) fail closed
   if ambiguous parameters like 'path' are passed.
5. Standardized status reporting: "applied", "rejected", or "unmodified".
6. Comprehensive Secret Redaction:
   - Regex-based: strips sk-..., Bearer tokens, inline password patterns.
   - Key-based recursive: redacts any dictionary value where the key is in SENSITIVE_KEY_NAMES
     (e.g., password, api_key, access_token, authorization, secret, auth_token, private_key).
7. Audit provenance isolation: Original arguments are preserved strictly in redacted form for auditing.
   The helper `get_audit_entry()` provides safe-to-log representations preventing raw normalized_args leaks.
"""
from __future__ import annotations

import re
from typing import Any, Dict, NamedTuple, Optional, Set

SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"password\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
]

SENSITIVE_KEY_NAMES = {
    "password",
    "api_key",
    "apikey",
    "access_token",
    "authorization",
    "secret",
    "secret_key",
    "auth_token",
    "private_key",
    "client_secret",
}


def redact_argument_value(val: Any, parent_key: Optional[str] = None) -> Any:
    """Recursively redact arguments using both key-based and regex-based patterns."""
    # Key-based redaction: any dictionary key that matches sensitive tokens
    if parent_key and parent_key.lower() in SENSITIVE_KEY_NAMES:
        return "[REDACTED_SECRET]"

    if isinstance(val, str):
        redacted = val
        for pat in SECRET_PATTERNS:
            redacted = pat.sub("[REDACTED_SECRET]", redacted)
        return redacted
    elif isinstance(val, dict):
        return {k: redact_argument_value(v, parent_key=k) for k, v in val.items()}
    elif isinstance(val, list):
        return [redact_argument_value(v, parent_key=parent_key) for v in val]
    return val


class NormalizationResult(NamedTuple):
    status: str  # Standardized: "applied", "rejected", "unmodified"
    normalized_args: Dict[str, Any]  # Used strictly for tool execution
    error: Optional[str] = None
    original_args: Optional[Dict[str, Any]] = None  # Redacted for audit trails

    def get_audit_record(self) -> Dict[str, Any]:
        """Produce an audit-safe record with sensitive execution arguments redacted."""
        return {
            "status": self.status,
            "original_args": self.original_args,
            "normalized_args_redacted": redact_argument_value(self.normalized_args),
            "error": self.error,
        }


WHITELISTED_ALIASES: Dict[str, Dict[str, str]] = {
    "edit_file": {
        "old_string": "old_text",
        "new_string": "new_text",
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

AMBIGUOUS_MULTI_TARGET_TOOLS: Set[str] = {
    "copy_file",
    "move_file",
    "diff_files",
}


def normalize_tool_arguments(tool_name: str, args: Any) -> NormalizationResult:
    """Normalize tool arguments strictly according to canonical schemas and unambiguous whitelists."""
    if not isinstance(args, dict):
        return NormalizationResult(
            status="rejected",
            normalized_args={},
            error="INVALID_ARGUMENTS_TYPE: Expected JSON object / dictionary.",
            original_args={"raw": redact_argument_value(args)},
        )

    audit_original = {k: redact_argument_value(v, parent_key=k) for k, v in args.items()}

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
                    f"ambiguous parameter(s) {sorted(list(intersect))}. Must explicitly provide canonical parameters."
                ),
                original_args=audit_original,
            )

    aliases = WHITELISTED_ALIASES.get(tool_name)
    if not aliases:
        # Tool has no aliases defined; return unmodified
        return NormalizationResult(
            status="unmodified",
            normalized_args=dict(args),
            original_args=audit_original,
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
                            f"CONFLICTING_ARGUMENTS_ERROR: Both alias '{alias_key}' (value: {redact_argument_value(alias_val, parent_key=alias_key)!r}) "
                            f"and canonical '{canonical_key}' (value: {redact_argument_value(canonical_val, parent_key=canonical_key)!r}) provided with conflicting values."
                        ),
                        original_args=audit_original,
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
        status="applied" if applied_changes else "unmodified",
        normalized_args=normalized,
        original_args=audit_original,
    )
