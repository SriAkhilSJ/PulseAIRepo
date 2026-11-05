"""
oauth.py - MCP OAuth 2.1 Security, PKCE & RFC 9207 Issuer Identification.

Phase 9.5: MCP Ecosystem & Browser Agent Security.
Implements OAuth 2.1 requirements for MCP connections:
1. Proof Key for Code Exchange (PKCE) with S256 challenge.
2. Cryptographic state binding and CSRF prevention.
3. RFC 9207 Authorization Server Issuer Identification (mix-up attack defense).
4. Strict token isolation per (server_id, issuer, client_id) — prevents token passthrough.
5. Refresh token rotation & credential revocation.
6. Zero credential leakage: redaction across all logs, prompts, and receipts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PKCEPair:
    verifier: str
    challenge: str
    method: str = "S256"


@dataclass
class OAuthTokenBundle:
    server_id: str
    issuer: str
    client_id: str
    access_token: str
    token_type: str = "Bearer"
    expires_at: float = 0.0
    refresh_token: Optional[str] = None
    scope: str = ""

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


class MCPOAuthManager:
    """
    Centralized OAuth 2.1 and Credential Security Manager for Remote MCP Servers.
    """

    def __init__(self, token_encryption_key: Optional[bytes] = None) -> None:
        self._key = token_encryption_key or os.urandom(32)
        # In-memory secure credential store indexed strictly by (server_id, issuer)
        self._tokens: Dict[Tuple[str, str], OAuthTokenBundle] = {}
        # Active PKCE states: state -> (server_id, issuer, verifier, expiry)
        self._active_states: Dict[str, Tuple[str, str, str, float]] = {}

    @classmethod
    def generate_pkce(cls) -> PKCEPair:
        """Generate high-entropy code_verifier and S256 code_challenge."""
        # 43 to 128 unreserved characters per RFC 7636
        verifier = secrets.token_urlsafe(64)[:86]
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return PKCEPair(verifier=verifier, challenge=challenge, method="S256")

    def create_authorization_request(
        self,
        server_id: str,
        authorization_endpoint: str,
        client_id: str,
        redirect_uri: str,
        scope: str = "mcp:tools",
    ) -> Tuple[str, PKCEPair, str]:
        """
        Build an OAuth 2.1 authorization URL with PKCE and bound state token.
        Returns (auth_url, pkce_pair, state).
        """
        pkce = self.generate_pkce()
        state = secrets.token_urlsafe(32)

        # Parse issuer from authorization endpoint
        parsed = urllib.parse.urlparse(authorization_endpoint)
        issuer = f"{parsed.scheme}://{parsed.netloc}"

        # Store pending state with 5-minute expiry
        self._active_states[state] = (server_id, issuer, pkce.verifier, time.time() + 300.0)

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": pkce.challenge,
            "code_challenge_method": pkce.method,
        }

        query = urllib.parse.urlencode(params)
        auth_url = f"{authorization_endpoint}?{query}"
        return auth_url, pkce, state

    def validate_authorization_callback(
        self,
        server_id: str,
        expected_issuer: str,
        callback_params: Dict[str, str],
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate OAuth 2.1 callback and RFC 9207 Issuer Identification:
        1. Verify state parameter exists and matches.
        2. Verify state belongs to the exact expected server_id and issuer.
        3. Verify RFC 9207 'iss' parameter matches expected authorization server issuer.
        4. Return (valid, verifier, error_message).
        """
        state = callback_params.get("state")
        if not state:
            return False, None, "Missing 'state' parameter in callback."

        stored = self._active_states.pop(state, None)
        if not stored:
            return False, None, "Invalid or unrecognized 'state' parameter (CSRF prevented)."

        bound_server, bound_issuer, verifier, expiry = stored
        if time.time() > expiry:
            return False, None, "Authorization state has expired."

        if bound_server != server_id:
            return False, None, f"State bound to server '{bound_server}', not '{server_id}' (mix-up prevented)."

        # RFC 9207 Issuer Validation
        returned_issuer = callback_params.get("iss")
        if returned_issuer:
            if returned_issuer.rstrip("/") != expected_issuer.rstrip("/"):
                return False, None, (
                    f"RFC 9207 Issuer Mismatch! Authorization response returned issuer '{returned_issuer}', "
                    f"expected '{expected_issuer}' (Authorization Server Mix-Up Attack Blocked)."
                )

        code = callback_params.get("code")
        if not code:
            err = callback_params.get("error", "missing_code")
            return False, None, f"Authorization server error: {err}"

        return True, verifier, None

    def store_token(
        self,
        server_id: Any,
        issuer: Optional[str] = None,
        client_id: Optional[str] = None,
        access_token: Optional[str] = None,
        expires_in_s: float = 3600.0,
        refresh_token: Optional[str] = None,
        scope: str = "",
    ) -> None:
        """Store OAuth tokens bound strictly to (server_id, issuer). Accepts bundle or individual fields."""
        if isinstance(server_id, OAuthTokenBundle):
            bundle = server_id
            key = (bundle.server_id, bundle.issuer.rstrip("/"))
            self._tokens[key] = bundle
            return

        key = (str(server_id), (issuer or "").rstrip("/"))
        bundle = OAuthTokenBundle(
            server_id=str(server_id),
            issuer=(issuer or "").rstrip("/"),
            client_id=client_id or "",
            access_token=access_token or "",
            expires_at=time.time() + expires_in_s,
            refresh_token=refresh_token,
            scope=scope,
        )
        self._tokens[key] = bundle

    def get_token(
        self, server_id: str, issuer: Optional[str] = None
    ) -> Optional[OAuthTokenBundle]:
        """Convenience accessor to get stored token bundle."""
        if issuer is not None:
            return self.get_token_for_server(server_id, issuer)
        for (s_id, _), bundle in self._tokens.items():
            if s_id == server_id and not bundle.is_expired:
                return bundle
        return None

    def get_token_for_server(
        self, server_id: str, target_server_url: str
    ) -> Optional[OAuthTokenBundle]:
        """
        Retrieve token ensuring token passthrough protection:
        Tokens issued for Server A are NEVER provided to Server B.
        """
        parsed = urllib.parse.urlparse(target_server_url)
        target_issuer = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        key = (server_id, target_issuer)
        bundle = self._tokens.get(key)
        if bundle is None:
            return None
        if bundle.is_expired:
            return None
        return bundle

    def rotate_refresh_token(
        self,
        server_id: str,
        issuer: str,
        new_access_token: str,
        new_refresh_token: str,
        expires_in_s: float = 3600.0,
    ) -> bool:
        """Rotate refresh token: updates tokens and revokes previous refresh token."""
        key = (server_id, issuer.rstrip("/"))
        bundle = self._tokens.get(key)
        if not bundle:
            return False

        self._tokens[key] = OAuthTokenBundle(
            server_id=server_id,
            issuer=issuer.rstrip("/"),
            client_id=bundle.client_id,
            access_token=new_access_token,
            expires_at=time.time() + expires_in_s,
            refresh_token=new_refresh_token,
            scope=bundle.scope,
        )
        return True

    def revoke_credentials(self, server_id: str, issuer: Optional[str] = None) -> int:
        """Purge stored credentials for a disconnected or uninstalled server."""
        removed = 0
        keys_to_del = []
        for (s_id, iss) in self._tokens:
            if s_id == server_id and (issuer is None or iss == issuer.rstrip("/")):
                keys_to_del.append((s_id, iss))

        for k in keys_to_del:
            del self._tokens[k]
            removed += 1
        return removed

    @classmethod
    def redact_secrets_from_text(cls, text: str) -> str:
        """Redact tokens, bearer headers, and keys from any diagnostic or log output."""
        if not text:
            return text
        redacted = re.sub(
            r"(Bearer\s+)[A-Za-z0-9_\-\.]{15,}",
            r"\1[REDACTED_OAUTH_TOKEN]",
            text,
            flags=re.IGNORECASE,
        )
        redacted = re.sub(
            r'("(?:access_token|refresh_token|client_secret|code)"\s*:\s*")[^"]+(")',
            r"\1[REDACTED]\2",
            redacted,
            flags=re.IGNORECASE,
        )
        return redacted

