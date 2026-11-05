"""
remote_security.py - Remote MCP Server Security, SSRF & DNS Rebinding Protection.

Phase 9.5: MCP Ecosystem & Browser Agent Security.
Strict destination validation for outbound remote MCP connections (Streamable HTTP, SSE, WebSocket).
Enforces HTTPS, IP resolution checks, DNS rebinding defenses, redirect revalidation, and port allowlists.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# Cloud metadata hosts and link-local endpoints
CLOUD_METADATA_HOSTS = frozenset({
    "169.254.169.254",
    "169.254.170.2",
    "metadata.google.internal",
    "metadata",
    "100.100.100.200",
    "instance-data",
})

# Dangerous administrative / protocol ports
BLOCKED_PORTS = frozenset({
    21,    # FTP
    22,    # SSH
    23,    # Telnet
    25,    # SMTP
    110,   # POP3
    143,   # IMAP
    389,   # LDAP
    636,   # LDAPS
    2375,  # Docker unencrypted
    2376,  # Docker TLS
    3306,  # MySQL
    3389,  # RDP
    5432,  # PostgreSQL
    6379,  # Redis
    6443,  # Kubernetes API
    8080,  # Alternate HTTP (flagged unless explicitly allowlisted)
    9200,  # Elasticsearch
    11211, # Memcached
    27017, # MongoDB
})


@dataclass(frozen=True)
class EndpointValidationResult:
    allowed: bool
    url: str
    resolved_ip: Optional[str] = None
    reason: Optional[str] = None
    is_https: bool = False
    is_private_ip: bool = False
    is_loopback: bool = False
    is_metadata: bool = False


class RemoteMCPSecurityPolicy:
    """
    Enforces outbound endpoint security, preventing SSRF, DNS rebinding, and credential leakages.
    """

    def __init__(
        self,
        enforce_https: bool = True,
        allow_private_networks: bool = False,
        allow_loopback: bool = False,
        trusted_hosts_allowlist: Optional[Set[str]] = None,
        max_redirects: int = 3,
        request_size_limit_bytes: int = 10 * 1024 * 1024,   # 10 MB
        response_size_limit_bytes: int = 25 * 1024 * 1024,  # 25 MB
    ) -> None:
        self.enforce_https = enforce_https
        self.allow_private_networks = allow_private_networks
        self.allow_loopback = allow_loopback
        self.trusted_hosts_allowlist = trusted_hosts_allowlist or set()
        self.max_redirects = max_redirects
        self.request_size_limit_bytes = request_size_limit_bytes
        self.response_size_limit_bytes = response_size_limit_bytes

    def parse_and_normalize_url(self, raw_url: str) -> Tuple[Optional[urllib.parse.ParseResult], Optional[str]]:
        """Normalize URL, strip credentials/userinfo tricks, and validate scheme."""
        if not raw_url or not isinstance(raw_url, str):
            return None, "Invalid or empty URL."

        url_str = raw_url.strip()

        # Check for userinfo tricks (e.g. http://trusted.com:pwd@127.0.0.1/)
        try:
            parsed = urllib.parse.urlparse(url_str)
        except Exception as exc:
            return None, f"Malformed URL syntax: {exc}"

        if not parsed.scheme or not parsed.netloc:
            return None, "URL must include an explicit scheme and hostname."

        scheme = parsed.scheme.lower()
        if self.enforce_https and scheme not in ("https", "wss"):
            return None, f"Non-HTTPS scheme '{scheme}' prohibited by remote security policy (HTTPS required)."

        if scheme not in ("http", "https", "ws", "wss"):
            return None, f"Unsupported scheme: {scheme}"

        if parsed.username or parsed.password:
            return None, "Embedded credentials / userinfo tricks in URL are strictly prohibited."

        return parsed, None

    def validate_ip_address(self, ip_str: str) -> Tuple[bool, Optional[str], bool, bool, bool]:
        """
        Validate resolved IP address against loopback, private ranges, link-local, and cloud metadata.
        Returns (is_safe, error_message, is_loopback, is_private, is_metadata).
        """
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Invalid IP address representation: {ip_str}", False, False, False

        is_loopback = ip_obj.is_loopback
        is_private = ip_obj.is_private
        is_link_local = ip_obj.is_link_local

        # Cloud metadata check
        if str(ip_obj) in CLOUD_METADATA_HOSTS:
            return False, f"Access to cloud metadata IP {ip_obj} is strictly prohibited.", is_loopback, is_private, True

        # Loopback check
        if is_loopback and not self.allow_loopback:
            return False, f"Access to loopback address {ip_obj} is prohibited by SSRF policy.", is_loopback, is_private, False

        # Private RFC1918 / RFC4193 check
        if is_private and not self.allow_private_networks:
            return False, f"Access to private internal network IP {ip_obj} is prohibited by SSRF policy.", is_loopback, is_private, False

        # Link-local check (169.254.0.0/16 or fe80::/10)
        if is_link_local:
            return False, f"Access to link-local IP {ip_obj} is prohibited.", is_loopback, is_private, False

        return True, None, is_loopback, is_private, False

    def validate_endpoint(self, raw_url: str) -> EndpointValidationResult:
        """
        Full SSRF and security check for an outbound remote MCP endpoint:
        1. Parse and sanitize URL (reject userinfo).
        2. Verify scheme (HTTPS default).
        3. Check port allowlist.
        4. Resolve hostname via DNS.
        5. Verify every resolved IP address against SSRF boundaries.
        6. Return pinned IP for DNS rebinding protection.
        """
        parsed, parse_err = self.parse_and_normalize_url(raw_url)
        if parse_err or not parsed:
            return EndpointValidationResult(allowed=False, url=raw_url, reason=parse_err)

        hostname = parsed.hostname.lower() if parsed.hostname else ""
        if not hostname:
            return EndpointValidationResult(allowed=False, url=raw_url, reason="Missing hostname.")

        # Check metadata hostnames
        if hostname in CLOUD_METADATA_HOSTS:
            return EndpointValidationResult(
                allowed=False,
                url=raw_url,
                reason=f"Hostname '{hostname}' matches cloud metadata service.",
                is_metadata=True,
            )

        # Check port
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme in ("https", "wss") else 80

        if port in BLOCKED_PORTS and hostname not in self.trusted_hosts_allowlist:
            return EndpointValidationResult(
                allowed=False,
                url=raw_url,
                reason=f"Port {port} is restricted by outbound security policy.",
            )

        # Resolve hostname and inspect all returned IPs (DNS Rebinding & SSRF defense)
        try:
            # Check if hostname is already a numeric IP (handles hex, octal, dword)
            try:
                ip_val = ipaddress.ip_address(hostname)
                ips = [str(ip_val)]
            except ValueError:
                # DNS query to resolve all addresses
                addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
                ips = list({item[4][0] for item in addr_info})
        except socket.gaierror as exc:
            return EndpointValidationResult(
                allowed=False,
                url=raw_url,
                reason=f"DNS resolution failure for host '{hostname}': {exc}",
            )

        if not ips:
            return EndpointValidationResult(allowed=False, url=raw_url, reason=f"Host '{hostname}' resolved to 0 IPs.")

        # Every single resolved IP must pass SSRF validation
        primary_ip = ips[0]
        for ip in ips:
            safe, err_msg, is_lb, is_priv, is_meta = self.validate_ip_address(ip)
            if not safe:
                return EndpointValidationResult(
                    allowed=False,
                    url=raw_url,
                    resolved_ip=ip,
                    reason=err_msg,
                    is_loopback=is_lb,
                    is_private_ip=is_priv,
                    is_metadata=is_meta,
                    is_https=parsed.scheme in ("https", "wss"),
                )

        return EndpointValidationResult(
            allowed=True,
            url=raw_url,
            resolved_ip=primary_ip,
            is_https=parsed.scheme in ("https", "wss"),
        )

    def validate_redirect(self, original_url: str, redirect_target: str, hop_index: int) -> EndpointValidationResult:
        """
        Validate HTTP redirect hop:
        - Prevents redirect chaining beyond max_redirects.
        - Revalidates scheme, hostname, and resolved destination IP.
        - Prevents redirect from external HTTPS server to internal/private/localhost resources.
        """
        if hop_index >= self.max_redirects:
            return EndpointValidationResult(
                allowed=False,
                url=redirect_target,
                reason=f"Maximum redirect limit ({self.max_redirects}) exceeded.",
            )

        # Resolve relative redirects against original URL
        resolved_target = urllib.parse.urljoin(original_url, redirect_target)
        return self.validate_endpoint(resolved_target)

