"""
tenancy.py -- Enterprise Multi-Tenancy, Organization & Membership Management.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Manages Organizations, Teams, Workspaces, Projects, and Memberships with
strict ownership verification, role assignment validation, and concurrency safety.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Set

from src.identity.models import (
    Membership,
    MembershipStatus,
    Organization,
    Permission,
    Project,
    RoleTemplate,
    Team,
    User,
    Workspace,
)
from src.identity.roles import can_assign_role, can_modify_membership

log = logging.getLogger("crusorai.identity.tenancy")


class TenancyError(Exception):
    """Base exception for tenancy, membership, and organization violations."""
    pass


class OrganizationNotFoundError(TenancyError):
    pass


class UnauthorizedRoleAssignmentError(TenancyError):
    pass


class TenancyManager:
    """
    Centralized store and governance engine for Organizations, Memberships,
    Workspaces, Teams, and Projects.
    """

    def __init__(self) -> None:
        self._orgs: Dict[str, Organization] = {}            # org_id -> Organization
        self._memberships: Dict[str, Membership] = {}        # membership_id -> Membership
        self._memberships_by_user_org: Dict[str, str] = {}   # f"{org_id}:{user_id}" -> membership_id
        self._workspaces: Dict[str, Workspace] = {}          # workspace_id -> Workspace
        self._projects: Dict[str, Project] = {}              # project_id -> Project
        self._teams: Dict[str, Team] = {}                    # team_id -> Team
        self._lock = threading.Lock()

    def create_organization(
        self,
        name: str,
        owner_user: User,
        org_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Organization, Membership]:
        """
        Create a new enterprise organization and establish the creator as the initial OWNER.
        """
        oid = org_id or f"org_{uuid.uuid4().hex[:12]}"
        now = time.time()

        with self._lock:
            if oid in self._orgs:
                raise TenancyError(f"Organization {oid} already exists")

            org = Organization(
                org_id=oid,
                name=name,
                owner_user_id=owner_user.user_id,
                created_at=now,
                settings=settings or {},
            )
            self._orgs[oid] = org

            mid = f"mem_{uuid.uuid4().hex[:12]}"
            membership = Membership(
                membership_id=mid,
                org_id=oid,
                user_id=owner_user.user_id,
                role=RoleTemplate.OWNER,
                status=MembershipStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            self._memberships[mid] = membership
            self._memberships_by_user_org[f"{oid}:{owner_user.user_id}"] = mid
            log.info(f"Created organization {oid} ('{name}') with owner {owner_user.user_id}")

        return org, membership

    def get_organization(self, org_id: str) -> Optional[Organization]:
        with self._lock:
            return self._orgs.get(org_id)

    def add_or_update_member(
        self,
        org_id: str,
        target_user: User,
        target_role: RoleTemplate,
        actor_role: RoleTemplate,
        custom_permissions: Optional[Set[Permission]] = None,
        actor_user_id: Optional[str] = None,
    ) -> Membership:
        """
        Add a user to an organization or modify their existing role.
        Enforces hierarchical role assignment permissions.
        """
        if not can_assign_role(actor_role, target_role):
            raise UnauthorizedRoleAssignmentError(
                f"Actor with role {actor_role.value} cannot assign role {target_role.value}"
            )

        key = f"{org_id}:{target_user.user_id}"
        now = time.time()

        with self._lock:
            org = self._orgs.get(org_id)
            if not org:
                raise OrganizationNotFoundError(f"Organization {org_id} does not exist")

            existing_mid = self._memberships_by_user_org.get(key)
            if existing_mid:
                membership = self._memberships[existing_mid]
                # Check modification rights
                if not can_modify_membership(actor_role, membership.role):
                    raise UnauthorizedRoleAssignmentError(
                        f"Actor with role {actor_role.value} cannot modify member with role {membership.role.value}"
                    )
                membership.role = target_role
                membership.status = MembershipStatus.ACTIVE
                membership.custom_permissions = set(custom_permissions or [])
                membership.updated_at = now
                log.info(f"Updated member {target_user.user_id} in {org_id} to role {target_role.value}")
                return membership

            # Create new membership
            mid = f"mem_{uuid.uuid4().hex[:12]}"
            membership = Membership(
                membership_id=mid,
                org_id=org_id,
                user_id=target_user.user_id,
                role=target_role,
                custom_permissions=set(custom_permissions or []),
                status=MembershipStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            self._memberships[mid] = membership
            self._memberships_by_user_org[key] = mid
            log.info(f"Added member {target_user.user_id} to {org_id} with role {target_role.value}")
            return membership

    def revoke_membership(
        self,
        org_id: str,
        target_user_id: str,
        actor_role: RoleTemplate,
    ) -> bool:
        """Revoke a user's membership in an organization."""
        key = f"{org_id}:{target_user_id}"
        with self._lock:
            mid = self._memberships_by_user_org.get(key)
            if not mid:
                return False
            membership = self._memberships.get(mid)
            if not membership:
                return False

            if not can_modify_membership(actor_role, membership.role):
                raise UnauthorizedRoleAssignmentError(
                    f"Actor with role {actor_role.value} cannot revoke member with role {membership.role.value}"
                )

            # Prevent removing the sole owner
            if membership.role == RoleTemplate.OWNER:
                owners = [
                    m for m in self._memberships.values()
                    if m.org_id == org_id and m.role == RoleTemplate.OWNER and m.status == MembershipStatus.ACTIVE
                ]
                if len(owners) <= 1:
                    raise TenancyError("Cannot revoke the sole OWNER of an organization")

            membership.status = MembershipStatus.REVOKED
            membership.updated_at = time.time()
            log.info(f"Revoked membership of {target_user_id} in {org_id}")
            return True

    def get_membership(self, org_id: str, user_id: str) -> Optional[Membership]:
        """Look up active or inactive membership for a user in an organization."""
        key = f"{org_id}:{user_id}"
        with self._lock:
            mid = self._memberships_by_user_org.get(key)
            if mid:
                return self._memberships.get(mid)
            return None

    def get_active_membership(self, org_id: str, user_id: str) -> Optional[Membership]:
        """Look up strictly ACTIVE membership."""
        m = self.get_membership(org_id, user_id)
        if m and m.status == MembershipStatus.ACTIVE:
            return m
        return None

    def create_workspace(
        self,
        org_id: str,
        name: str,
        root_path: str,
        owner_user: User,
        workspace_id: Optional[str] = None,
    ) -> Workspace:
        """Create and bind a workspace to an organization."""
        wid = workspace_id or f"ws_{uuid.uuid4().hex[:12]}"
        now = time.time()

        with self._lock:
            if org_id not in self._orgs:
                raise OrganizationNotFoundError(f"Organization {org_id} does not exist")

            ws = Workspace(
                workspace_id=wid,
                org_id=org_id,
                name=name,
                root_path=root_path,
                owner_user_id=owner_user.user_id,
                created_at=now,
            )
            self._workspaces[wid] = ws
            return ws

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        with self._lock:
            return self._workspaces.get(workspace_id)

    def create_project(
        self,
        workspace_id: str,
        name: str,
        project_id: Optional[str] = None,
    ) -> Project:
        """Create a project within an existing workspace."""
        pid = project_id or f"proj_{uuid.uuid4().hex[:12]}"
        with self._lock:
            ws = self._workspaces.get(workspace_id)
            if not ws:
                raise TenancyError(f"Workspace {workspace_id} does not exist")

            proj = Project(
                project_id=pid,
                workspace_id=workspace_id,
                org_id=ws.org_id,
                name=name,
                created_at=time.time(),
            )
            self._projects[pid] = proj
            return proj

    def get_project(self, project_id: str) -> Optional[Project]:
        with self._lock:
            return self._projects.get(project_id)


_GLOBAL_TENANCY_MANAGER: Optional[TenancyManager] = None

def get_tenancy_manager() -> TenancyManager:
    global _GLOBAL_TENANCY_MANAGER
    if _GLOBAL_TENANCY_MANAGER is None:
        _GLOBAL_TENANCY_MANAGER = TenancyManager()
    return _GLOBAL_TENANCY_MANAGER

