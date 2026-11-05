"""
resource_guard.py -- Resource-Level Access Control & Anti-Spoofing Guard.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Provides:
- Strict path sandboxing enforcing that file operations stay strictly within the authorized workspace.
- Cross-tenant resource isolation (files, projects, workspaces).
- Client-supplied identity verification (defeats header manipulation and impersonation).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.identity.authorization import (
    AuthorizationDecision,
    AuthorizationEngine,
    AuthorizationRequest,
    AuthorizationResult,
    get_authorization_engine,
)
from src.identity.models import Permission, User, Workspace
from src.identity.tenancy import TenancyManager, get_tenancy_manager

log = logging.getLogger("crusorai.identity.resource_guard")


class ResourceAccessDeniedError(Exception):
    """Raised when resource-level boundaries or client identity checks fail."""
    pass


class IdentitySpoofingError(ResourceAccessDeniedError):
    """Raised when client headers attempt to spoof a different user or tenant."""
    pass


class ResourceGuard:
    """
    Enforces resource-level boundaries, workspace filesystem confinement,
    and anti-spoofing checks.
    """

    def __init__(
        self,
        auth_engine: Optional[AuthorizationEngine] = None,
        tenancy_manager: Optional[TenancyManager] = None,
    ) -> None:
        self.auth_engine = auth_engine or get_authorization_engine()
        self.tenancy_manager = tenancy_manager or get_tenancy_manager()

    def verify_client_identity(
        self,
        verified_user: User,
        client_supplied_user_id: Optional[str] = None,
        verified_org_id: Optional[str] = None,
        client_supplied_org_id: Optional[str] = None,
    ) -> None:
        """
        Anti-spoofing gate: Client-supplied IDs must never override or contradict
        the cryptographically verified token claims.
        """
        if client_supplied_user_id and client_supplied_user_id != verified_user.user_id:
            raise IdentitySpoofingError(
                f"Identity spoofing attempt detected: client claimed user {client_supplied_user_id}, "
                f"but verified token subject is {verified_user.user_id}"
            )

        if client_supplied_org_id and verified_org_id and client_supplied_org_id != verified_org_id:
            raise IdentitySpoofingError(
                f"Tenant spoofing attempt detected: client claimed org {client_supplied_org_id}, "
                f"but verified token tenant is {verified_org_id}"
            )

    def authorize_file_operation(
        self,
        user: User,
        org_id: str,
        workspace_id: str,
        relative_path: str,
        is_write: bool = False,
        is_delete: bool = False,
    ) -> Path:
        """
        Authorize a file read/write/delete operation:
        1. Checks RBAC permission (FILE_READ, FILE_WRITE, or FILE_DELETE).
        2. Validates workspace ownership and org boundary.
        3. Enforces canonical path containment within workspace root.
        """
        if is_delete:
            permission = Permission.FILE_DELETE
        elif is_write:
            permission = Permission.FILE_WRITE
        else:
            permission = Permission.FILE_READ

        req = AuthorizationRequest(
            principal=user,
            permission=permission,
            org_id=org_id,
            workspace_id=workspace_id,
            resource_type="file",
            resource_id=relative_path,
        )
        res = self.auth_engine.evaluate(req)
        if not res.is_allowed:
            raise ResourceAccessDeniedError(f"File access denied: {res.reason}")

        ws = self.tenancy_manager.get_workspace(workspace_id)
        if not ws:
            raise ResourceAccessDeniedError(f"Workspace {workspace_id} not found")

        # Path traversal guard
        canonical_root = Path(ws.root_path).resolve()
        target_path = (canonical_root / relative_path).resolve()

        try:
            target_path.relative_to(canonical_root)
        except ValueError:
            raise ResourceAccessDeniedError(
                f"Workspace traversal blocked: path '{relative_path}' resolves outside root '{canonical_root}'"
            )

        return target_path


_GLOBAL_RESOURCE_GUARD: Optional[ResourceGuard] = None

def get_resource_guard() -> ResourceGuard:
    global _GLOBAL_RESOURCE_GUARD
    if _GLOBAL_RESOURCE_GUARD is None:
        _GLOBAL_RESOURCE_GUARD = ResourceGuard()
    return _GLOBAL_RESOURCE_GUARD

