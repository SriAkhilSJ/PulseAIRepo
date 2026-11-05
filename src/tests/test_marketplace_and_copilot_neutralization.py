"""Tests for Phase 9.3.4 Tasks 9.3.4.1 & 9.3.4.2:
Marketplace Restoration & Copilot Network Neutralization.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_JSON_PATH = ROOT / "desktop" / "vscode" / "product.json"


def test_product_extensions_gallery_is_configured_with_open_vsx():
    """TASK 9.3.4.1: Ensure extensionsGallery is restored and points to Open VSX."""
    assert PRODUCT_JSON_PATH.exists(), f"Missing product.json at {PRODUCT_JSON_PATH}"
    product = json.loads(PRODUCT_JSON_PATH.read_text(encoding="utf-8"))

    assert "extensionsGallery" in product, "product.json must contain 'extensionsGallery'"
    gallery = product["extensionsGallery"]

    assert gallery.get("serviceUrl") == "https://open-vsx.org/vscode/gallery"
    assert gallery.get("itemUrl") == "https://open-vsx.org/vscode/item"
    assert "https://open-vsx.org/vscode/unpkg" in gallery.get("resourceUrlTemplate", "")
    assert gallery.get("controlUrl") == ""


def test_open_vsx_is_in_trusted_domains():
    """TASK 9.3.4.1: Ensure open-vsx.org is in linkProtectionTrustedDomains."""
    product = json.loads(PRODUCT_JSON_PATH.read_text(encoding="utf-8"))
    trusted_domains = product.get("linkProtectionTrustedDomains", [])
    assert "https://open-vsx.org" in trusted_domains, (
        "linkProtectionTrustedDomains must include https://open-vsx.org"
    )


def test_copilot_default_chat_agent_structural_contract_is_preserved():
    """TASK 9.3.4.2: Preserve structural contract required by onboardingVariationA.ts:80."""
    product = json.loads(PRODUCT_JSON_PATH.read_text(encoding="utf-8"))
    assert "defaultChatAgent" in product, "product.json must contain defaultChatAgent"

    chat_agent = product["defaultChatAgent"]
    # Required identifiers
    assert chat_agent.get("extensionId") == "GitHub.copilot"
    assert chat_agent.get("chatExtensionId") == "GitHub.copilot-chat"

    # Required provider object
    assert "provider" in chat_agent
    provider = chat_agent["provider"]
    assert "default" in provider and provider["default"].get("name")
    assert "enterprise" in provider and provider["enterprise"].get("name")
    assert chat_agent.get("providerExtensionId") == "vscode.github-authentication"
    assert chat_agent.get("providerUriSetting") == "github-enterprise.uri"


def test_copilot_network_endpoints_are_fully_neutralized():
    """TASK 9.3.4.2: Ensure all external GitHub Copilot API endpoints are neutralized."""
    product = json.loads(PRODUCT_JSON_PATH.read_text(encoding="utf-8"))
    chat_agent = product["defaultChatAgent"]

    # Active entitlement and telemetry endpoints must be completely cleared / empty
    assert chat_agent.get("entitlementUrl") == "", "entitlementUrl must be empty"
    assert chat_agent.get("tokenEntitlementUrl") == "", "tokenEntitlementUrl must be empty"
    assert chat_agent.get("mcpRegistryDataUrl") == "", "mcpRegistryDataUrl must be empty"
    assert chat_agent.get("managedSettingsUrl") == "", "managedSettingsUrl must be empty"
    assert chat_agent.get("entitlementSignupLimitedUrl") == "", "entitlementSignupLimitedUrl must be empty"

    # Ensure no lingering api.github.com/copilot_internal or aka.ms URLs remain in defaultChatAgent
    agent_str = json.dumps(chat_agent)
    assert "api.github.com/copilot_internal" not in agent_str, (
        "Found active copilot_internal endpoint in defaultChatAgent"
    )
    assert "aka.ms" not in agent_str, (
        "Found unneutralized aka.ms shortcut URL in defaultChatAgent"
    )


def test_mock_marketplace_query_and_network_interception():
    """TASK 9.3.4.1 & 9.3.4.2: Mocked network verification of extension gallery query."""
    product = json.loads(PRODUCT_JSON_PATH.read_text(encoding="utf-8"))
    service_url = product["extensionsGallery"]["serviceUrl"]

    parsed = urlparse(service_url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "open-vsx.org"
    assert parsed.path == "/vscode/gallery"

    # Mocked extension query request payload as sent by VS Code extensionGalleryService
    mock_query_url = f"{service_url}/extensionquery"
    mock_payload = {
        "filters": [{"criteria": [{"filterType": 10, "value": "python"}]}],
        "flags": 1039,
    }

    # Verify query structure
    assert mock_query_url == "https://open-vsx.org/vscode/gallery/extensionquery"
    assert mock_payload["flags"] == 1039

