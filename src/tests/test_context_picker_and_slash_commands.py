"""Tests for Task 9.3.4.5 (Interactive @ Context Picker), Task 9.3.4.6 (Slash Commands Palette),
and Task 9.3.4.7 (Cross-Process Security & Fail-Closed Boundaries).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VSCODE_SRC = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai"
RENDERER_FILE = VSCODE_SRC / "browser" / "crusorAIRenderer.ts"
SERVICE_FILE = VSCODE_SRC / "browser" / "crusorAIRendererService.ts"
CSS_FILE = VSCODE_SRC / "browser" / "media" / "crusorAI.css"
WORKBENCH_SERVICE_FILE = VSCODE_SRC / "browser" / "crusorAIWorkbenchService.ts"
HOST_CAPABILITIES_FILE = ROOT / "src" / "runtime" / "host_capabilities.py"


def test_renderer_has_context_chips_and_suggestions():
    """Verify Task 9.3.4.5: Context picker suggestions and chip interfaces are defined."""
    renderer_text = RENDERER_FILE.read_text(encoding="utf-8")
    
    # Interface definitions
    assert "interface CrusorAIContextChip" in renderer_text
    assert "interface CrusorAISuggestionItem" in renderer_text
    
    # Suggested triggers
    assert "AT_CONTEXT_SUGGESTIONS" in renderer_text
    assert "SLASH_COMMAND_SUGGESTIONS" in renderer_text
    
    # Supported context kinds
    for kind in ("@file", "@folder", "@symbol", "@selection", "@diagnostics"):
        assert kind in renderer_text
        
    # Supported slash commands
    for cmd in ("/test", "/review", "/fix", "/clear"):
        assert cmd in renderer_text
        
    # Model integration
    assert "contextChips?: readonly CrusorAIContextChip[]" in renderer_text
    assert "addContextChip?(chip: CrusorAIContextChip): void" in renderer_text
    assert "removeContextChip?(id: string): void" in renderer_text
    assert "clearContextChips?(): void" in renderer_text


def test_renderer_css_has_styling_for_chips_and_suggestions():
    """Verify CSS styling tokens for chips and dropdown suggestion popup."""
    css_text = CSS_FILE.read_text(encoding="utf-8")
    
    assert ".crusorai-context-chips-bar" in css_text
    assert ".crusorai-context-chip" in css_text
    assert ".crusorai-chip-remove" in css_text
    assert ".crusorai-suggestions-box" in css_text
    assert ".crusorai-suggestion-item" in css_text
    assert ".crusorai-suggestion-item.selected" in css_text


def test_renderer_service_handles_slash_commands():
    """Verify Task 9.3.4.6: Slash command interception and transformation."""
    service_text = SERVICE_FILE.read_text(encoding="utf-8")
    
    # /clear handling
    assert "trimmed === '/clear'" in service_text
    assert "this.newSession()" in service_text
    
    # /test handling
    assert "trimmed.startsWith('/test')" in service_text
    assert "[Slash Command /test]" in service_text
    
    # /review handling
    assert "trimmed.startsWith('/review')" in service_text
    assert "[Slash Command /review]" in service_text
    
    # /fix handling
    assert "trimmed.startsWith('/fix')" in service_text
    assert "[Slash Command /fix]" in service_text


def test_renderer_service_resolves_context_chips():
    """Verify Task 9.3.4.5: Structured context chip resolution on submit."""
    service_text = SERVICE_FILE.read_text(encoding="utf-8")
    
    # Context chips state in service and model
    assert "private contextChips: readonly CrusorAIContextChip[] = [];" in service_text
    assert "contextChips: this.contextChips," in service_text
    
    # Resolution logic
    assert "chip.type === 'selection'" in service_text
    assert "this.workbenchService.getActiveEditorContext(true)" in service_text
    assert "chip.type === 'diagnostics'" in service_text
    assert "this.workbenchService.getDiagnostics()" in service_text
    assert "chip.type === 'file'" in service_text
    assert "chip.type === 'folder'" in service_text
    assert "chip.type === 'symbol'" in service_text
    assert "Context References:" in service_text or "### Context References" in service_text


def test_cross_process_security_fail_closed():
    """Verify Task 9.3.4.7: Cross-process security boundary and fail-closed guarantees."""
    # 1. Reverse RPC host capabilities are strictly read-only
    host_caps_text = HOST_CAPABILITIES_FILE.read_text(encoding="utf-8")
    assert "READ_ONLY_CAPABILITIES" in host_caps_text
    # Mutating / executing tools must NOT be in read-only capabilities allowlist
    for dangerous in ("terminal.native", "edit.bulkApply", "tasks.run", "tests.run", "code_exec_tool"):
        assert dangerous not in host_caps_text

    # 2. In workbench service, trust is required before executing or mutating
    wb_service_text = WORKBENCH_SERVICE_FILE.read_text(encoding="utf-8")
    assert "Crusor cannot apply workspace edits before workspace trust is granted" in wb_service_text
    assert "Crusor cannot run terminal commands before workspace trust is granted" in wb_service_text
    assert "Crusor cannot run tests before workspace trust is granted" in wb_service_text
    assert "Crusor cannot run tasks before workspace trust is granted" in wb_service_text

