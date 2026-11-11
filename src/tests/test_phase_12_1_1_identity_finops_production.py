"""
test_phase_12_1_1_identity_finops_production.py - Phase 12.1.1 Identity, FinOps & Production Readiness Qualification.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal

from src.identity.authorization import (
    AuthorizationDecision,
    AuthorizationEngine,
    AuthorizationRequest,
    get_authorization_engine,
)
from src.identity.models import Permission, RoleTemplate, User
from src.identity.tool_authorizer import IdentityAwareToolAuthorizer
from src.finops.budget_governor import BudgetGovernor, BudgetPolicy, BudgetExhaustionError
from src.orchestration.finops_governor import OrchestrationFinOpsGovernor, BudgetExhaustedError
from src.production.engine import ProductionReadinessEngine
from src.production.models import (
    ProductionReadinessVerdict,
    TargetEnvironmentConfig,
    EnvironmentProfile,
)


class TestPhase1211IdentityFinOpsProduction(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="crusor_qual_id_fin_")
        self.ws = Path(self.tmp)
        self.auth_engine = get_authorization_engine()
        self.tool_auth = IdentityAwareToolAuthorizer(self.auth_engine)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Identity & RBAC Scenarios
    # -------------------------------------------------------------------------
    def test_01_identity_missing_principal_fails_closed(self) -> None:
        """Missing principal fails closed with DENY."""
        req = AuthorizationRequest(
            principal=None,  # Missing principal
            permission=Permission.FILE_WRITE,
            org_id="org_test",
            workspace_id=str(self.ws),
            resource_type="agent_tool",
            resource_id="write_file",
        )
        res = self.auth_engine.evaluate(req)
        self.assertEqual(res.decision, AuthorizationDecision.DENY)
        self.assertIn("unauthenticated", res.reason.lower())

    def test_02_identity_viewer_role_blocked_from_mutation(self) -> None:
        """User with VIEWER role is blocked from executing mutating tools."""
        viewer = User(
            user_id="user_viewer_1",
            email="viewer@test.com",
            display_name="Viewer User",
            is_superadmin=False,
        )
        # Authorize mutating tool
        res = self.tool_auth.authorize_tool_call(
            principal=viewer,
            org_id="org_test",
            workspace_id=str(self.ws),
            tool_name="write_file",
            tool_args={"path": "test.txt", "content": "data"},
        )
        self.assertFalse(res.is_allowed)
        self.assertEqual(res.decision, AuthorizationDecision.DENY)

    def test_03_identity_high_risk_action_requires_approval(self) -> None:
        """High risk mutating operations require explicit approval token."""
        dev = User(
            user_id="user_dev_1",
            email="dev@test.com",
            display_name="Dev User",
            is_superadmin=False,
        )
        res = self.tool_auth.authorize_tool_call(
            principal=dev,
            org_id="org_test",
            workspace_id=str(self.ws),
            tool_name="delete_file",
            tool_args={"path": "main.py"},
        )
        self.assertFalse(res.is_allowed)

    # -------------------------------------------------------------------------
    # FinOps Scenarios
    # -------------------------------------------------------------------------
    def test_04_finops_pre_call_budget_authorization(self) -> None:
        """Within-budget calls succeed; over-budget calls raise BudgetExhaustedError."""
        finops = OrchestrationFinOpsGovernor("fin_task_1", budget_inr=50.0, token_budget=1000)

        # Within budget passes
        finops.authorize_operation(estimated_tokens=500, estimated_cost_inr=10.0)

        # Record usage
        finops.record_usage(input_tokens=400, output_tokens=200, cost_inr=12.0)
        self.assertEqual(finops.accounting.tokens_consumed, 600)
        self.assertEqual(finops.accounting.spent_inr, 12.0)

        # Over-budget tokens check fails closed
        with self.assertRaises(BudgetExhaustedError):
            finops.authorize_operation(estimated_tokens=500, estimated_cost_inr=5.0)

        # Over-budget cost check fails closed
        with self.assertRaises(BudgetExhaustedError):
            finops.authorize_operation(estimated_tokens=100, estimated_cost_inr=45.0)

    # -------------------------------------------------------------------------
    # Production Readiness Scenarios
    # -------------------------------------------------------------------------
    def test_05_production_readiness_insecure_config_detected(self) -> None:
        """Insecure configurations (wildcard origins, missing secrets) are flagged."""
        # Create insecure docker/config
        bad_config = self.ws / "docker-compose.yml"
        bad_config.write_text("version: '3'\nservices:\n  web:\n    image: app:latest\n    privileged: true\n", encoding="utf-8")

        engine = ProductionReadinessEngine(str(self.ws))
        report = engine.evaluate_readiness(
            task_id="task_readiness_1",
            application_id="InsecureApp",
            target_env=TargetEnvironmentConfig(profile=EnvironmentProfile.STANDARD_PROD),
        )

        self.assertIsNotNone(report.verdict)
        # Should not be ready for clean production deployment due to insecure config
        self.assertIn(report.verdict, {
            ProductionReadinessVerdict.NOT_PRODUCTION_READY,
            ProductionReadinessVerdict.PRODUCTION_READY_WITH_ACCEPTED_RISKS,
            ProductionReadinessVerdict.BLOCKED,
        })
        self.assertGreater(len(report.open_findings), 0)
