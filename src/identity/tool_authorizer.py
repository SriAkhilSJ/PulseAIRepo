"""
tool_authorizer.py -- Identity-Aware Tool, MCP, Browser & Execution Authorizer.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Integrates Phase 9.5 MCP/Browser security with Phase 10.0 Identity and RBAC:
- Binds tool execution, MCP invocation, and browser automation to the verified principal.
- Enforces that VIEWER roles can never execute tools, mutate workspaces, or invoke MCP servers.
- Preserves cryptographic approval token binding and replay defenses.
- Enforces fail-closed denials for unauthorized execution attempts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from src.identity.authorization import (
    AuthorizationDecision,
    AuthorizationEngine,
    AuthorizationRequest,
    AuthorizationResult,
    get_authorization_engine,
)
from src.identity.models import Permission, RoleTemplate, User

log = logging.getLogger("crusorai.identity.tool_authorizer")

# Tools classified as read-only / informational
READ_ONLY_TOOLS: Set[str] = {
    "read_file",
    "search_files",
    "list_directory",
    "find_by_name",
    "get_documentation",
    "view_diagnostics",
}

# Tools classified as high risk mutating operations
HIGH_RISK_TOOLS: Set[str] = {
    "run_shell_command",
    "execute_script",
    "delete_file",
    "modify_system_config",
    "drop_database",
    "browser_fill_password",
    "browser_submit_form",
}


class ToolAuthorizationError(Exception):
    """Raised when an agent tool, MCP server, or browser action is denied."""
    pass


class IdentityAwareToolAuthorizer:
    """
    Authorizes agent tool invocations, MCP tool execution, and browser actions
    against the verified user identity and assigned RBAC role.
    """

    def __init__(self, auth_engine: Optional[AuthorizationEngine] = None) -> None:
        self.auth_engine = auth_engine or get_authorization_engine()

    def authorize_tool_call(
        self,
        principal: User,
        org_id: str,
        workspace_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        approval_token: Optional[str] = None,
    ) -> AuthorizationResult:
        """
        Authorize execution of an agent tool.
        Enforces that read-only roles (VIEWER) cannot execute mutating or execution tools.
        """
        is_read_only = tool_name in READ_ONLY_TOOLS
        is_high_risk = tool_name in HIGH_RISK_TOOLS

        if is_read_only:
            permission = Permission.FILE_READ
        else:
            permission = Permission.TOOL_EXECUTE

        req = AuthorizationRequest(
            principal=principal,
            permission=permission,
            org_id=org_id,
            workspace_id=workspace_id,
            resource_type="agent_tool",
            resource_id=tool_name,
            is_high_risk=is_high_risk,
            approval_token=approval_token,
            metadata={"tool_args": tool_args},
        )
        result = self.auth_engine.evaluate(req)
        if not result.is_allowed:
            log.warning(f"Tool invocation denied: {tool_name} by {principal.user_id} ({result.reason})")
        return result

    def authorize_mcp_tool(
        self,
        principal: User,
        org_id: str,
        server_id: str,
        tool_name: str,
        approval_token: Optional[str] = None,
    ) -> AuthorizationResult:
        """
        Authorize an external MCP tool invocation.
        Requires Permission.MCP_TOOL_INVOKE and active membership in the organization.
        """
        req = AuthorizationRequest(
            principal=principal,
            permission=Permission.MCP_TOOL_INVOKE,
            org_id=org_id,
            resource_type="mcp_tool",
            resource_id=f"{server_id}:{tool_name}",
            is_high_risk=False,
            approval_token=approval_token,
        )
        return self.auth_engine.evaluate(req)

    def authorize_browser_action(
        self,
        principal: User,
        org_id: str,
        action_type: str,  # "navigate", "click", "download", "upload"
        target_url: str,
        approval_token: Optional[str] = None,
    ) -> AuthorizationResult:
        """
        Authorize headless browser agent actions.
        Enforces distinct permissions for navigate vs action vs download/upload.
        """
        if action_type == "navigate":
            permission = Permission.BROWSER_NAVIGATE
        elif action_type == "download":
            permission = Permission.BROWSER_DOWNLOAD
        elif action_type == "upload":
            permission = Permission.BROWSER_UPLOAD
        else:
            permission = Permission.BROWSER_ACTION

        is_high_risk = action_type in {"click", "upload"}

        req = AuthorizationRequest(
            principal=principal,
            permission=permission,
            org_id=org_id,
            resource_type="browser_action",
            resource_id=target_url,
            is_high_risk=is_high_risk,
            approval_token=approval_token,
        )
        return self.auth_engine.evaluate(req)


_GLOBAL_TOOL_AUTHORIZER: Optional[IdentityAwareToolAuthorizer] = None

def get_tool_authorizer() -> IdentityAwareToolAuthorizer:
    global _GLOBAL_TOOL_AUTHORIZER
    if _GLOBAL_TOOL_AUTHORIZER is None:
        _GLOBAL_TOOL_AUTHORIZER = IdentityAwareToolAuthorizer()
    return _GLOBAL_TOOL_AUTHORIZER

