"""Bounded safety boundary for values written to durable runtime stores.

Live tool output and durable replay have different trust requirements. A user
may choose verbose live output, but credentials, request bodies, and source
text must not silently become a second long-lived copy in SQLite or tracing.

This module is intentionally dependency-light. Durable stores call
:func:`sanitize_for_persistence`; event journals call
:func:`sanitize_event_payload` so tool-body omission cannot be bypassed by a
new caller that forgets to pre-sanitize its arguments.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from typing import Any

from src.utils.redact import redact_sensitive_text

PERSISTENCE_REDACTION = "«redacted:persistence-secret»"
KNOWN_SECRET_REDACTION = "«redacted:known-secret»"
_MAX_DEPTH = 24
_MAX_ITEMS = 2_000
_MAX_STRING_CHARS = 64_000

# Exact names and narrow suffixes avoid masking identifiers/counters such as
# ``session_id`` and ``token_count``.
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "id_token",
        "jwt",
        "key",
        "password",
        "passwd",
        "private_key",
        "proxy_authorization",
        "refresh_token",
        "secret",
        "set_cookie",
        "signature",
        "token",
        "x_api_key",
    }
)
_SENSITIVE_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_api_token",
    "_auth_token",
    "_bearer_token",
    "_client_secret",
    "_credential",
    "_password",
    "_private_key",
    "_refresh_token",
    "_session_token",
    "_secret",
)

# File/request bodies can contain opaque credentials for which no regex can
# exist. Intent rows need the operation shape and target, not another copy of
# the body. Applied only to tool arguments, never to result/status fields.
_TOOL_BODY_KEYS = frozenset(
    {
        "base64",
        "binary",
        "blob",
        "body",
        "code",
        "content",
        "data",
        "file_content",
        "new_text",
        "old_text",
        "patch",
    }
)

# ``file_read=True`` gives known token prefixes a non-reusable full mask while
# intentionally skipping assignment/JSON patterns. A second prose/config pass
# is needed only when a string can actually contain one of those forms. This
# avoids two full redactor calls for ordinary paths, statuses, and identifiers.
_CONFIG_SECRET_HINTS = (
    "api_key",
    "apikey",
    "auth",
    "credential",
    "jwt",
    "key",
    "passwd",
    "password",
    "private",
    "secret",
    "signature",
    "token",
)


def _normalise_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def _is_sensitive_key(key: object) -> bool:
    name = _normalise_key(key)
    return name in _SENSITIVE_KEYS or name.endswith(_SENSITIVE_SUFFIXES)


def _is_secret_env_name(name: object) -> bool:
    normalized = _normalise_key(name)
    # Provider credentials commonly use GITHUB_TOKEN/HF_TOKEN. Keep this
    # broader suffix restricted to environment discovery so model settings
    # such as ``max_token`` remain useful in structured payloads.
    return _is_sensitive_key(normalized) or normalized.endswith("_token")


def _snapshot_known_environment_secrets() -> tuple[str, ...]:
    """Capture configured secret values once, without persisting their names.

    Prefix/key regexes cannot recognize an opaque credential echoed without a
    label. Provider secrets are normally loaded before Agent Core imports this
    module, so a startup snapshot closes that gap without re-reading mutable
    process state or adding per-write configuration I/O.
    """

    values: set[str] = set()
    for name, value in os.environ.items():
        if not _is_secret_env_name(name) or not isinstance(value, str):
            continue
        candidate = value.strip()
        if len(candidate) < 8:
            continue
        if candidate.lower() in {"placeholder", "changeme", "undefined", "none"}:
            continue
        values.add(candidate)
    return tuple(sorted(values, key=len, reverse=True))


_KNOWN_ENVIRONMENT_SECRETS = _snapshot_known_environment_secrets()


def _redact_string(value: str) -> str:
    if len(value) > _MAX_STRING_CHARS:
        return (
            "[oversized string omitted at persistence boundary; "
            f"{len(value)} characters]"
        )

    scrubbed = value
    for secret in _KNOWN_ENVIRONMENT_SECRETS:
        if secret in scrubbed:
            scrubbed = scrubbed.replace(secret, KNOWN_SECRET_REDACTION)

    # The first pass fully masks recognizable token bodies and strict URL
    # credentials. It also handles auth headers, JWTs, private keys, and DB
    # connection strings while avoiding source-code false positives.
    scrubbed = redact_sensitive_text(
        scrubbed,
        force=True,
        file_read=True,
        redact_url_credentials=True,
        non_reusable=True,
    )

    # Assignment/JSON redaction is the only material behavior suppressed by
    # file_read mode. Gate that second pass so ordinary persistence remains a
    # one-pass operation.
    if "=" in scrubbed or ":" in scrubbed:
        lowered = scrubbed.lower()
        if any(hint in lowered for hint in _CONFIG_SECRET_HINTS):
            scrubbed = redact_sensitive_text(
                scrubbed,
                force=True,
                redact_url_credentials=True,
                non_reusable=True,
            )
    return scrubbed


def _remaining_count(value: Mapping[Any, Any], consumed: int) -> int | None:
    try:
        return max(0, len(value) - consumed)
    except (TypeError, ValueError):
        return None


def sanitize_for_persistence(
    value: Any,
    *,
    _depth: int = 0,
    _seen: set[int] | None = None,
) -> Any:
    """Return a bounded, JSON-safe, forcibly redacted representation.

    Known token forms, configured provider-secret values, auth/URL credentials,
    and secret-valued mapping keys are scrubbed even when live-output redaction
    is disabled. Cyclic, oversized, and exotic values become explicit markers
    rather than making persistence unbounded or failing after a side effect.
    """

    if _depth > _MAX_DEPTH:
        return "[persistence depth limit]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"[binary omitted at persistence boundary; {len(value)} bytes]"

    seen = _seen if _seen is not None else set()
    marker = id(value)
    if marker in seen:
        return "[cyclic value omitted at persistence boundary]"

    if isinstance(value, Mapping):
        seen.add(marker)
        try:
            output: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= _MAX_ITEMS:
                    remaining = _remaining_count(value, _MAX_ITEMS)
                    detail = (
                        f"{remaining} mapping entries omitted"
                        if remaining is not None
                        else "additional mapping entries omitted"
                    )
                    output["__persistence_truncated__"] = detail
                    break
                name = str(key)
                safe_name = _redact_string(name)
                output[safe_name] = (
                    PERSISTENCE_REDACTION
                    if _is_sensitive_key(name)
                    else sanitize_for_persistence(
                        item, _depth=_depth + 1, _seen=seen
                    )
                )
            return output
        finally:
            seen.remove(marker)

    if isinstance(value, (list, tuple, set, frozenset)):
        seen.add(marker)
        try:
            values = list(value)
            output = [
                sanitize_for_persistence(
                    item, _depth=_depth + 1, _seen=seen
                )
                for item in values[:_MAX_ITEMS]
            ]
            if len(values) > _MAX_ITEMS:
                output.append(
                    f"[{len(values) - _MAX_ITEMS} collection items omitted]"
                )
            return output
        finally:
            seen.remove(marker)

    # Unknown objects do not get to break journal serialization. Their repr is
    # still forced through the same redactor before persistence.
    try:
        rendered = repr(value)
    except Exception:
        rendered = f"<{type(value).__name__}>"
    return sanitize_for_persistence(
        rendered, _depth=_depth + 1, _seen=seen
    )


def _omitted_body(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        size: int | None = len(value)
        unit = "characters"
    elif isinstance(value, (bytes, bytearray, memoryview)):
        size = len(value)
        unit = "bytes"
    else:
        try:
            size = len(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            size = None
        unit = "items"
    marker: dict[str, Any] = {
        "__omitted__": True,
        "reason": "tool_body",
        "unit": unit,
    }
    if size is not None:
        marker["size"] = size
    return marker


def _omit_tool_bodies(
    value: Any,
    *,
    _depth: int = 0,
    _seen: set[int] | None = None,
) -> Any:
    if _depth > _MAX_DEPTH:
        return "[persistence depth limit]"
    if not isinstance(value, (Mapping, list, tuple, set, frozenset)):
        return value

    seen = _seen if _seen is not None else set()
    marker = id(value)
    if marker in seen:
        return "[cyclic value omitted at persistence boundary]"
    seen.add(marker)
    try:
        if isinstance(value, Mapping):
            shaped: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= _MAX_ITEMS:
                    shaped["__persistence_truncated__"] = (
                        "additional mapping entries omitted"
                    )
                    break
                name = str(key)
                shaped[name] = (
                    _omitted_body(item)
                    if _normalise_key(name) in _TOOL_BODY_KEYS
                    else _omit_tool_bodies(
                        item, _depth=_depth + 1, _seen=seen
                    )
                )
            return shaped

        values = list(value)
        shaped_values = [
            _omit_tool_bodies(item, _depth=_depth + 1, _seen=seen)
            for item in values[:_MAX_ITEMS]
        ]
        if len(values) > _MAX_ITEMS:
            shaped_values.append("[additional collection items omitted]")
        return shaped_values
    finally:
        seen.remove(marker)


def sanitize_tool_arguments(
    arguments: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Prepare tool arguments for a durable/telemetry sink.

    Body omission is recursive because MCP/browser/API tools commonly nest a
    request body below one or more options objects.
    """

    if not arguments:
        return {}
    sanitized = sanitize_for_persistence(_omit_tool_bodies(arguments))
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}


def sanitize_event_payload(
    event_type: str,
    payload: Mapping[str, Any] | Any,
) -> dict[str, Any]:
    """Apply event-aware shaping and one recursive sanitization pass.

    Tool intent omission lives here—not only in tool middleware—so every
    present and future journal caller receives the same guarantee.
    """

    shaped: Any = payload
    if str(event_type) == "tool.intent" and isinstance(payload, Mapping):
        shaped = dict(payload)
        for field in ("args", "arguments"):
            if field in shaped:
                shaped[field] = _omit_tool_bodies(shaped[field])
    sanitized = sanitize_for_persistence(shaped)
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}
