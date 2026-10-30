"""Unit tests for SafeArgumentNormalizer (CrusorAI 2.1).

Validates:
1. Canonical argument precedence (no overwriting).
2. Conflicting alias and canonical rejection.
3. Multi-target ambiguity rejection (fail-closed).
4. Unambiguous whitelist promotions.
5. Audit provenance preservation.
"""
import pytest
from src.runtime.argument_normalizer import (
    NormalizationResult,
    normalize_tool_arguments,
)


def test_unambiguous_alias_promotion():
    # edit_file: old_text -> old_string
    args = {"path": "server.py", "old_text": "hello", "new_string": "world"}
    result = normalize_tool_arguments("edit_file", args)
    
    assert result.status == "ok"
    assert result.normalized_args == {"path": "server.py", "old_string": "hello", "new_string": "world"}
    assert result.error is None
    assert result.original_args == args


def test_canonical_argument_takes_precedence_when_identical():
    # If both supplied and values match, alias is silently dropped
    args = {"path": "app.py", "old_text": "foo", "old_string": "foo"}
    result = normalize_tool_arguments("edit_file", args)

    assert result.status == "ok"
    assert result.normalized_args == {"path": "app.py", "old_string": "foo"}
    assert "old_text" not in result.normalized_args


def test_conflicting_alias_and_canonical_is_rejected():
    # Peer review requirement: Conflicting alias must be rejected!
    args = {"path": "app.py", "old_text": "first_value", "old_string": "conflicting_value"}
    result = normalize_tool_arguments("edit_file", args)

    assert result.status == "rejected"
    assert "CONFLICTING_ARGUMENTS_ERROR" in result.error
    assert result.normalized_args == {}


def test_ambiguous_multi_target_tools_fail_closed():
    # Peer review requirement: copy_file(src, dst) cannot accept ambiguous 'path'
    args = {"path": "source.py"}
    result = normalize_tool_arguments("copy_file", args)

    assert result.status == "rejected"
    assert "AMBIGUOUS_ARGUMENT_ERROR" in result.error
    assert result.normalized_args == {}


def test_unmodified_tool_arguments():
    # Clean canonical call passes unmodified
    args = {"path": "main.py", "old_string": "a", "new_string": "b"}
    result = normalize_tool_arguments("edit_file", args)

    assert result.status == "unmodified"
    assert result.normalized_args == args
    assert result.error is None


def test_invalid_type_rejection():
    # Passing a non-dict should be rejected cleanly
    result = normalize_tool_arguments("edit_file", "invalid string payload")  # type: ignore

    assert result.status == "rejected"
    assert "INVALID_ARGUMENTS_TYPE" in result.error
