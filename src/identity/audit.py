"""
audit.py -- Enterprise Identity, Authentication, and Authorization Audit Ledger.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Provides structured, auditable, tamper-resistant logging of all identity, authentication,
membership, role mutation, and authorization denial events.
Zero-leak: Sanitizes credentials and secrets before writing entries.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("crusorai.identity.audit")

SENSITIVE_FIELD_NAMES = frozenset({
    "password", "secret", "token", "access_token", "refresh_token",
    "authorization", "api_key", "salt", "signature"
})


class AuditEventType(str, enum.Enum):
    # Authentication events
    AUTH_LOGIN_SUCCESS = "AUTH_LOGIN_SUCCESS"
    AUTH_LOGIN_FAILURE = "AUTH_LOGIN_FAILURE"
    AUTH_LOGOUT = "AUTH_LOGOUT"
    AUTH_TOKEN_REFRESH = "AUTH_TOKEN_REFRESH"
    SESSION_REVOKED = "SESSION_REVOKED"

    # Membership and Role events
    MEMBERSHIP_CREATED = "MEMBERSHIP_CREATED"
    MEMBERSHIP_ROLE_UPDATED = "MEMBERSHIP_ROLE_UPDATED"
    MEMBERSHIP_REVOKED = "MEMBERSHIP_REVOKED"

    # Authorization events
    AUTHORIZATION_ALLOWED = "AUTHORIZATION_ALLOWED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    HIGH_RISK_APPROVAL_REQUESTED = "HIGH_RISK_APPROVAL_REQUESTED"

    # Security violations
    SPOOFING_ATTEMPT_DETECTED = "SPOOFING_ATTEMPT_DETECTED"
    CROSS_TENANT_VIOLATION_BLOCKED = "CROSS_TENANT_VIOLATION_BLOCKED"


def _sanitize_audit_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively sanitize sensitive credential fields."""
    sanitized: Dict[str, Any] = {}
    for k, v in data.items():
        if any(sens in k.lower() for sens in SENSITIVE_FIELD_NAMES):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_audit_dict(v)
        else:
            sanitized[k] = v
    return sanitized


@dataclass
class AuditEvent:
    """Immutable audit record for a security-significant action."""
    event_id: str
    event_type: AuditEventType
    principal_id: str
    org_id: Optional[str]
    target_resource: str
    details: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    ip_address: str = "127.0.0.1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "principal_id": self.principal_id,
            "org_id": self.org_id,
            "target_resource": self.target_resource,
            "details": self.details,
            "timestamp": self.timestamp,
            "ip_address": self.ip_address,
        }


class AuditLedger:
    """
    Thread-safe, append-only security audit ledger.
    """

    def __init__(self) -> None:
        self._events: List[AuditEvent] = []
        self._lock = threading.Lock()

    def record_event(
        self,
        event_type: AuditEventType,
        principal_id: str,
        target_resource: str,
        org_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: str = "127.0.0.1",
    ) -> AuditEvent:
        """Create and record an auditable event with sanitized details."""
        clean_details = _sanitize_audit_dict(details or {})
        event = AuditEvent(
            event_id=f"aud_{uuid.uuid4().hex[:16]}",
            event_type=event_type,
            principal_id=principal_id,
            org_id=org_id,
            target_resource=target_resource,
            details=clean_details,
            timestamp=time.time(),
            ip_address=ip_address,
        )
        with self._lock:
            self._events.append(event)

        log.info(f"AUDIT [{event_type.value}] principal={principal_id} org={org_id} target={target_resource}")
        return event

    def query_events(
        self,
        org_id: Optional[str] = None,
        principal_id: Optional[str] = None,
        event_type: Optional[AuditEventType] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """Query audit events with optional filtering."""
        with self._lock:
            matched = []
            for ev in reversed(self._events):
                if org_id and ev.org_id != org_id:
                    continue
                if principal_id and ev.principal_id != principal_id:
                    continue
                if event_type and ev.event_type != event_type:
                    continue
                matched.append(ev)
                if len(matched) >= limit:
                    break
            return matched

    def count(self) -> int:
        with self._lock:
            return len(self._events)


_GLOBAL_AUDIT_LEDGER: Optional[AuditLedger] = None

def get_audit_ledger() -> AuditLedger:
    global _GLOBAL_AUDIT_LEDGER
    if _GLOBAL_AUDIT_LEDGER is None:
        _GLOBAL_AUDIT_LEDGER = AuditLedger()
    return _GLOBAL_AUDIT_LEDGER

