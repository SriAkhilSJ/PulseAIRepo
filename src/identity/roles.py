"""
roles.py -- Role Definitions, Permission Templates, and Role Hierarchy.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Provides deterministic mappings between Role Templates and granular Permissions,
enforcing least-privilege defaults and strict administrative assignment guards.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Set

from src.identity.models import Permission, RoleTemplate

# 1. OWNER: Full authority across organization, billing, membership, and runtime
OWNER_PERMISSIONS: FrozenSet[Permission] = frozenset(Permission)

# 2. ADMIN: Full authority except organization deletion and direct owner displacement
ADMIN_PERMISSIONS: FrozenSet[Permission] = frozenset({
    # Organization Management (except ORG_DELETE)
    Permission.ORG_READ,
    Permission.ORG_UPDATE,
    Permission.ORG_MANAGE_MEMBERS,
    Permission.ORG_MANAGE_ROLES,
    Permission.ORG_MANAGE_BILLING,

    # Workspace & Project Operations
    Permission.WORKSPACE_READ,
    Permission.WORKSPACE_WRITE,
    Permission.WORKSPACE_DELETE,
    Permission.WORKSPACE_MANAGE_ACCESS,
    Permission.PROJECT_READ,
    Permission.PROJECT_WRITE,
    Permission.PROJECT_DELETE,

    # Filesystem Operations
    Permission.FILE_READ,
    Permission.FILE_WRITE,
    Permission.FILE_DELETE,

    # Agent & Execution
    Permission.AGENT_CHAT,
    Permission.TOOL_EXECUTE,
    Permission.SANDBOX_EXECUTE,
    Permission.BACKGROUND_TASK,

    # MCP & Browser
    Permission.MCP_SERVER_READ,
    Permission.MCP_SERVER_MANAGE,
    Permission.MCP_TOOL_INVOKE,
    Permission.BROWSER_NAVIGATE,
    Permission.BROWSER_ACTION,
    Permission.BROWSER_DOWNLOAD,
    Permission.BROWSER_UPLOAD,

    # FinOps & Audit
    Permission.FINOPS_VIEW_REPORTS,
    Permission.FINOPS_MANAGE_BUDGETS,
    Permission.FINOPS_MANAGE_CREDITS,
    Permission.AUDIT_LOG_READ,
})

# 3. DEVELOPER: Workspace development, code execution, MCP & Browser tooling, personal FinOps
DEVELOPER_PERMISSIONS: FrozenSet[Permission] = frozenset({
    # Read-only org context
    Permission.ORG_READ,

    # Workspace & Project
    Permission.WORKSPACE_READ,
    Permission.WORKSPACE_WRITE,
    Permission.PROJECT_READ,
    Permission.PROJECT_WRITE,

    # Filesystem
    Permission.FILE_READ,
    Permission.FILE_WRITE,

    # Agent & Execution
    Permission.AGENT_CHAT,
    Permission.TOOL_EXECUTE,
    Permission.SANDBOX_EXECUTE,
    Permission.BACKGROUND_TASK,

    # MCP & Browser
    Permission.MCP_SERVER_READ,
    Permission.MCP_TOOL_INVOKE,
    Permission.BROWSER_NAVIGATE,
    Permission.BROWSER_ACTION,
    Permission.BROWSER_DOWNLOAD,
    Permission.BROWSER_UPLOAD,

    # FinOps
    Permission.FINOPS_VIEW_REPORTS,
})

# 4. VIEWER: Strictly read-only access with zero mutating or execution capabilities
VIEWER_PERMISSIONS: FrozenSet[Permission] = frozenset({
    Permission.ORG_READ,
    Permission.WORKSPACE_READ,
    Permission.PROJECT_READ,
    Permission.FILE_READ,
    Permission.MCP_SERVER_READ,
    Permission.FINOPS_VIEW_REPORTS,
})

# Role Template to Permission Set Mapping
ROLE_PERMISSION_TEMPLATES: Dict[RoleTemplate, FrozenSet[Permission]] = {
    RoleTemplate.OWNER: OWNER_PERMISSIONS,
    RoleTemplate.ADMIN: ADMIN_PERMISSIONS,
    RoleTemplate.DEVELOPER: DEVELOPER_PERMISSIONS,
    RoleTemplate.VIEWER: VIEWER_PERMISSIONS,
    RoleTemplate.CUSTOM: frozenset(),
}


def get_role_permissions(
    role: RoleTemplate,
    custom_permissions: Optional[Set[Permission]] = None,
) -> Set[Permission]:
    """
    Resolve the complete set of effective permissions for a role,
    combining the template baseline with any explicit custom grants.
    """
    base = set(ROLE_PERMISSION_TEMPLATES.get(role, frozenset()))
    if role == RoleTemplate.CUSTOM and custom_permissions:
        base.update(custom_permissions)
    return base


def can_assign_role(actor_role: RoleTemplate, target_role: RoleTemplate) -> bool:
    """
    Enforce hierarchical role assignment rules:
    - OWNER can assign any role (OWNER, ADMIN, DEVELOPER, VIEWER, CUSTOM).
    - ADMIN can only assign DEVELOPER and VIEWER (cannot elevate to ADMIN or OWNER).
    - DEVELOPER and VIEWER cannot assign any roles.
    """
    if actor_role == RoleTemplate.OWNER:
        return True
    if actor_role == RoleTemplate.ADMIN:
        return target_role in {RoleTemplate.DEVELOPER, RoleTemplate.VIEWER}
    return False


def can_modify_membership(actor_role: RoleTemplate, target_member_role: RoleTemplate) -> bool:
    """
    Guard membership modifications:
    - OWNER can modify anyone (except displacing the last owner).
    - ADMIN can modify DEVELOPER and VIEWER, but cannot modify ADMIN or OWNER.
    - DEVELOPER and VIEWER cannot modify anyone.
    """
    if actor_role == RoleTemplate.OWNER:
        return True
    if actor_role == RoleTemplate.ADMIN:
        return target_member_role in {RoleTemplate.DEVELOPER, RoleTemplate.VIEWER}
    return False

