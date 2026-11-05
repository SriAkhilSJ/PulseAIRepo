"""
test_phase_10_0_enterprise_identity_rbac.py -- Comprehensive Adversarial Test Suite for Phase 10.0.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Evaluates 25 deterministic security scenarios covering:
1. Invalid authentication token
2. Expired token
3. Invalid token issuer
4. Invalid token audience
5. Session replay
6. Session revocation
7. Cross-account access
8. Cross-organization access
9. Cross-workspace access
10. Unauthorized project access
11. Viewer attempting file modification
12. Developer attempting administrative actions
13. Unauthorized role assignment
14. Privilege escalation attempts
15. Client-supplied identity manipulation
16. Unauthorized MCP tool invocation
17. Browser Agent permission bypass
18. Unauthorized execution request
19. Revoked membership with active sessions
20. Unauthorized financial record access
21. Cross-organization credit manipulation
22. Concurrent role changes
23. Concurrent permission checks
24. Missing identity context
25. Fail-closed authorization behavior
"""

from __future__ import annotations

import concurrent.futures
from decimal import Decimal
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict

from src.identity.models import (
    MembershipStatus,
    Permission,
    RoleTemplate,
    User,
)
from src.identity.roles import (
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
    hash_password,
    verify_password,
)
from src.identity.tenancy import (
    OrganizationNotFoundError,
    TenancyError,
    TenancyManager,
    UnauthorizedRoleAssignmentError,
)
from src.identity.authorization import (
    AuthorizationDecision,
    AuthorizationEngine,
    AuthorizationRequest,
    AuthorizationResult,
)
from src.identity.resource_guard import (
    IdentitySpoofingError,
    ResourceAccessDeniedError,
    ResourceGuard,
)
from src.identity.tool_authorizer import (
    IdentityAwareToolAuthorizer,
)
from src.identity.finops_integration import (
    CrossTenantFinancialViolationError,
    FinOpsAccessDeniedError,
    IdentityAwareFinOpsGovernor,
)
from src.identity.audit import (
    AuditEventType,
    AuditLedger,
)


class TestPhase10EnterpriseIdentityRBAC(unittest.TestCase):
    """25 Adversarial Test Scenarios for Phase 10.0 Enterprise Identity & RBAC."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="crusor_phase10_")
        self.token_manager = TokenManager(signing_key=b"0123456789abcdef0123456789abcdef", issuer="crusor-auth", audience="crusor-ide")
        self.auth_service = AuthenticationService(token_manager=self.token_manager)
        self.tenancy_mgr = TenancyManager()
        self.auth_engine = AuthorizationEngine(tenancy_manager=self.tenancy_mgr)
        self.resource_guard = ResourceGuard(auth_engine=self.auth_engine, tenancy_manager=self.tenancy_mgr)
        self.tool_authorizer = IdentityAwareToolAuthorizer(auth_engine=self.auth_engine)
        self.finops_governor = IdentityAwareFinOpsGovernor(auth_engine=self.auth_engine)
        self.audit_ledger = AuditLedger()

        # Seed standard users
        self.user_alice = self.auth_service.register_user("alice@corp.com", "PasswordAlice123!", "Alice Owner")
        self.user_bob = self.auth_service.register_user("bob@corp.com", "PasswordBob123!", "Bob Admin")
        self.user_charlie = self.auth_service.register_user("charlie@corp.com", "PasswordCharlie123!", "Charlie Dev")
        self.user_david = self.auth_service.register_user("david@corp.com", "PasswordDavid123!", "David Viewer")
        self.user_eve = self.auth_service.register_user("eve@othercorp.com", "PasswordEve123!", "Eve Attacker")

        # Seed Organizations
        self.org_alpha, _ = self.tenancy_mgr.create_organization("Alpha Corp", self.user_alice, org_id="org_alpha")
        self.org_beta, _ = self.tenancy_mgr.create_organization("Beta Corp", self.user_eve, org_id="org_beta")

        # Assign roles in Org Alpha
        self.tenancy_mgr.add_or_update_member(self.org_alpha.org_id, self.user_bob, RoleTemplate.ADMIN, RoleTemplate.OWNER)
        self.tenancy_mgr.add_or_update_member(self.org_alpha.org_id, self.user_charlie, RoleTemplate.DEVELOPER, RoleTemplate.ADMIN)
        self.tenancy_mgr.add_or_update_member(self.org_alpha.org_id, self.user_david, RoleTemplate.VIEWER, RoleTemplate.ADMIN)

        # Seed Workspaces
        self.ws_dir = os.path.join(self.tmp_dir, "ws_alpha")
        os.makedirs(self.ws_dir, exist_ok=True)
        self.workspace_alpha = self.tenancy_mgr.create_workspace("org_alpha", "Alpha Workspace", self.ws_dir, self.user_alice, workspace_id="ws_alpha")
        self.project_alpha = self.tenancy_mgr.create_project("ws_alpha", "Alpha Project", project_id="proj_alpha")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Invalid authentication token
    def test_01_invalid_authentication_token(self) -> None:
        """Malformed or tampered JWT token signatures must be rejected."""
        token, _ = self.token_manager.generate_token(self.user_alice.user_id)
        tampered = token[:-6] + "xxxxxx"
        with self.assertRaises(InvalidTokenError):
            self.token_manager.verify_token(tampered)

        with self.assertRaises(InvalidTokenError):
            self.token_manager.verify_token("not.a.valid.jwt.token")

    # 2. Expired token
    def test_02_expired_token(self) -> None:
        """Token with expiration in the past must be rejected."""
        token, _ = self.token_manager.generate_token(self.user_alice.user_id, ttl_seconds=-10)
        with self.assertRaises(TokenExpiredError):
            self.token_manager.verify_token(token)

    # 3. Invalid token issuer
    def test_03_invalid_token_issuer(self) -> None:
        """Token generated by rogue or unrecognized issuer must be rejected."""
        rogue_mgr = TokenManager(signing_key=b"0123456789abcdef0123456789abcdef", issuer="rogue-issuer")
        rogue_token, _ = rogue_mgr.generate_token(self.user_alice.user_id)
        with self.assertRaises(InvalidTokenError) as ctx:
            self.token_manager.verify_token(rogue_token)
        self.assertIn("Invalid token issuer", str(ctx.exception))

    # 4. Invalid token audience
    def test_04_invalid_token_audience(self) -> None:
        """Token designated for another service or audience must be rejected."""
        rogue_mgr = TokenManager(signing_key=b"0123456789abcdef0123456789abcdef", audience="some-other-audience")
        rogue_token, _ = rogue_mgr.generate_token(self.user_alice.user_id)
        with self.assertRaises(InvalidTokenError) as ctx:
            self.token_manager.verify_token(rogue_token)
        self.assertIn("Invalid token audience", str(ctx.exception))

    # 5. Session replay prevention
    def test_05_session_replay_prevention(self) -> None:
        """Replaying an old refresh token after rotation must trigger immediate revocation."""
        user, token_pair = self.auth_service.authenticate_credentials("alice@corp.com", "PasswordAlice123!")
        old_refresh = token_pair.refresh_token

        # First refresh succeeds and rotates refresh token
        new_pair = self.auth_service.refresh_access_token(old_refresh)
        self.assertIsNotNone(new_pair.access_token)

        # Attempting to replay the old refresh token must be rejected and revoke session
        with self.assertRaises(InvalidTokenError):
            self.auth_service.refresh_access_token(old_refresh)

    # 6. Session revocation
    def test_06_session_revocation(self) -> None:
        """Explicit logout immediately revokes the session and access token."""
        user, token_pair = self.auth_service.authenticate_credentials("alice@corp.com", "PasswordAlice123!")
        u, session, claims = self.auth_service.validate_access_token(token_pair.access_token)
        self.assertFalse(session.is_revoked)

        # Explicitly revoke session
        self.auth_service.revoke_session(session.session_id)

        # Subsequent validation must raise SessionRevokedError
        with self.assertRaises(SessionRevokedError):
            self.auth_service.validate_access_token(token_pair.access_token)

    # 7. Cross-account access blocked
    def test_07_cross_account_access_blocked(self) -> None:
        """User Eve cannot access Alice's session or private profile."""
        eve_user, eve_tokens = self.auth_service.authenticate_credentials("eve@othercorp.com", "PasswordEve123!")
        alice_user, alice_tokens = self.auth_service.authenticate_credentials("alice@corp.com", "PasswordAlice123!")

        # Eve claims to act as Alice
        with self.assertRaises(IdentitySpoofingError):
            self.resource_guard.verify_client_identity(eve_user, client_supplied_user_id=alice_user.user_id)

    # 8. Cross-organization access blocked
    def test_08_cross_organization_access_blocked(self) -> None:
        """Member of Org Beta (Eve) cannot access Org Alpha resources."""
        req = AuthorizationRequest(
            principal=self.user_eve,
            permission=Permission.WORKSPACE_READ,
            org_id="org_alpha",
            workspace_id="ws_alpha",
        )
        res = self.auth_engine.evaluate(req)
        self.assertFalse(res.is_allowed)
        self.assertEqual(res.decision, AuthorizationDecision.DENY)
        self.assertIn("not a member of organization", res.reason)

    # 9. Cross-workspace access blocked
    def test_09_cross_workspace_access_blocked(self) -> None:
        """Attempting to access a workspace belonging to a different org is blocked."""
        # Create workspace in Org Beta
        ws_beta_dir = os.path.join(self.tmp_dir, "ws_beta")
        os.makedirs(ws_beta_dir, exist_ok=True)
        ws_beta = self.tenancy_mgr.create_workspace("org_beta", "Beta WS", ws_beta_dir, self.user_eve, workspace_id="ws_beta")

        # Charlie (member of org_alpha) attempts to query ws_beta while targeting org_alpha
        req = AuthorizationRequest(
            principal=self.user_charlie,
            permission=Permission.WORKSPACE_READ,
            org_id="org_alpha",
            workspace_id="ws_beta",
        )
        res = self.auth_engine.evaluate(req)
        self.assertFalse(res.is_allowed)
        self.assertEqual(res.decision, AuthorizationDecision.DENY)
        self.assertIn("Cross-organization access blocked", res.reason)

    # 10. Unauthorized project access
    def test_10_unauthorized_project_access(self) -> None:
        """Access to a project that does not belong to the target workspace/org is rejected."""
        req = AuthorizationRequest(
            principal=self.user_eve,
            permission=Permission.PROJECT_READ,
            org_id="org_alpha",
            project_id="proj_alpha",
        )
        res = self.auth_engine.evaluate(req)
        self.assertFalse(res.is_allowed)
        self.assertEqual(res.decision, AuthorizationDecision.DENY)

    # 11. Viewer attempting file modification
    def test_11_viewer_attempting_file_modification(self) -> None:
        """VIEWER role is strictly prohibited from writing or deleting files."""
        # Viewer can read
        read_req = AuthorizationRequest(
            principal=self.user_david,
            permission=Permission.FILE_READ,
            org_id="org_alpha",
            workspace_id="ws_alpha",
        )
        self.assertTrue(self.auth_engine.evaluate(read_req).is_allowed)

        # Viewer cannot write
        write_req = AuthorizationRequest(
            principal=self.user_david,
            permission=Permission.FILE_WRITE,
            org_id="org_alpha",
            workspace_id="ws_alpha",
        )
        write_res = self.auth_engine.evaluate(write_req)
        self.assertFalse(write_res.is_allowed)
        self.assertEqual(write_res.decision, AuthorizationDecision.DENY)
        self.assertIn("lacks required permission", write_res.reason)

    # 12. Developer attempting administrative actions
    def test_12_developer_attempting_admin_actions(self) -> None:
        """DEVELOPER role cannot modify organization membership, roles, or billing."""
        req = AuthorizationRequest(
            principal=self.user_charlie,
            permission=Permission.ORG_MANAGE_MEMBERS,
            org_id="org_alpha",
        )
        res = self.auth_engine.evaluate(req)
        self.assertFalse(res.is_allowed)
        self.assertEqual(res.decision, AuthorizationDecision.DENY)
        self.assertIn("lacks required permission", res.reason)

    # 13. Unauthorized role assignment
    def test_13_unauthorized_role_assignment(self) -> None:
        """ADMIN cannot assign OWNER role; DEVELOPER cannot assign any role."""
        # Admin Bob attempts to assign Owner
        self.assertFalse(can_assign_role(RoleTemplate.ADMIN, RoleTemplate.OWNER))
        with self.assertRaises(UnauthorizedRoleAssignmentError):
            self.tenancy_mgr.add_or_update_member("org_alpha", self.user_charlie, RoleTemplate.OWNER, RoleTemplate.ADMIN)

        # Developer Charlie attempts to assign Developer
        self.assertFalse(can_assign_role(RoleTemplate.DEVELOPER, RoleTemplate.DEVELOPER))
        with self.assertRaises(UnauthorizedRoleAssignmentError):
            self.tenancy_mgr.add_or_update_member("org_alpha", self.user_david, RoleTemplate.DEVELOPER, RoleTemplate.DEVELOPER)

    # 14. Privilege escalation attempts
    def test_14_privilege_escalation_attempts(self) -> None:
        """A user cannot elevate their own role to ADMIN or OWNER."""
        # Developer Charlie attempts to self-modify to Admin
        self.assertFalse(can_modify_membership(RoleTemplate.DEVELOPER, RoleTemplate.ADMIN))
        with self.assertRaises(UnauthorizedRoleAssignmentError):
            self.tenancy_mgr.add_or_update_member("org_alpha", self.user_charlie, RoleTemplate.ADMIN, RoleTemplate.DEVELOPER)

    # 15. Client-supplied identity manipulation
    def test_15_client_supplied_identity_manipulation(self) -> None:
        """Client headers claiming a different user or tenant are detected and rejected."""
        with self.assertRaises(IdentitySpoofingError):
            self.resource_guard.verify_client_identity(
                self.user_charlie,
                client_supplied_user_id=self.user_alice.user_id,
            )

        with self.assertRaises(IdentitySpoofingError):
            self.resource_guard.verify_client_identity(
                self.user_charlie,
                verified_org_id="org_alpha",
                client_supplied_org_id="org_beta",
            )

    # 16. Unauthorized MCP tool invocation
    def test_16_unauthorized_mcp_tool_invocation(self) -> None:
        """VIEWER role or non-member cannot execute MCP tools."""
        res_viewer = self.tool_authorizer.authorize_mcp_tool(
            self.user_david,
            org_id="org_alpha",
            server_id="github_mcp",
            tool_name="create_issue",
        )
        self.assertFalse(res_viewer.is_allowed)
        self.assertEqual(res_viewer.decision, AuthorizationDecision.DENY)

        res_nonmember = self.tool_authorizer.authorize_mcp_tool(
            self.user_eve,
            org_id="org_alpha",
            server_id="github_mcp",
            tool_name="create_issue",
        )
        self.assertFalse(res_nonmember.is_allowed)
        self.assertEqual(res_nonmember.decision, AuthorizationDecision.DENY)

    # 17. Browser Agent permission bypass
    def test_17_browser_agent_permission_bypass(self) -> None:
        """VIEWER role cannot perform browser navigation or actions."""
        res_nav = self.tool_authorizer.authorize_browser_action(
            self.user_david,
            org_id="org_alpha",
            action_type="navigate",
            target_url="https://internal.corp",
        )
        self.assertFalse(res_nav.is_allowed)
        self.assertEqual(res_nav.decision, AuthorizationDecision.DENY)

    # 18. Unauthorized execution request
    def test_18_unauthorized_execution_request(self) -> None:
        """VIEWER cannot execute shell commands or code execution tools."""
        res_exec = self.tool_authorizer.authorize_tool_call(
            self.user_david,
            org_id="org_alpha",
            workspace_id="ws_alpha",
            tool_name="run_shell_command",
            tool_args={"cmd": "dir"},
        )
        self.assertFalse(res_exec.is_allowed)
        self.assertEqual(res_exec.decision, AuthorizationDecision.DENY)

    # 19. Revoked membership with active sessions
    def test_19_revoked_membership_with_active_sessions(self) -> None:
        """Revoking an organization membership immediately denies subsequent authorized calls."""
        # Charlie initially has DEVELOPER rights
        req = AuthorizationRequest(
            principal=self.user_charlie,
            permission=Permission.FILE_WRITE,
            org_id="org_alpha",
            workspace_id="ws_alpha",
        )
        self.assertTrue(self.auth_engine.evaluate(req).is_allowed)

        # Alice revokes Charlie's membership
        self.tenancy_mgr.revoke_membership("org_alpha", self.user_charlie.user_id, RoleTemplate.OWNER)

        # Subsequent evaluation fails closed
        res_revoked = self.auth_engine.evaluate(req)
        self.assertFalse(res_revoked.is_allowed)
        self.assertEqual(res_revoked.decision, AuthorizationDecision.DENY)
        self.assertIn("REVOKED", res_revoked.reason)

    # 20. Unauthorized financial record access
    def test_20_unauthorized_financial_record_access(self) -> None:
        """Non-members cannot view organizational FinOps reports."""
        with self.assertRaises(FinOpsAccessDeniedError):
            self.finops_governor.authorize_view_reports(self.user_eve, "org_alpha")

    # 21. Cross-organization credit manipulation
    def test_21_cross_organization_credit_manipulation(self) -> None:
        """An actor from Org Beta cannot grant or manipulate virtual credits in Org Alpha."""
        with self.assertRaises(CrossTenantFinancialViolationError):
            self.finops_governor.authorize_credit_operation(
                principal=self.user_eve,
                target_org_id="org_alpha",
                operation_type="grant",
                amount_diamonds=Decimal("5000"),
                actor_org_id="org_beta",
            )

    # 22. Concurrent role changes
    def test_22_concurrent_role_changes(self) -> None:
        """Multi-threaded membership and role updates must be concurrency-safe."""
        def modify_role(i: int) -> None:
            role = RoleTemplate.DEVELOPER if i % 2 == 0 else RoleTemplate.VIEWER
            self.tenancy_mgr.add_or_update_member("org_alpha", self.user_charlie, role, RoleTemplate.OWNER)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(modify_role, i) for i in range(24)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        m = self.tenancy_mgr.get_membership("org_alpha", self.user_charlie.user_id)
        self.assertIsNotNone(m)
        self.assertIn(m.role, {RoleTemplate.DEVELOPER, RoleTemplate.VIEWER})

    # 23. Concurrent permission checks
    def test_23_concurrent_permission_checks(self) -> None:
        """High throughput concurrent authorization evaluations execute deterministically."""
        def check_perm(i: int) -> bool:
            req = AuthorizationRequest(
                principal=self.user_charlie,
                permission=Permission.FILE_READ,
                org_id="org_alpha",
                workspace_id="ws_alpha",
            )
            return self.auth_engine.evaluate(req).is_allowed

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(check_perm, i) for i in range(50)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(results), 50)
        self.assertTrue(all(results))

    # 24. Missing identity context
    def test_24_missing_identity_context(self) -> None:
        """Anonymous or missing identity requests fail closed to DENY."""
        req = AuthorizationRequest(
            principal=None,
            permission=Permission.FILE_READ,
            org_id="org_alpha",
        )
        res = self.auth_engine.evaluate(req)
        self.assertFalse(res.is_allowed)
        self.assertEqual(res.decision, AuthorizationDecision.DENY)
        self.assertIn("Missing identity context", res.reason)

    # 25. Fail-closed authorization behavior
    def test_25_fail_closed_authorization_behavior(self) -> None:
        """Any unexpected engine exceptions or malformed policies strictly yield DENY."""
        class MalformedPrincipal:
            pass

        req = AuthorizationRequest(
            principal=MalformedPrincipal(), # type: ignore
            permission=Permission.FILE_WRITE,
            org_id="org_alpha",
        )
        res = self.auth_engine.evaluate(req)
        self.assertFalse(res.is_allowed)
        self.assertEqual(res.decision, AuthorizationDecision.DENY)
        self.assertIn("FAIL_CLOSED", res.reason)


if __name__ == "__main__":
    unittest.main()

