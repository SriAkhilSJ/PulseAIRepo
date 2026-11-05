"""
browser_security.py - Browser Agent Process Isolation, Session Sandboxing & Navigation SSRF Protection.

Phase 9.5: MCP Ecosystem & Browser Agent Security.
Enforces:
1. Isolated, ephemeral browser contexts per session (no inherited cookies, passwords, storage, extensions).
2. Navigation and redirect SSRF protection blocking localhost, private subnets, cloud metadata, and userinfo tricks.
3. Fail-closed Chromium sandbox enforcement.
4. Sensitive action confirmation (posts, messages, form submissions, purchases).
"""

from __future__ import annotations

import enum
import ipaddress
import re
import socket
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.security.mcp.remote_security import (
    BLOCKED_PORTS,
    CLOUD_METADATA_HOSTS,
    EndpointValidationResult,
    RemoteMCPSecurityPolicy,
)


class BrowserActionType(str, enum.Enum):
    NAVIGATE = "NAVIGATE"
    SNAPSHOT = "SNAPSHOT"
    CLICK = "CLICK"
    TYPE_INPUT = "TYPE_INPUT"
    SUBMIT_FORM = "SUBMIT_FORM"
    EXTERNAL_POST = "EXTERNAL_POST"
    DOWNLOAD = "DOWNLOAD"
    UPLOAD = "UPLOAD"
    EVALUATE_SCRIPT = "EVALUATE_SCRIPT"


@dataclass(frozen=True)
class BrowserSessionConfig:
    session_id: str
    user_data_dir: Path
    headless: bool = True
    enable_chromium_sandbox: bool = True
    block_private_networks: bool = True
    block_loopback: bool = True
    allowed_domains: Optional[Set[str]] = None


class BrowserSecurityController:
    """
    Central controller enforcing browser process isolation, SSRF navigation guards,
    and sensitive action policies.
    """

    def __init__(self, base_session_root: Optional[Path] = None) -> None:
        self.base_session_root = base_session_root or (Path("bench-results") / "phase95_mcp_browser_security" / "browser_sessions")
        self.base_session_root.mkdir(parents=True, exist_ok=True)
        self.remote_policy = RemoteMCPSecurityPolicy(
            enforce_https=False,  # Browser may navigate to plain HTTP for standard websites
            allow_private_networks=False,
            allow_loopback=False,
        )

    def create_isolated_session_config(
        self,
        session_id: str,
        headless: bool = True,
        allow_loopback_for_local_testing: bool = False,
    ) -> BrowserSessionConfig:
        """Create configuration for a clean, ephemeral browser context."""
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id)[:32]
        session_dir = self.base_session_root / f"session_{safe_id}"
        session_dir.mkdir(parents=True, exist_ok=True)

        return BrowserSessionConfig(
            session_id=session_id,
            user_data_dir=session_dir,
            headless=headless,
            enable_chromium_sandbox=True,
            block_private_networks=True,
            block_loopback=not allow_loopback_for_local_testing,
        )

    def validate_navigation_target(
        self,
        target_url: str,
        allow_loopback: bool = False,
    ) -> EndpointValidationResult:
        """
        Comprehensive SSRF and destination check for browser navigation:
        - Blocks localhost, 127.0.0.0/8, ::1 (unless explicit test flag enabled)
        - Blocks private RFC1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
        - Blocks private RFC4193 (fc00::/7) and link-local (fe80::/10, 169.254.0.0/16)
        - Blocks cloud metadata (169.254.169.254, metadata.google.internal)
        - Blocks non-standard dangerous ports
        - Blocks userinfo credentials in URLs
        """
        policy = RemoteMCPSecurityPolicy(
            enforce_https=False,
            allow_private_networks=False,
            allow_loopback=allow_loopback,
        )
        return policy.validate_endpoint(target_url)

    @classmethod
    def is_sensitive_action(
        cls,
        action: BrowserActionType,
        target_element_tag: str = "",
        input_value: str = "",
    ) -> Tuple[bool, str]:
        """
        Determine if a browser operation constitutes a sensitive external action
        requiring explicit user confirmation.
        """
        if action in (BrowserActionType.SUBMIT_FORM, BrowserActionType.EXTERNAL_POST):
            return True, "Submitting form or publishing content to an external service."

        if action == BrowserActionType.UPLOAD:
            return True, "Uploading local workspace files to an external web application."

        if action == BrowserActionType.TYPE_INPUT:
            # Check for payment or password fields
            elem_lower = target_element_tag.lower()
            if any(term in elem_lower for term in ("password", "passwd", "credit", "card", "cvv", "ssn", "token", "secret")):
                return True, f"Entering sensitive data into element '{target_element_tag}'."

        if action == BrowserActionType.EVALUATE_SCRIPT:
            return True, "Executing custom JavaScript inside the host webpage context."

        return False, "Standard navigation or inspection."

