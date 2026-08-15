"""Pins for the Code OSS sensor/actuator capability boundary."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "desktop" / "src" / "vs" / "workbench" / "contrib" / "pulseai" / "common"
CATALOG = COMMON / "pulseAIWorkbenchCapabilities.ts"
HOST = COMMON / "pulseAIWorkbenchService.ts"
IMPLEMENTATION = COMMON.parent / "browser" / "pulseAIWorkbenchService.ts"
AUDIT = ROOT / "docs" / "VSCODE_AGENT_CAPABILITIES_AUDIT.md"


def _rows():
    text = CATALOG.read_text(encoding="utf-8")
    pattern = re.compile(
        r"cap\('([^']+)', '([^']+)', '([^']+)', '([^']+)'(?:, (true|false))?\)"
    )
    return [match.groups() for match in pattern.finditer(text)]


def test_capability_catalog_is_unique_and_broad():
    rows = _rows()
    ids = [row[0] for row in rows]
    assert len(ids) >= 28
    assert len(ids) == len(set(ids))
    for required in (
        "editor.dirtyText", "language.definitions", "diagnostics.markers",
        "edit.bulkApply", "tasks.discover", "tasks.run", "tests.run", "terminal.native", "scm.state",
        "mcp.tools", "remote.authority", "secrets.pulseOwned",
    ):
        assert required in ids


def test_every_mutating_or_execution_capability_requires_trust():
    for identifier, _phase, risk, _provider, requires_trust in _rows():
        if risk in {"mutate", "execute", "credential"}:
            assert requires_trust == "true", f"{identifier} must require workspace trust"


def test_host_contract_has_safe_context_and_actuation_seams():
    text = HOST.read_text(encoding="utf-8")
    for method in (
        "getActiveEditorContext", "getDiagnostics", "getDocumentSymbols",
        "getDefinitions", "getReferences", "searchWorkspace", "getSCMState", "openNativeDiff",
        "applyWorkspaceEdit", "discoverTasks", "runTask", "runTests", "runInTerminal", "requestWorkspaceTrust",
    ):
        assert method in text
    assert "expectedVersionId" in text
    assert "approvalToolId" in text


def test_phase_a_adapter_uses_dirty_buffers_markers_and_language_providers():
    text = IMPLEMENTATION.read_text(encoding="utf-8")
    for receipt in (
        "activeTextEditorControl", "textFileService.isDirty", "markerService.read",
        "documentSymbolProvider.ordered", "definitionProvider.ordered",
        "referenceProvider.ordered", "createModelReference", "openNativeDiff",
        "bulkEditService.apply", "expectedVersionId", "approvalToolId",
        "queryBuilder.text", "searchService.textSearch", "scmService.repositories",
        "testService.syncTests", "testService.runTests", "TestResultState.Passed",
        "taskService.getKnownTasks", "TaskRunSource.ChatAgent",
        "createAndFocusTerminal", "instance.sendText", "requestWorkspaceTrust",
        "TerminalCapability.CommandDetection", "onCommandFinished", "onLineData",
        "MAX_TERMINAL_OUTPUT_CHARS", "state: 'timed_out'", "sendSignal('SIGINT')",
    ):
        assert receipt in text
    assert "from 'node:" not in text
    assert "slice(0, 32_000)" in text
    assert "Pulse cannot apply workspace edits before workspace trust is granted" in text
    assert "Pulse cannot run terminal commands before workspace trust is granted" in text
    assert "Pulse cannot run tests before workspace trust is granted" in text
    assert "Pulse cannot run tasks before workspace trust is granted" in text
    assert "confirmBeforeUndo: true" in text
    assert "expectedVersionId" in HOST.read_text(encoding="utf-8")


def test_audit_forbids_cross_extension_secret_access():
    text = AUDIT.read_text(encoding="utf-8")
    assert "Never enumerate or read another extension's secrets" in text
    assert "ISecretStorageService" in text
    assert "IWorkspaceTrust" in text
