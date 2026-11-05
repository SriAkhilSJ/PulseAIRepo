"""
protocol.py - Model Context Protocol (MCP) Version Governance & Protocol Compliance.

Phase 9.5: MCP Ecosystem & Browser Agent Security.
Supported specifications:
- 2024-11-05 (Legacy Baseline)
- 2025-11-25 (Intermediate Enhanced Specification)
- 2026-07-28 (Current Modern Specification per https://modelcontextprotocol.io/specification/2026-07-28)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


class MCPProtocolVersion(str, enum.Enum):
    V2024_11_05 = "2024-11-05"
    V2025_11_25 = "2025-11-25"
    V2026_07_28 = "2026-07-28"

    @classmethod
    def default(cls) -> MCPProtocolVersion:
        return cls.V2026_07_28

    @classmethod
    def supported_versions(cls) -> List[str]:
        return [v.value for v in cls]

    @classmethod
    def is_supported(cls, version: str) -> bool:
        return version in cls.supported_versions()


@dataclass(frozen=True)
class MCPProtocolCapabilities:
    version: MCPProtocolVersion
    supports_stateless: bool
    supports_per_request_version: bool
    supports_server_discover: bool
    supports_multi_round_trip: bool
    supports_cache_hints: bool
    supports_header_routing: bool
    supports_oauth21_rfc9207: bool


PROTOCOL_CAPABILITY_MATRIX: Dict[MCPProtocolVersion, MCPProtocolCapabilities] = {
    MCPProtocolVersion.V2024_11_05: MCPProtocolCapabilities(
        version=MCPProtocolVersion.V2024_11_05,
        supports_stateless=False,
        supports_per_request_version=False,
        supports_server_discover=False,
        supports_multi_round_trip=False,
        supports_cache_hints=False,
        supports_header_routing=False,
        supports_oauth21_rfc9207=False,
    ),
    MCPProtocolVersion.V2025_11_25: MCPProtocolCapabilities(
        version=MCPProtocolVersion.V2025_11_25,
        supports_stateless=False,
        supports_per_request_version=True,
        supports_server_discover=True,
        supports_multi_round_trip=False,
        supports_cache_hints=True,
        supports_header_routing=True,
        supports_oauth21_rfc9207=True,
    ),
    MCPProtocolVersion.V2026_07_28: MCPProtocolCapabilities(
        version=MCPProtocolVersion.V2026_07_28,
        supports_stateless=True,
        supports_per_request_version=True,
        supports_server_discover=True,
        supports_multi_round_trip=True,
        supports_cache_hints=True,
        supports_header_routing=True,
        supports_oauth21_rfc9207=True,
    ),
}


@dataclass
class ProtocolNegotiationResult:
    negotiated_version: Optional[MCPProtocolVersion]
    accepted: bool
    error_code: Optional[int] = None
    error_message: Optional[str] = None
    capabilities: Optional[MCPProtocolCapabilities] = None


class MCPProtocolGovernor:
    """
    Evaluates, negotiates and enforces MCP protocol versions.
    Fail-closed: all unsupported or malformed protocol versions return controlled JSON-RPC errors.
    """

    CLIENT_INFO = {
        "name": "crusorai",
        "version": "2.1.0",
        "supported_mcp_versions": MCPProtocolVersion.supported_versions(),
    }

    @classmethod
    def negotiate_version(
        cls, requested_version: Optional[str]
    ) -> ProtocolNegotiationResult:
        if not requested_version:
            # Default to modern 2026-07-28
            ver = MCPProtocolVersion.default()
            return ProtocolNegotiationResult(
                negotiated_version=ver,
                accepted=True,
                capabilities=PROTOCOL_CAPABILITY_MATRIX[ver],
            )

        if not MCPProtocolVersion.is_supported(requested_version):
            return ProtocolNegotiationResult(
                negotiated_version=None,
                accepted=False,
                error_code=-32000,
                error_message=(
                    f"Unsupported MCP protocol version: '{requested_version}'. "
                    f"Supported versions are: {MCPProtocolVersion.supported_versions()}"
                ),
            )

        ver = MCPProtocolVersion(requested_version)
        return ProtocolNegotiationResult(
            negotiated_version=ver,
            accepted=True,
            capabilities=PROTOCOL_CAPABILITY_MATRIX[ver],
        )

    @classmethod
    def validate_request_header_version(
        cls, header_version: Optional[str], session_version: MCPProtocolVersion
    ) -> Tuple[bool, Optional[str]]:
        """Validate per-request protocol version override (supported in 2025+ specs)."""
        if not header_version:
            return True, None
        caps = PROTOCOL_CAPABILITY_MATRIX[session_version]
        if not caps.supports_per_request_version and header_version != session_version.value:
            return False, f"Per-request protocol version override not permitted in {session_version.value}"
        if not MCPProtocolVersion.is_supported(header_version):
            return False, f"Unsupported per-request protocol version: {header_version}"
        return True, None

    @classmethod
    def handle_server_discover(
        cls, version: MCPProtocolVersion
    ) -> Dict[str, Any]:
        """Handle server/discover specification method (2025-11-25 and 2026-07-28)."""
        caps = PROTOCOL_CAPABILITY_MATRIX[version]
        if not caps.supports_server_discover:
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32601,
                    "message": f"Method 'server/discover' not supported under MCP protocol {version.value}",
                },
            }
        return {
            "jsonrpc": "2.0",
            "result": {
                "serverInfo": {
                    "name": "crusorai-mcp-gateway",
                    "version": "2.1.0",
                    "protocolVersion": version.value,
                },
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"subscribe": True},
                    "prompts": {"listChanged": True},
                    "stateless": caps.supports_stateless,
                    "cacheHints": caps.supports_cache_hints,
                },
            },
        }

