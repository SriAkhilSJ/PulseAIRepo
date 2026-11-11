"""Desktop startup regression: the workbench registers the real chat session
routing singleton before `chat.contextContributions` is instantiated.

The service module was previously side-effect imported only by the separate
sessions app entry, so the regular workbench failed with
"depends on UNKNOWN service chatSessionRoutingProviderService". This test pins
the registration import and the real registerSingleton call.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib"


def test_workbench_chat_contribution_imports_real_routing_service() -> None:
    contribution = (ROOT / "chat" / "browser" / "chat.contribution.ts").read_text(encoding="utf-8")
    assert "sessionRouter/chatSessionRoutingProviderService.js" in contribution


def test_routing_service_registers_the_real_singleton() -> None:
    service = (ROOT / "chat" / "browser" / "sessionRouter" / "chatSessionRoutingProviderService.ts").read_text(encoding="utf-8")
    assert "registerSingleton(IChatSessionRoutingProviderService" in service
    assert "class ChatSessionRoutingProviderService" in service
