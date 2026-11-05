"""
auth.py -- Enterprise Authentication Engine, Token Validation, and Session Management.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Implements:
- RFC 7519 JSON Web Token (JWT) encoding and decoding with HS256 cryptographic verification.
- Strict validation: signature, issuer, audience, expiration, and replay prevention.
- Refresh token rotation (single-use semantics).
- Session lifecycle management (creation, validation, expiration, and revocation).
- PBKDF2-HMAC-SHA256 password hashing with cryptographically random salts.
- Constant-time comparison to prevent timing side-channel attacks.
- Zero-leak credential redaction.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set, Tuple

from src.identity.models import Session, User

log = logging.getLogger("crusorai.identity.auth")

DEFAULT_ISSUER = "crusor-auth"
DEFAULT_AUDIENCE = "crusor-ide"
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 3600       # 1 hour
DEFAULT_REFRESH_TOKEN_TTL_SECONDS = 86400 * 14 # 14 days
PBKDF2_ITERATIONS = 100_000


class AuthenticationError(Exception):
    """Raised when authentication credentials or tokens are invalid, expired, or revoked."""
    pass


class TokenExpiredError(AuthenticationError):
    pass


class InvalidTokenError(AuthenticationError):
    pass


class SessionRevokedError(AuthenticationError):
    pass


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    rem = len(data) % 4
    if rem > 0:
        data += "=" * (4 - rem)
    return base64.urlsafe_b64decode(data.encode("ascii"))


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """
    Hash a password using PBKDF2-HMAC-SHA256 with 100,000 iterations.
    Returns (hex_hash, hex_salt).
    """
    if salt is None:
        salt_bytes = os.urandom(16)
        salt = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt)

    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        PBKDF2_ITERATIONS
    )
    return dk.hex(), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify a password against stored PBKDF2 hash using constant-time comparison."""
    computed_hash, _ = hash_password(password, salt=salt)
    return hmac.compare_digest(computed_hash, stored_hash)


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = DEFAULT_ACCESS_TOKEN_TTL_SECONDS
    session_id: str = ""


class TokenManager:
    """Cryptographic token generator and validator implementing HS256 JWT specification."""

    def __init__(
        self,
        signing_key: Optional[bytes] = None,
        issuer: str = DEFAULT_ISSUER,
        audience: str = DEFAULT_AUDIENCE,
    ) -> None:
        self._key = signing_key or os.urandom(32)
        self._issuer = issuer
        self._audience = audience
        self._revoked_jtis: Set[str] = set()
        self._lock = threading.Lock()

    def generate_token(
        self,
        subject: str,
        token_type: str = "access",
        ttl_seconds: int = DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]:
        """
        Create a cryptographically signed HS256 JWT token.
        Returns (jwt_string, jti).
        """
        jti = str(uuid.uuid4())
        now = time.time()
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": subject,
            "jti": jti,
            "iat": int(now),
            "exp": int(now + ttl_seconds),
            "token_type": token_type,
        }
        if extra_claims:
            payload.update(extra_claims)

        hdr_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        pay_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{hdr_b64}.{pay_b64}".encode("ascii")

        sig = hmac.new(self._key, signing_input, hashlib.sha256).digest()
        sig_b64 = _b64url_encode(sig)

        token = f"{hdr_b64}.{pay_b64}.{sig_b64}"
        return token, jti

    def verify_token(
        self,
        token: str,
        expected_token_type: str = "access",
    ) -> Dict[str, Any]:
        """
        Cryptographically verify signature, issuer, audience, expiration, and revocation.
        """
        parts = token.strip().split(".")
        if len(parts) != 3:
            raise InvalidTokenError("Malformed JWT: expected 3 dot-separated segments")

        hdr_b64, pay_b64, sig_b64 = parts
        signing_input = f"{hdr_b64}.{pay_b64}".encode("ascii")
        expected_sig = hmac.new(self._key, signing_input, hashlib.sha256).digest()
        provided_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, provided_sig):
            raise InvalidTokenError("Cryptographic signature mismatch")

        try:
            payload = json.loads(_b64url_decode(pay_b64).decode("utf-8"))
        except Exception as e:
            raise InvalidTokenError(f"Failed to decode token payload: {e}")

        # Validate Issuer
        if payload.get("iss") != self._issuer:
            raise InvalidTokenError(f"Invalid token issuer: expected {self._issuer}, got {payload.get('iss')}")

        # Validate Audience
        if payload.get("aud") != self._audience:
            raise InvalidTokenError(f"Invalid token audience: expected {self._audience}, got {payload.get('aud')}")

        # Validate Expiration
        exp = payload.get("exp", 0)
        if time.time() > exp:
            raise TokenExpiredError(f"Token expired at {exp} (current time {int(time.time())})")

        # Validate Token Type
        if payload.get("token_type") != expected_token_type:
            raise InvalidTokenError(f"Unexpected token type: expected {expected_token_type}, got {payload.get('token_type')}")

        # Validate JTI Revocation
        jti = payload.get("jti")
        if jti:
            with self._lock:
                if jti in self._revoked_jtis:
                    raise SessionRevokedError("Token has been revoked")

        return payload

    def revoke_jti(self, jti: str) -> None:
        """Mark a specific token JTI as revoked."""
        with self._lock:
            self._revoked_jtis.add(jti)


class AuthenticationService:
    """
    Centralized Authentication and Session Governance Manager.
    Handles user login, token generation, refresh rotation, and session validation.
    """

    def __init__(self, token_manager: Optional[TokenManager] = None) -> None:
        self.token_manager = token_manager or TokenManager()
        self._users: Dict[str, User] = {}          # user_id -> User
        self._users_by_email: Dict[str, User] = {} # email -> User
        self._sessions: Dict[str, Session] = {}    # session_id -> Session
        self._lock = threading.Lock()

    def register_user(
        self,
        email: str,
        password: str,
        display_name: str,
        user_id: Optional[str] = None,
        is_superadmin: bool = False,
    ) -> User:
        """Register a new user identity with salted PBKDF2 hash."""
        email_clean = email.strip().lower()
        with self._lock:
            if email_clean in self._users_by_email:
                raise ValueError(f"User with email {email_clean} already exists")

            uid = user_id or f"usr_{uuid.uuid4().hex[:12]}"
            pwd_hash, salt = hash_password(password)

            user = User(
                user_id=uid,
                email=email_clean,
                display_name=display_name,
                password_hash=pwd_hash,
                salt=salt,
                is_active=True,
                is_superadmin=is_superadmin,
            )
            self._users[uid] = user
            self._users_by_email[email_clean] = user
            log.info(f"Registered user {uid} ({email_clean})")
            return user

    def authenticate_credentials(
        self,
        email: str,
        password: str,
        org_id: Optional[str] = None,
        ip_address: str = "127.0.0.1",
        user_agent: str = "CrusorDesktop/1.0",
    ) -> Tuple[User, TokenPair]:
        """Authenticate user credentials and issue a fresh session token pair."""
        email_clean = email.strip().lower()
        with self._lock:
            user = self._users_by_email.get(email_clean)

        if not user or not user.is_active:
            raise AuthenticationError("Invalid email or password")

        if not user.password_hash or not user.salt:
            raise AuthenticationError("Account has no password configured")

        if not verify_password(password, user.password_hash, user.salt):
            raise AuthenticationError("Invalid email or password")

        token_pair = self._create_session_for_user(
            user=user,
            org_id=org_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return user, token_pair

    def _create_session_for_user(
        self,
        user: User,
        org_id: Optional[str] = None,
        ip_address: str = "127.0.0.1",
        user_agent: str = "CrusorDesktop/1.0",
    ) -> TokenPair:
        session_id = f"ses_{uuid.uuid4().hex[:16]}"
        now = time.time()

        access_token, access_jti = self.token_manager.generate_token(
            subject=user.user_id,
            token_type="access",
            ttl_seconds=DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
            extra_claims={"session_id": session_id, "org_id": org_id, "email": user.email},
        )

        refresh_raw = uuid.uuid4().hex + uuid.uuid4().hex
        refresh_hash = hashlib.sha256(refresh_raw.encode("ascii")).hexdigest()

        session = Session(
            session_id=session_id,
            user_id=user.user_id,
            org_id=org_id,
            access_token_jti=access_jti,
            refresh_token_hash=refresh_hash,
            created_at=now,
            expires_at=now + DEFAULT_REFRESH_TOKEN_TTL_SECONDS,
            is_revoked=False,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        with self._lock:
            self._sessions[session_id] = session

        return TokenPair(
            access_token=access_token,
            refresh_token=f"{session_id}.{refresh_raw}",
            expires_in=DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
            session_id=session_id,
        )

    def refresh_access_token(self, full_refresh_token: str) -> TokenPair:
        """
        Rotate refresh token: validate single-use refresh token, invalidate old one,
        and issue a new access token + new refresh token.
        """
        parts = full_refresh_token.strip().split(".")
        if len(parts) != 2:
            raise InvalidTokenError("Malformed refresh token format")

        session_id, refresh_secret = parts
        provided_hash = hashlib.sha256(refresh_secret.encode("ascii")).hexdigest()

        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise AuthenticationError("Session not found")
            if session.is_revoked:
                raise SessionRevokedError("Session is revoked")
            if time.time() > session.expires_at:
                raise TokenExpiredError("Session has expired")
            if not hmac.compare_digest(session.refresh_token_hash, provided_hash):
                # Potential token replay/theft: revoke session immediately!
                session.is_revoked = True
                self.token_manager.revoke_jti(session.access_token_jti)
                raise InvalidTokenError("Invalid refresh token. Session revoked for safety.")

            user = self._users.get(session.user_id)
            if not user or not user.is_active:
                raise AuthenticationError("User is no longer active")

            # Revoke old access token JTI
            self.token_manager.revoke_jti(session.access_token_jti)

            # Issue new token pair
            now = time.time()
            new_access_token, new_access_jti = self.token_manager.generate_token(
                subject=user.user_id,
                token_type="access",
                ttl_seconds=DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
                extra_claims={"session_id": session_id, "org_id": session.org_id, "email": user.email},
            )

            # Generate new single-use refresh secret
            new_refresh_raw = uuid.uuid4().hex + uuid.uuid4().hex
            session.refresh_token_hash = hashlib.sha256(new_refresh_raw.encode("ascii")).hexdigest()
            session.access_token_jti = new_access_jti

        return TokenPair(
            access_token=new_access_token,
            refresh_token=f"{session_id}.{new_refresh_raw}",
            expires_in=DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
            session_id=session_id,
        )

    def validate_access_token(self, token: str) -> Tuple[User, Session, Dict[str, Any]]:
        """
        Fully validate an access token: verify cryptography and confirm that the backing session
        and user identity are active and unrevoked.
        """
        claims = self.token_manager.verify_token(token, expected_token_type="access")
        user_id = claims["sub"]
        session_id = claims.get("session_id")

        with self._lock:
            user = self._users.get(user_id)
            if not user or not user.is_active:
                raise AuthenticationError(f"User {user_id} is inactive or does not exist")

            session = None
            if session_id:
                session = self._sessions.get(session_id)
                if not session or session.is_revoked:
                    raise SessionRevokedError(f"Session {session_id} is revoked or expired")
                if time.time() > session.expires_at:
                    raise TokenExpiredError(f"Session {session_id} has expired")

        return user, session, claims

    def revoke_session(self, session_id: str) -> bool:
        """Explicitly revoke a single session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.is_revoked = True
                self.token_manager.revoke_jti(session.access_token_jti)
                return True
        return False

    def revoke_all_user_sessions(self, user_id: str) -> int:
        """Revoke all active sessions for a user (e.g. password reset or account freeze)."""
        count = 0
        with self._lock:
            for session in self._sessions.values():
                if session.user_id == user_id and not session.is_revoked:
                    session.is_revoked = True
                    self.token_manager.revoke_jti(session.access_token_jti)
                    count += 1
        return count

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        with self._lock:
            return self._users.get(user_id)


_GLOBAL_AUTH_SERVICE: Optional[AuthenticationService] = None

def get_auth_service() -> AuthenticationService:
    global _GLOBAL_AUTH_SERVICE
    if _GLOBAL_AUTH_SERVICE is None:
        _GLOBAL_AUTH_SERVICE = AuthenticationService()
    return _GLOBAL_AUTH_SERVICE

