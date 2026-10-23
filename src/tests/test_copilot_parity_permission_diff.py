"""Tests for GitHub Copilot parity: Permission Handling and Diff View enhancements."""
from __future__ import annotations

from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
FORK = ROOT / "desktop" / "vscode"
CRUSOR = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai"


def _text(*parts: str) -> str:
    return CRUSOR.joinpath(*parts).read_text(encoding="utf-8")


def test_diff_payload_for_file_mutations(tmp_path):
    """SafeToolNode._diff_payload produces unified diffs with hunks and stats."""
    from src.graphs.chat_graph import SafeToolNode
    from src.context.safety_guard import SafetyGuard

    node = SafeToolNode([], SafetyGuard(str(tmp_path)))

    # Test file create
    tc_create = {
        "id": "tc-1",
        "name": "write_file",
        "args": {"path": "hello.txt", "content": "hello world\n"},
    }
    payload = node._diff_payload(tc_create, str(tmp_path))
    assert payload is not None
    assert payload["kind"] == "file"
    assert payload["action"] == "create"
    assert payload["old_text"] is None
    assert payload["new_text"] == "hello world\n"
    assert "+hello world" in payload["diff"]
    assert payload["stats"]["added"] == 1
    assert payload["stats"]["removed"] == 0

    # Test file modify
    (tmp_path / "hello.txt").write_text("hello world\n", encoding="utf-8")
    tc_edit = {
        "id": "tc-2",
        "name": "edit_file",
        "args": {"path": "hello.txt", "old_text": "hello world\n", "new_text": "hello arena\n"},
    }
    payload_edit = node._diff_payload(tc_edit, str(tmp_path))
    assert payload_edit is not None
    assert payload_edit["kind"] == "file"
    assert payload_edit["action"] == "modify"
    assert payload_edit["old_text"] == "hello world\n"
    assert payload_edit["new_text"] == "hello arena\n"
    assert "-hello world" in payload_edit["diff"]
    assert "+hello arena" in payload_edit["diff"]
    assert payload_edit["stats"]["added"] == 1
    assert payload_edit["stats"]["removed"] == 1


def test_diff_payload_for_shell_commands(tmp_path):
    """SafeToolNode._diff_payload produces risk metadata for shell commands."""
    from src.graphs.chat_graph import SafeToolNode
    from src.context.safety_guard import SafetyGuard

    node = SafeToolNode([], SafetyGuard(str(tmp_path)))
    tc_shell = {
        "id": "tc-shell-1",
        "name": "run_terminal",
        "args": {"command": "rm -rf /tmp/data"},
    }
    payload = node._diff_payload(tc_shell, str(tmp_path))
    assert payload is not None
    assert payload["kind"] == "shell"
    assert payload["command"] == "rm -rf /tmp/data"
    assert "risk" in payload


def test_diff_commands_registered_in_contribution():
    """AcceptDiff and RejectDiff commands are registered in Crusor contribution."""
    contrib = _text("browser", "crusorAI.contribution.ts")
    assert "CrusorAICommandId.AcceptDiff" in contrib
    assert "CrusorAICommandId.RejectDiff" in contrib
    assert "crusorai.hasActiveDiff" in contrib
    assert "acceptActiveDiff" in contrib
    assert "rejectActiveDiff" in contrib


def test_workbench_service_tracks_active_diffs_and_resolves():
    """CrusorAIWorkbenchService exposes onDidResolveDiff and active diff tracking."""
    service_ts = _text("browser", "crusorAIWorkbenchService.ts")
    common_ts = _text("common", "crusorAIWorkbenchService.ts")
    assert "onDidResolveDiff" in common_ts
    assert "acceptActiveDiff(): void" in common_ts
    assert "rejectActiveDiff(): void" in common_ts
    assert "hasActiveDiff(): boolean" in common_ts

    assert "hasActiveDiffKey" in service_ts
    assert "crusorai.hasActiveDiff" in service_ts
    assert "this._onDidResolveDiff.fire({ toolId: diff.toolId, approved: true })" in service_ts
    assert "this._onDidResolveDiff.fire({ toolId: diff.toolId, approved: false })" in service_ts


def test_approval_dock_renders_review_action_and_plain_hint():
    """The current slim permission bar keeps a file diff one click away.

    Inline preview classes belonged to the rejected card design. The native
    editor diff, +/- summary, plain hint, and three explicit verdicts are the
    active contract.
    """
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "crusorai-approval-review" in renderer
    assert "host.openDiff(approval.toolId)" in renderer
    assert "crusorai-diff-count" in renderer
    assert "function approvalHintText" in renderer
    assert "crusorai-approval-diff-preview" not in renderer
    assert "crusorai-approval-warning" not in renderer
    assert "crusorai-approval-risk-badge" not in renderer
    assert ".crusorai-approval-review" in css
    assert ".crusorai-approval-diff-preview" not in css
    assert ".crusorai-approval-warning" not in css


def test_renderer_service_wires_diff_resolution_and_robust_open_diff():
    """CrusorAIRendererService listens to diff resolution and handles write_file openDiff."""
    service = _text("browser", "crusorAIRendererService.ts")
    assert "this.workbenchService.onDidResolveDiff" in service
    assert "this.host.replyToSafety(event.toolId, event.approved)" in service
    assert "value?.content === 'string'" in service or "typeof value?.content === 'string'" in service
