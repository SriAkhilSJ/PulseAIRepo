"""Unit tests for Phase 1 Refined SafeArgumentNormalizer (CrusorAI 2.1).

Validates:
1. Standardized status strings: "applied", "rejected", "unmodified".
2. Canonical edit_file schema: maps old_string -> old_text, new_string -> new_text.
3. read_file & write_file aliases: maps filepath, file, filename, file_path -> path.
4. terminal aliases: maps cmd, exec -> command.
5. Ambiguous 'target' / 'replacement' are rejected / ignored as aliases.
6. Conflicting alias and canonical arguments fail closed.
7. Multi-target tools (copy_file) fail closed on ambiguous 'path'.
8. Key-based recursive secret redaction (password, api_key, access_token, etc.).
9. Audit record generation (get_audit_record) prevents raw normalized_args leaks.
10. Restored invalid-type rejection test (non-dict inputs).
"""
import pytest
from src.runtime.argument_normalizer import (
    NormalizationResult,
    normalize_tool_arguments,
    redact_argument_value,
)


def test_standardized_status_applied_edit_file():
    args = {"path": "server.py", "old_string": "hello", "new_string": "world"}
    result = normalize_tool_arguments("edit_file", args)

    assert result.status == "applied"
    assert result.normalized_args == {"path": "server.py", "old_text": "hello", "new_text": "world"}
    assert result.error is None


def test_standardized_status_applied_read_file_aliases():
    for alias in ["filepath", "file", "filename", "file_path"]:
        args = {alias: "config.json"}
        result = normalize_tool_arguments("read_file", args)
        assert result.status == "applied"
        assert result.normalized_args == {"path": "config.json"}


def test_standardized_status_applied_write_file_aliases():
    args = {"filepath": "output.txt", "content": "data"}
    result = normalize_tool_arguments("write_file", args)
    assert result.status == "applied"
    assert result.normalized_args == {"path": "output.txt", "content": "data"}


def test_standardized_status_applied_terminal_aliases():
    for alias in ["cmd", "exec"]:
        args = {alias: "ls -la"}
        result = normalize_tool_arguments("terminal", args)
        assert result.status == "applied"
        assert result.normalized_args == {"command": "ls -la"}


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


def test_key_based_recursive_secret_redaction():
    # Peer review requirement: JSON dictionaries with keys like password, api_key, access_token
    args = {
        "path": "credentials.json",
        "password": "my_actual_password_123",
        "api_key": "secret123",
        "access_token": "token123",
        "nested": {
            "secret": "very_secret_key",
            "normal_field": "visible_value"
        }
    }
    result = normalize_tool_arguments("read_file", args)

    assert result.original_args is not None
    assert result.original_args["password"] == "[REDACTED_SECRET]"
    assert result.original_args["api_key"] == "[REDACTED_SECRET]"
    assert result.original_args["access_token"] == "[REDACTED_SECRET]"
    assert result.original_args["nested"]["secret"] == "[REDACTED_SECRET]"
    assert result.original_args["nested"]["normal_field"] == "visible_value"

    # Verify audit record redacts normalized_args as well
    audit_record = result.get_audit_record()
    assert audit_record["normalized_args_redacted"]["password"] == "[REDACTED_SECRET]"


def test_invalid_type_rejection():
    # Restored test: Passing a non-dict should be rejected cleanly
    for invalid_arg in ["not a dictionary", 12345, None, ["a", "b"]]:
        result = normalize_tool_arguments("edit_file", invalid_arg)
        assert result.status == "rejected"
        assert "INVALID_ARGUMENTS_TYPE" in result.error
        assert result.normalized_args == {}
