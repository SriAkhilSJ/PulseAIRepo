"""Safety boundary for values written to durable runtime stores.

The interactive redaction preference is intentionally *not* respected here.
A user may opt into seeing raw values during a live debugging session, but a
credential must not consequently become part of a replayable SQLite journal.

The helpers in this module are deliberately dependency-light so every durable
store can call them without importing the agent graph or tool registry.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from src.utils.redact import redact_sensitive_text

_PERSISTENCE_REDACTION = "«redacted:persistence-secret»"
_MAX_DEPTH = 24
_MAX_ITEMS = 2_000
_MAX_STRING_CHARS = 64_000

# Exact names and narrowly-scoped suffixes avoid masking identifiers such as
# ``session_id`` and counters such as ``token_count``.
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
    "_auth_token",
    "_client_secret",
    "_credential",
    "_password",
    "_private_key",
    "_refresh_token",
    "_secret",
)

# Source/file bodies can contain credentials that have no recognisable vendor
# prefix. Tool-intent rows need their shape and target, not a replayable copy of
# the body. This list is applied only to tool arguments, never to result fields.
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


def _normalise_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def _is_sensitive_key(key: object) -> bool:
    name = _normalise_key(key)
    return name in _SENSITIVE_KEYS or name.endswith(_SENSITIVE_SUFFIXES)


def _omitted_body(value: Any) -> str:
    if isinstance(value, str):
        size = len(value)
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
    detail = f"; {size} {unit}" if size is not None else ""
    return f"[payload omitted at persistence boundary{detail}]"


def sanitize_for_persistence(value: Any, *, _depth: int = 0, _seen: set[int] | None = None) -> Any:
    """Return a JSON-safe, forcibly redacted representation of ``value``.

    This is defense in depth for durable stores: known token forms, auth
    headers, URL credentials, and secret-valued mapping keys are always
    scrubbed even when live-output redaction has been disabled. Oversized and
    cyclic values are represented explicitly rather than making persistence
    unbounded or failing JSON serialization after a side effect has run.
    """

    if _depth > _MAX_DEPTH:
        return "[persistence depth limit]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        if len(value) > _MAX_STRING_CHARS:
            return f"[oversized string omitted at persistence boundary; {len(value)} characters]"
        # First use the file-read mode so prefix-shaped credentials lose the
        # entire random body (ordinary log redaction intentionally preserves a
        # short head/tail for debugging). Then run the full prose/config pass:
        # file-read mode suppresses a few source-code false-positive patterns
        # that remain desirable at this durable boundary.
        scrubbed = redact_sensitive_text(
            value, force=True, file_read=True, redact_url_credentials=True,
        )
        return redact_sensitive_text(
            scrubbed, force=True, redact_url_credentials=True,
        )
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
                    output["__persistence_truncated__"] = f"{len(value) - _MAX_ITEMS} mapping entries omitted"
                    break
                name = str(key)
                output[name] = (
                    _PERSISTENCE_REDACTION
                    if _is_sensitive_key(name)
                    else sanitize_for_persistence(item, _depth=_depth + 1, _seen=seen)
                )
            return output
        finally:
            seen.remove(marker)

    if isinstance(value, (list, tuple, set, frozenset)):
        seen.add(marker)
        try:
            values = list(value)
            output = [
                sanitize_for_persistence(item, _depth=_depth + 1, _seen=seen)
                for item in values[:_MAX_ITEMS]
            ]
            if len(values) > _MAX_ITEMS:
                output.append(f"[{len(values) - _MAX_ITEMS} collection items omitted]")
            return output
        finally:
            seen.remove(marker)

    # Unknown objects must not get a chance to break journal serialization.
    # Their repr is still put through the forced redactor before persistence.
    try:
        rendered = repr(value)
    except Exception:
        rendered = f"<{type(value).__name__}>"
    return sanitize_for_persistence(rendered, _depth=_depth + 1, _seen=seen)


def _omit_tool_bodies(value: Any, *, _depth: int = 0, _seen: set[int] | None = None) -> Any:
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
                    shaped["__persistence_truncated__"] = "additional mapping entries omitted"
                    break
                name = str(key)
                shaped[name] = (
                    _omitted_body(item)
                    if _normalise_key(name) in _TOOL_BODY_KEYS
                    else _omit_tool_bodies(item, _depth=_depth + 1, _seen=seen)
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


def sanitize_tool_arguments(arguments: Mapping[str, Any] | None) -> dict[str, Any]:
    """Prepare tool arguments for an intent row without retaining file bodies.

    Body omission is recursive because MCP/browser/API tools often nest request
    payloads below an options object rather than passing ``content`` at the top
    level.
    """

    if not arguments:
        return {}
    sanitized = sanitize_for_persistence(_omit_tool_bodies(arguments))
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}
