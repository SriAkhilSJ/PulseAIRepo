"""
src/identity -- Enterprise Identity, Authentication & Role-Based Access Control Subsystem.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Exports all canonical entities, authorization engines, roles, permissions,
and security authorizers.
"""

from src.identity.models import (
    IdentityProviderType,
    Membership,
    MembershipStatus,
    Organization,
    Permission,
    Project,
    RoleTemplate,
    ServiceIdentity,
    Session,
    Team,
    User,
)
from src.identity.roles import (
    ADMIN_PERMISSIONS,
    DEVELOPER_PERMISSIONS,
    OWNER_PERMISSIONS,
    ROLE_PERMISSION_TEMPLATES,
    VIEWER_PERMISSIONS,
    can_assign_role,
    can_modify_membership,
    get_role_permissions,
)
from src.identity.auth import (
    AuthenticationError,
    AuthenticationService,
    InvalidTokenError,
    SessionRevokedError,
    TokenExpiredError,
    TokenManager,
    TokenPair,
    get_auth_service,
    hash_password,
    verify_password,
)
from src.identity.tenancy import (
    OrganizationNotFoundError,
    TenancyError,
    TenancyManager,
    UnauthorizedRoleAssignmentError,
    get_tenancy_manager,
)
from src.identity.authorization import (
    AuthorizationDecision,
    AuthorizationEngine,
    AuthorizationRequest,
    AuthorizationResult,
    get_authorization_engine,
)
from src.identity.resource_guard import (
    IdentitySpoofingError,
    ResourceAccessDeniedError,
    ResourceGuard,
    get_resource_guard,
)
from src.identity.tool_authorizer import (
    IdentityAwareToolAuthorizer,
    ToolAuthorizationError,
    get_tool_authorizer,
)
from src.identity.finops_integration import (
    CrossTenantFinancialViolationError,
    FinOpsAccessDeniedError,
    IdentityAwareFinOpsGovernor,
    get_finops_governor,
)
from src.identity.audit import (
    AuditEvent,
    AuditEventType,
    AuditLedger,
    get_audit_ledger,
)

__all__ = [
    # Models
    "User",
    "Organization",
    "Team",
    "Workspace",
    "Project",
    "Membership",
    "MembershipStatus",
    "RoleTemplate",
    "Permission",
    "Session",
    "ServiceIdentity",
    "IdentityProviderType",

    # Roles & Permissions
    "OWNER_PERMISSIONS",
    "ADMIN_PERMISSIONS",
    "DEVELOPER_PERMISSIONS",
    "VIEWER_PERMISSIONS",
    "ROLE_PERMISSION_TEMPLATES",
    "get_role_permissions",
    "can_assign_role",
    "can_modify_membership",

    # Authentication
    "AuthenticationError",
    "TokenExpiredError",
    "InvalidTokenError",
    "SessionRevokedError",
    "TokenPair",
    "TokenManager",
    "AuthenticationService",
    "get_auth_service",
    "hash_password",
    "verify_password",

    # Tenancy
    "TenancyError",
    "OrganizationNotFoundError",
    "UnauthorizedRoleAssignmentError",
    "TenancyManager",
    "get_tenancy_manager",

    # Authorization
    "AuthorizationDecision",
    "AuthorizationRequest",
    "AuthorizationResult",
    "AuthorizationEngine",
    "get_authorization_engine",

    # Resource Guard
    "ResourceAccessDeniedError",
    "IdentitySpoofingError",
    "ResourceGuard",
    "get_resource_guard",

    # Tool Authorizer
    "ToolAuthorizationError",
    "IdentityAwareToolAuthorizer",
    "get_tool_authorizer",

    # FinOps Integration
    "FinOpsAccessDeniedError",
    "CrossTenantFinancialViolationError",
    "IdentityAwareFinOpsGovernor",
    "get_finops_governor",

    # Audit Ledger
    "AuditEventType",
    "AuditEvent",
    "AuditLedger",
    "get_audit_ledger",
]

