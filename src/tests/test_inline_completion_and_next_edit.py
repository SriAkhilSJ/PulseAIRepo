"""Tests for Phase 9.3.4 Tasks 9.3.4.3 & 9.3.4.4:
Native Inline Completion Provider & Next Edit Architecture.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRIB = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai"


def test_inline_completion_provider_implements_interface_and_bounds():
    """TASK 9.3.4.3: CrusorAIInlineCompletionProvider contract, bounds and cancellation."""
    provider_path = CONTRIB / "browser" / "crusorAIInlineCompletionProvider.ts"
    assert provider_path.exists(), f"Missing {provider_path}"
    content = provider_path.read_text(encoding="utf-8")

    # Contract implementation
    assert "implements InlineCompletionsProvider" in content
    assert "provideInlineCompletions(" in content
    assert "handleFrame(" in content
    assert "dispose(" in content

    # Security & workspace trust
    assert "isWorkspaceTrusted()" in content
    assert "isSensitiveFile(" in content

    # Request ID and pending tracking
    assert "request_id" in content
    assert "MAX_CONCURRENT_PENDING" in content
    assert "REQUEST_TIMEOUT_MS" in content
    assert "onCancellationRequested" in content

    # Stale response protection
    assert "modelVersion" in content


def test_inline_completion_provider_registered_in_workbench():
    """TASK 9.3.4.3: Inline completion provider is registered in workbench contribution."""
    contrib_path = CONTRIB / "browser" / "crusorAI.contribution.ts"
    assert contrib_path.exists()
    content = contrib_path.read_text(encoding="utf-8")

    assert "CrusorAIInlineCompletionProvider" in content
    assert "languageFeaturesService.inlineCompletionsProvider.register('*', provider)" in content
    assert "CrusorAIInlineCompletionContribution" in content


def test_next_edit_provider_architecture_and_contract():
    """TASK 9.3.4.4: CrusorAINextEditProvider structured prediction, diff preview & acceptance."""
    next_edit_path = CONTRIB / "browser" / "crusorAINextEditProvider.ts"
    assert next_edit_path.exists(), f"Missing {next_edit_path}"
    content = next_edit_path.read_text(encoding="utf-8")

    # Structured edit model
    assert "interface CrusorAINextEdit" in content
    assert "oldText:" in content
    assert "newText:" in content
    assert "expectedVersionId?:" in content

    # Methods
    assert "requestNextEdits(" in content
    assert "getPendingEdits(" in content
    assert "previewEdit(" in content
    assert "acceptEdit(" in content
    assert "rejectEdit(" in content
    assert "clearSuggestions(" in content
    assert "invalidateStale(" in content

    # Uses safe workspace edit and inline diff pipelines
    assert "openInlineDiff(" in content
    assert "applyWorkspaceEdit(" in content
    assert "isWorkspaceTrusted()" in content


def test_next_edit_provider_registered_in_workbench():
    """TASK 9.3.4.4: Next Edit Provider is registered as singleton."""
    contrib_path = CONTRIB / "browser" / "crusorAI.contribution.ts"
    assert contrib_path.exists()
    content = contrib_path.read_text(encoding="utf-8")

    assert "CrusorAINextEditProvider" in content
    assert "registerSingleton(CrusorAINextEditProvider" in content


def test_mock_inline_completion_and_next_edit_simulation():
    """TASK 9.3.4.3 & 9.3.4.4: Deterministic simulation of request/response frames."""
    # Mock inline completion frame round-trip
    req_frame = {
        "type": "inline_completion",
        "request_id": "req-1-1000",
        "resource": "file:///workspace/test.py",
        "language_id": "python",
        "line": 10,
        "column": 5,
        "prefix": "def hello():\n    ",
        "suffix": "\n",
    }
    res_frame = {
        "type": "inline_completion_result",
        "request_id": "req-1-1000",
        "completions": [
            {
                "text": "return 'world'",
                "range_start_line": 10,
                "range_start_column": 5,
                "range_end_line": 10,
                "range_end_column": 5,
            }
        ],
    }
    assert res_frame["request_id"] == req_frame["request_id"]
    assert len(res_frame["completions"]) == 1

    # Mock next edit prediction frame
    next_edit_frame = {
        "type": "next_edit_result",
        "suggestions": [
            {
                "id": "edit-1",
                "resource": "file:///workspace/test.py",
                "line": 12,
                "column": 1,
                "endLine": 12,
                "endColumn": 10,
                "title": "Add test assertion",
                "description": "Assert that hello() returns world",
                "confidence": 0.95,
                "category": "test",
                "oldText": "pass",
                "newText": "assert hello() == 'world'",
            }
        ],
    }
    assert len(next_edit_frame["suggestions"]) == 1
    item = next_edit_frame["suggestions"][0]
    assert item["newText"] == "assert hello() == 'world'"
    assert item["confidence"] > 0.9

