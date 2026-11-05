"""
models.py -- Enterprise Identity, Authentication, and RBAC Data Models.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Provides normalized, auditable entities for Users, Organizations, Teams, Workspaces,
Projects, Roles, Permissions, Memberships, Sessions, and Service Identities.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


class RoleTemplate(str, enum.Enum):
    """Canonical role templates for Crusor AI IDE organizations and workspaces."""
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    DEVELOPER = "DEVELOPER"
    VIEWER = "VIEWER"
    CUSTOM = "CUSTOM"


class Permission(str, enum.Enum):
    """Fine-grained atomic permissions evaluated across all protected operations."""
    # Organization Management
    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"
    ORG_MANAGE_MEMBERS = "org:manage_members"
    ORG_MANAGE_ROLES = "org:manage_roles"
    ORG_MANAGE_BILLING = "org:manage_billing"

    # Workspace Operations
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_WRITE = "workspace:write"
    WORKSPACE_DELETE = "workspace:delete"
    WORKSPACE_MANAGE_ACCESS = "workspace:manage_access"

    # Project Operations
    PROJECT_READ = "project:read"
    PROJECT_WRITE = "project:write"
    PROJECT_DELETE = "project:delete"

    # Filesystem Operations
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    FILE_DELETE = "file:delete"

    # Agent & Code Execution
    AGENT_CHAT = "agent:chat"
    TOOL_EXECUTE = "tool:execute"
    SANDBOX_EXECUTE = "sandbox:execute"
    BACKGROUND_TASK = "background:task"

    # MCP (Model Context Protocol)
    MCP_SERVER_READ = "mcp:server_read"
    MCP_SERVER_MANAGE = "mcp:server_manage"
    MCP_TOOL_INVOKE = "mcp:tool_invoke"

    # Headless Browser Agent
    BROWSER_NAVIGATE = "browser:navigate"
    BROWSER_ACTION = "browser:action"
    BROWSER_DOWNLOAD = "browser:download"
    BROWSER_UPLOAD = "browser:upload"

    # FinOps & Credits
    FINOPS_VIEW_REPORTS = "finops:view_reports"
    FINOPS_MANAGE_BUDGETS = "finops:manage_budgets"
    FINOPS_MANAGE_CREDITS = "finops:manage_credits"

    # System & Audit
    AUDIT_LOG_READ = "audit:read"
    SYSTEM_ADMIN = "system:admin"


class MembershipStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class IdentityProviderType(str, enum.Enum):
    LOCAL_CREDENTIALS = "LOCAL"
    OAUTH_GOOGLE = "GOOGLE"
    OAUTH_GITHUB = "GITHUB"
    OIDC_ENTERPRISE = "OIDC"
    SERVICE_KEY = "SERVICE_KEY"


@dataclass
class User:
    """Stable internal identity representing an individual developer or administrator."""
    user_id: str
    email: str
    display_name: str
    password_hash: Optional[str] = None
    salt: Optional[str] = None
    is_active: bool = True
    is_superadmin: bool = False
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_safe_dict(self) -> Dict[str, Any]:
        """Safe representation with zero credential leakage."""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "is_active": self.is_active,
            "is_superadmin": self.is_superadmin,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class Organization:
    """Enterprise tenant boundary isolating teams, workspaces, credits, and policies."""
    org_id: str
    name: str
    owner_user_id: str
    created_at: float = field(default_factory=time.time)
    settings: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "org_id": self.org_id,
            "name": self.name,
            "owner_user_id": self.owner_user_id,
            "created_at": self.created_at,
            "settings": self.settings,
        }


@dataclass
class Team:
    """Collaborative unit within an organization."""
    team_id: str
    org_id: str
    name: str
    created_at: float = field(default_factory=time.time)


@dataclass
class Workspace:
    """Isolated development workspace bound to an organization and file tree."""
    workspace_id: str
    org_id: str
    name: str
    root_path: str
    owner_user_id: str
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Project:
    """Sub-unit of work located within an authorized workspace."""
    project_id: str
    workspace_id: str
    org_id: str
    name: str
    created_at: float = field(default_factory=time.time)


@dataclass
class Membership:
    """Association of a user with an organization, assigning their role and teams."""
    membership_id: str
    org_id: str
    user_id: str
    role: RoleTemplate
    custom_permissions: Set[Permission] = field(default_factory=set)
    team_ids: Set[str] = field(default_factory=set)
    status: MembershipStatus = MembershipStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class Session:
    """Active authenticated session backed by cryptographic token verification."""
    session_id: str
    user_id: str
    org_id: Optional[str]
    access_token_jti: str
    refresh_token_hash: str
    created_at: float
    expires_at: float
    is_revoked: bool = False
    ip_address: str = "127.0.0.1"
    user_agent: str = "CrusorDesktop/1.0"


@dataclass
class ServiceIdentity:
    """Automated service account or background worker identity."""
    service_id: str
    name: str
    org_id: str
    role: RoleTemplate = RoleTemplate.DEVELOPER
    explicit_permissions: Set[Permission] = field(default_factory=set)
    is_active: bool = True
    created_at: float = field(default_factory=time.time)

