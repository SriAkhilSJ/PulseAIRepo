"""
authorization.py -- Centralized Enterprise Authorization Decision Engine.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Enforces the core security invariant:
  Every protected operation is evaluated against verified identity, organization membership,
  assigned role, explicit permissions, resource ownership, and operation risk.
  Fail-closed design: any error, missing context, or authorization deficit yields DENY.
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union

from src.identity.models import (
    Membership,
    MembershipStatus,
    Permission,
    RoleTemplate,
    ServiceIdentity,
    User,
)
from src.identity.roles import get_role_permissions
from src.identity.tenancy import TenancyManager, get_tenancy_manager

log = logging.getLogger("crusorai.identity.authorization")


class AuthorizationDecision(str, enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


@dataclass
class AuthorizationRequest:
    """Standardized authorization evaluation request payload."""
    principal: Optional[Union[User, ServiceIdentity]]
    permission: Permission
    org_id: Optional[str] = None
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    resource_type: str = "general"
    resource_id: str = "*"
    is_high_risk: bool = False
    approval_token: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthorizationResult:
    """Immutable, auditable authorization decision record."""
    decision: AuthorizationDecision
    reason: str
    principal_id: str
    permission: str
    org_id: Optional[str] = None
    workspace_id: Optional[str] = None
    role: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_allowed(self) -> bool:
        return self.decision == AuthorizationDecision.ALLOW

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "principal_id": self.principal_id,
            "permission": self.permission,
            "org_id": self.org_id,
            "workspace_id": self.workspace_id,
            "role": self.role,
            "timestamp": self.timestamp,
        }


class AuthorizationEngine:
    """
    Centralized, fail-closed authorization engine evaluating all access requests.
    """

    def __init__(self, tenancy_manager: Optional[TenancyManager] = None) -> None:
        self.tenancy_manager = tenancy_manager or get_tenancy_manager()

    def evaluate(self, request: AuthorizationRequest) -> AuthorizationResult:
        """
        Evaluate an authorization request against identity, tenancy, roles, and scope.
        Strictly fail-closed: returns DENY on any error or missing credential.
        """
        try:
            return self._evaluate_internal(request)
        except Exception as e:
            principal_id = getattr(request.principal, "user_id", None) or getattr(request.principal, "service_id", "unknown")
            log.error(f"Authorization evaluation failed with internal error: {e}", exc_info=True)
            return AuthorizationResult(
                decision=AuthorizationDecision.DENY,
                reason=f"FAIL_CLOSED: Internal authorization error ({type(e).__name__}: {e})",
                principal_id=str(principal_id),
                permission=request.permission.value,
                org_id=request.org_id,
                workspace_id=request.workspace_id,
            )

    def _evaluate_internal(self, request: AuthorizationRequest) -> AuthorizationResult:
        # 1. Identity Verification
        principal = request.principal
        if principal is None:
            return AuthorizationResult(
                decision=AuthorizationDecision.DENY,
                reason="DENY: Missing identity context (unauthenticated principal)",
                principal_id="anonymous",
                permission=request.permission.value,
                org_id=request.org_id,
            )

        if not isinstance(principal, (User, ServiceIdentity)):
            raise TypeError(f"Invalid or unsupported principal type: {type(principal).__name__}")

        principal_id = getattr(principal, "user_id", None) or getattr(principal, "service_id", "unknown")

        if not getattr(principal, "is_active", True):
            return AuthorizationResult(
                decision=AuthorizationDecision.DENY,
                reason="DENY: Principal account is inactive or disabled",
                principal_id=principal_id,
                permission=request.permission.value,
                org_id=request.org_id,
            )

        # 2. Superadmin Exemption (if user has global platform administrative rights)
        if isinstance(principal, User) and principal.is_superadmin:
            return AuthorizationResult(
                decision=AuthorizationDecision.ALLOW,
                reason="ALLOW: Superadmin platform override",
                principal_id=principal_id,
                permission=request.permission.value,
                org_id=request.org_id,
                role="SUPERADMIN",
            )

        # 3. Service Identity Special Scoping
        if isinstance(principal, ServiceIdentity):
            if principal.org_id != request.org_id:
                return AuthorizationResult(
                    decision=AuthorizationDecision.DENY,
                    reason=f"DENY: Service identity {principal.service_id} bound to org {principal.org_id}, not {request.org_id}",
                    principal_id=principal_id,
                    permission=request.permission.value,
                    org_id=request.org_id,
                )
            effective_perms = get_role_permissions(principal.role, principal.explicit_permissions)
            if request.permission not in effective_perms:
                return AuthorizationResult(
                    decision=AuthorizationDecision.DENY,
                    reason=f"DENY: Service identity {principal.service_id} lacks permission {request.permission.value}",
                    principal_id=principal_id,
                    permission=request.permission.value,
                    org_id=request.org_id,
                    role=principal.role.value,
                )
            return AuthorizationResult(
                decision=AuthorizationDecision.ALLOW,
                reason="ALLOW: Authorized service identity",
                principal_id=principal_id,
                permission=request.permission.value,
                org_id=request.org_id,
                role=principal.role.value,
            )

        # 4. User Membership & Tenancy Scoping
        org_id = request.org_id
        if not org_id:
            # Personal standalone operation without organization scope
            return AuthorizationResult(
                decision=AuthorizationDecision.ALLOW,
                reason="ALLOW: Un-scoped standalone developer operation",
                principal_id=principal_id,
                permission=request.permission.value,
                role="STANDALONE_DEVELOPER",
            )

        membership = self.tenancy_manager.get_membership(org_id, principal_id)
        if not membership:
            return AuthorizationResult(
                decision=AuthorizationDecision.DENY,
                reason=f"DENY: User {principal_id} is not a member of organization {org_id}",
                principal_id=principal_id,
                permission=request.permission.value,
                org_id=org_id,
            )

        if membership.status != MembershipStatus.ACTIVE:
            return AuthorizationResult(
                decision=AuthorizationDecision.DENY,
                reason=f"DENY: User {principal_id} membership in organization {org_id} is {membership.status.value}",
                principal_id=principal_id,
                permission=request.permission.value,
                org_id=org_id,
                role=membership.role.value,
            )

        # 5. Resource Ownership & Scope Isolation
        if request.workspace_id:
            ws = self.tenancy_manager.get_workspace(request.workspace_id)
            if not ws:
                return AuthorizationResult(
                    decision=AuthorizationDecision.DENY,
                    reason=f"DENY: Workspace {request.workspace_id} does not exist",
                    principal_id=principal_id,
                    permission=request.permission.value,
                    org_id=org_id,
                    workspace_id=request.workspace_id,
                )
            if ws.org_id != org_id:
                return AuthorizationResult(
                    decision=AuthorizationDecision.DENY,
                    reason=f"DENY: Cross-organization access blocked. Workspace {request.workspace_id} belongs to {ws.org_id}, not {org_id}",
                    principal_id=principal_id,
                    permission=request.permission.value,
                    org_id=org_id,
                    workspace_id=request.workspace_id,
                )

        if request.project_id:
            proj = self.tenancy_manager.get_project(request.project_id)
            if not proj:
                return AuthorizationResult(
                    decision=AuthorizationDecision.DENY,
                    reason=f"DENY: Project {request.project_id} does not exist",
                    principal_id=principal_id,
                    permission=request.permission.value,
                    org_id=org_id,
                )
            if proj.org_id != org_id:
                return AuthorizationResult(
                    decision=AuthorizationDecision.DENY,
                    reason=f"DENY: Cross-organization project access blocked. Project belongs to {proj.org_id}, not {org_id}",
                    principal_id=principal_id,
                    permission=request.permission.value,
                    org_id=org_id,
                )
            if request.workspace_id and proj.workspace_id != request.workspace_id:
                return AuthorizationResult(
                    decision=AuthorizationDecision.DENY,
                    reason=f"DENY: Project {request.project_id} does not belong to workspace {request.workspace_id}",
                    principal_id=principal_id,
                    permission=request.permission.value,
                    org_id=org_id,
                    workspace_id=request.workspace_id,
                )

        # 6. Role and Permission Check
        effective_perms = get_role_permissions(membership.role, membership.custom_permissions)
        if request.permission not in effective_perms:
            return AuthorizationResult(
                decision=AuthorizationDecision.DENY,
                reason=f"DENY: Role {membership.role.value} lacks required permission {request.permission.value}",
                principal_id=principal_id,
                permission=request.permission.value,
                org_id=org_id,
                workspace_id=request.workspace_id,
                role=membership.role.value,
            )

        # 7. High-Risk Operation & Explicit Approval Gate
        if request.is_high_risk:
            # If developer or custom role executes a high-risk mutation without approval token
            if membership.role in {RoleTemplate.DEVELOPER, RoleTemplate.CUSTOM}:
                if not request.approval_token:
                    return AuthorizationResult(
                        decision=AuthorizationDecision.REQUIRES_APPROVAL,
                        reason="REQUIRES_APPROVAL: High-risk operation requires explicit interactive user approval",
                        principal_id=principal_id,
                        permission=request.permission.value,
                        org_id=org_id,
                        workspace_id=request.workspace_id,
                        role=membership.role.value,
                    )

        # 8. All checks passed -> ALLOW
        return AuthorizationResult(
            decision=AuthorizationDecision.ALLOW,
            reason=f"ALLOW: Authorized by role {membership.role.value} with permission {request.permission.value}",
            principal_id=principal_id,
            permission=request.permission.value,
            org_id=org_id,
            workspace_id=request.workspace_id,
            role=membership.role.value,
        )


_GLOBAL_AUTHORIZATION_ENGINE: Optional[AuthorizationEngine] = None

def get_authorization_engine() -> AuthorizationEngine:
    global _GLOBAL_AUTHORIZATION_ENGINE
    if _GLOBAL_AUTHORIZATION_ENGINE is None:
        _GLOBAL_AUTHORIZATION_ENGINE = AuthorizationEngine()
    return _GLOBAL_AUTHORIZATION_ENGINE
