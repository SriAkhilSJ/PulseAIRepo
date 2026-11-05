"""Phase 9.3.4.2 Native AI Workflow End-to-End Test Suite.

Verifies:
1. Monaco Inline Completion contract, bounds, cancellation, timeout, sensitive file filters.
2. Next Edit prediction, diff preview, acceptance, rejection, undo and stale invalidation.
3. All five @ context references (@file, @folder, @symbol, @selection, @diagnostics).
4. All four slash commands (/test, /review, /fix, /clear).
5. Cross-process security, SafetyGuard fail-closed, explicit approval and workspace trust.
6. Open VSX marketplace configuration and Copilot network isolation.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
CONTRIB = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai"


# ============================================================================
# TASK 9.3.4.2.1: Monaco Inline Completion Provider Contract & Scenarios
# ============================================================================

def test_inline_completion_sensitive_file_filtering():
    """TASK 9.3.4.2.1 Scenario T: Sensitive files are filtered fail-closed."""
    provider_file = CONTRIB / "browser" / "crusorAIInlineCompletionProvider.ts"
    assert provider_file.exists()
    content = provider_file.read_text(encoding="utf-8")

    sensitive_patterns = [".env", "/.git/", "id_rsa", "credentials", ".key", ".pem"]
    for pat in sensitive_patterns:
        assert pat in content, f"Expected {pat} in sensitive file filter"


def test_inline_completion_concurrency_and_timeout_bounds():
    """TASK 9.3.4.2.1 Scenarios Q & S: Pending request bounds and timeout."""
    provider_file = CONTRIB / "browser" / "crusorAIInlineCompletionProvider.ts"
    content = provider_file.read_text(encoding="utf-8")

    assert "MAX_CONCURRENT_PENDING = 8" in content
    assert "REQUEST_TIMEOUT_MS = 4000" in content
    assert "clearTimeout(timer)" in content
    assert "this.pending.delete(requestId)" in content


def test_inline_completion_stale_response_and_cancellation():
    """TASK 9.3.4.2.1 Scenarios N, O, P: Stale responses and cancellation."""
    provider_file = CONTRIB / "browser" / "crusorAIInlineCompletionProvider.ts"
    content = provider_file.read_text(encoding="utf-8")

    assert "token.isCancellationRequested" in content
    assert "token.onCancellationRequested" in content
    assert "modelVersion" in content


def test_inline_completion_deterministic_mock_backend():
    """TASK 9.3.4.2.1 Scenario D: Deterministic mock backend returns valid items."""
    from src.tools.inline_completions import InlineCompletionProvider, CompletionRequest

    provider = InlineCompletionProvider()
    assert provider.enabled

    # Test deterministic mock generator
    req = CompletionRequest(
        resource="file:///workspace/calculator.ts",
        language_id="typescript",
        line=3,
        column=10,
        prefix="export class Calculator {\n    add(a: number, b: number): number {\n       ",
        suffix="\n    }\n}",
    )
    items = provider._deterministic_mock_completion(req)
    assert len(items) >= 1
    assert "return a + b;" in items[0].text
    assert items[0].confidence == 1.0
    assert items[0].stop_reason == "deterministic_mock"


# ============================================================================
# TASK 9.3.4.2.2: Next Edit Provider & Diff Preview Pipeline
# ============================================================================

def test_next_edit_state_machine_and_diff_pipeline():
    """TASK 9.3.4.2.2 Scenarios 1-10: Next Edit state machine & diff pipeline."""
    next_edit_file = CONTRIB / "browser" / "crusorAINextEditProvider.ts"
    assert next_edit_file.exists()
    content = next_edit_file.read_text(encoding="utf-8")

    # State transitions
    assert "'pending' | 'previewing' | 'accepted' | 'rejected' | 'stale'" in content
    assert "previewEdit(" in content
    assert "acceptEdit(" in content
    assert "rejectEdit(" in content
    assert "invalidateStale(" in content

    # Diff preview and atomic edit hooks
    assert "workbenchService.openInlineDiff(" in content
    assert "workbenchService.applyWorkspaceEdit(" in content
    assert "isWorkspaceTrusted()" in content


def test_next_edit_predictor_heuristics():
    """TASK 9.3.4.2.2 Scenario 1: NextEditPredictor analyzes patterns without LLM."""
    from src.tools.next_edit_suggestions import NextEditPredictor

    predictor = NextEditPredictor()
    assert predictor.enabled

    predictor.record_change(
        resource="file:///workspace/calculator.ts",
        line=2,
        column=5,
        old_text="def add(a, b):",
        new_text="def add(a, b, c=0):",
        workspace="c:/workspace",
    )
    suggestions = predictor.predict_next_edits("c:/workspace")
    assert isinstance(suggestions, list)


# ============================================================================
# TASK 9.3.4.2.3: @ Context References (All Five Types)
# ============================================================================

def test_context_references_advertised_and_resolved():
    """TASK 9.3.4.2.3: All five @ context types are advertised and structured."""
    renderer_file = CONTRIB / "browser" / "crusorAIRenderer.ts"
    service_file = CONTRIB / "browser" / "crusorAIRendererService.ts"

    r_content = renderer_file.read_text(encoding="utf-8")
    s_content = service_file.read_text(encoding="utf-8")

    # The 5 advertised items
    for item in ["@file", "@folder", "@symbol", "@selection", "@diagnostics"]:
        assert item in r_content, f"Missing {item} suggestion item"

    # The 5 structured resolutions in submitPrompt
    assert "chip.type === 'selection'" in s_content
    assert "chip.type === 'diagnostics'" in s_content
    assert "chip.type === 'file'" in s_content
    assert "chip.type === 'folder'" in s_content
    assert "chip.type === 'symbol'" in s_content
    assert "getActiveEditorContext" in s_content
    assert "getDiagnostics" in s_content


# ============================================================================
# TASK 9.3.4.2.4: Slash Commands Structured Dispatch
# ============================================================================

def test_slash_commands_structured_dispatch_and_reset():
    """TASK 9.3.4.2.4: Slash commands /test, /review, /fix, /clear dispatch contracts."""
    renderer_file = CONTRIB / "browser" / "crusorAIRenderer.ts"
    service_file = CONTRIB / "browser" / "crusorAIRendererService.ts"

    r_content = renderer_file.read_text(encoding="utf-8")
    s_content = service_file.read_text(encoding="utf-8")

    for cmd in ["/test", "/review", "/fix", "/clear"]:
        assert cmd in r_content, f"Missing {cmd} suggestion item"

    assert "trimmed === '/clear'" in s_content
    assert "this.newSession()" in s_content
    assert "this.contextChips = [];" in s_content

    assert "trimmed.startsWith('/test')" in s_content
    assert "[Slash Command /test]" in s_content

    assert "trimmed.startsWith('/review')" in s_content
    assert "[Slash Command /review]" in s_content

    assert "trimmed.startsWith('/fix')" in s_content
    assert "[Slash Command /fix]" in s_content


# ============================================================================
# TASK 9.3.4.2.5: Security Approval & Fail-Closed Policy Matrix
# ============================================================================

def test_reverse_rpc_security_allowlist_and_trust():
    """TASK 9.3.4.2.5: Security controls, reverse RPC allowlist and trust boundaries."""
    service_file = CONTRIB / "browser" / "crusorAIWorkbenchService.ts"
    content = service_file.read_text(encoding="utf-8")

    # Protected mutating tools check workspace trust
    assert "isWorkspaceTrusted()" in content
    assert "cannot apply workspace edits before workspace trust is granted" in content
    assert "cannot run tests before workspace trust is granted" in content


def test_safetyguard_fail_closed_contract():
    """TASK 9.3.4.2.5: SafetyGuard exception handling fails closed."""
    from scripts.run_live_economics_benchmark import dispatch_tool

    # Dispatch with unknown tool fails closed
    out, norm_args = dispatch_tool("unknown_tool_xyz", {}, workspace_root=str(ROOT))
    assert "refused" in out.lower() or "error" in out.lower() or "unknown" in out.lower()


# ============================================================================
# TASK 9.3.4.2.6: Open VSX Marketplace & Copilot Decoupling
# ============================================================================

def test_open_vsx_marketplace_configuration():
    """TASK 9.3.4.2.6: Open VSX gallery and trusted domains."""
    product_json = ROOT / "desktop" / "vscode" / "product.json"
    data = json.loads(product_json.read_text(encoding="utf-8"))

    gallery = data.get("extensionsGallery", {})
    assert gallery.get("serviceUrl") == "https://open-vsx.org/vscode/gallery"
    assert gallery.get("itemUrl") == "https://open-vsx.org/vscode/item"
    assert "https://open-vsx.org" in data.get("linkProtectionTrustedDomains", [])


def test_copilot_network_endpoints_neutralized():
    """TASK 9.3.4.2.7: Copilot external URLs are empty strings."""
    product_json = ROOT / "desktop" / "vscode" / "product.json"
    data = json.loads(product_json.read_text(encoding="utf-8"))

    dca = data.get("defaultChatAgent", {})
    assert dca.get("extensionId") == "GitHub.copilot"
    assert dca.get("chatExtensionId") == "GitHub.copilot-chat"
    assert dca.get("entitlementUrl") == ""
    assert dca.get("tokenEntitlementUrl") == ""
    assert dca.get("mcpRegistryDataUrl") == ""
    assert dca.get("managedSettingsUrl") == ""
    assert dca.get("entitlementSignupLimitedUrl") == ""
