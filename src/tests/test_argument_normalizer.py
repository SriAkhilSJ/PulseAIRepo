"""Unit tests for Phase 1 Refined SafeArgumentNormalizer (CrusorAI 2.1).

Validates:
1. Standardized status strings: "applied", "rejected", "unmodified".
2. Canonical edit_file schema: maps old_string -> old_text, new_string -> new_text.
3. Ambiguous 'target' / 'replacement' are rejected / ignored as aliases.
4. Conflicting alias and canonical arguments fail closed.
5. Multi-target tools (copy_file) fail closed on ambiguous 'path'.
6. Audit logs redact API keys and passwords in original_args.
"""
import pytest
from src.runtime.argument_normalizer import (
    NormalizationResult,
    normalize_tool_arguments,
    redact_argument_value,
)


def test_standardized_status_applied():
    args = {"path": "server.py", "old_string": "hello", "new_string": "world"}
    result = normalize_tool_arguments("edit_file", args)

    assert result.status == "applied"
    assert result.normalized_args == {"path": "server.py", "old_text": "hello", "new_text": "world"}
    assert result.error is None


def test_standardized_status_unmodified():
    args = {"path": "server.py", "old_text": "hello", "new_text": "world"}
    result = normalize_tool_arguments("edit_file", args)

    assert result.status == "unmodified"
    assert result.normalized_args == args
    assert result.error is None


def test_ambiguous_target_is_not_whitelisted():
    # 'target' was flagged as ambiguous in review; must not be coerced to old_text
    args = {"path": "server.py", "target": "some_func", "new_text": "new_func"}
    result = normalize_tool_arguments("edit_file", args)

    # Remains unmodified because 'target' is not a whitelisted alias
    assert result.status == "unmodified"
    assert "old_text" not in result.normalized_args
    assert result.normalized_args.get("target") == "some_func"


def test_conflicting_alias_and_canonical_rejection():
    args = {"path": "app.py", "old_string": "val1", "old_text": "val2"}
    result = normalize_tool_arguments("edit_file", args)

    assert result.status == "rejected"
    assert "CONFLICTING_ARGUMENTS_ERROR" in result.error
    assert result.normalized_args == {}


def test_canonical_precedence_when_identical():
    args = {"path": "app.py", "old_string": "identical", "old_text": "identical"}
    result = normalize_tool_arguments("edit_file", args)

    assert result.status == "applied"
    assert result.normalized_args == {"path": "app.py", "old_text": "identical"}
    assert "old_string" not in result.normalized_args


def test_multi_target_ambiguity_rejection():
    args = {"path": "file.txt"}
    result = normalize_tool_arguments("copy_file", args)

    assert result.status == "rejected"
    assert "AMBIGUOUS_ARGUMENT_ERROR" in result.error


def test_audit_logs_redact_secrets():
    args = {
        "path": "config.json",
        "file_path": "config.json",
        "token": "sk-ant-api03-12345678901234567890",
        "nested": {"password": "password='my_secret_pass'"}
    }
    result = normalize_tool_arguments("read_file", args)

    assert result.status == "applied"
    assert result.original_args is not None
    assert "sk-ant" not in str(result.original_args)
    assert "[REDACTED_SECRET]" in result.original_args["token"]
