"""
finops_integration.py -- Tenancy & RBAC Integration with Phase 9.7 FinOps.

Phase 10.0: Enterprise Identity, Authentication & Role-Based Access Control.
Provides:
- Strict cross-organization financial isolation (preventing unauthorized spend visibility).
- Role-based enforcement over budget policies, spending limits, and virtual credits.
- Verification that credit transactions and budget holds belong strictly to the authorized tenant.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.finops.credits import CreditAccountingEngine, CreditTransaction, get_credit_engine
from src.identity.authorization import (
    AuthorizationEngine,
    AuthorizationRequest,
    AuthorizationResult,
    get_authorization_engine,
)
from src.identity.models import Permission, RoleTemplate, User

log = logging.getLogger("crusorai.identity.finops_integration")


class FinOpsAccessDeniedError(Exception):
    """Raised when an unauthorized user attempts to access or modify financial resources."""
    pass


class CrossTenantFinancialViolationError(FinOpsAccessDeniedError):
    """Raised when an operation attempts cross-organization financial mutation or access."""
    pass


class IdentityAwareFinOpsGovernor:
    """
    Enforces identity and RBAC boundaries over FinOps reporting, budgets, and credits.
    """

    def __init__(
        self,
        auth_engine: Optional[AuthorizationEngine] = None,
        credit_engine: Optional[CreditAccountingEngine] = None,
    ) -> None:
        self.auth_engine = auth_engine or get_authorization_engine()
        self.credit_engine = credit_engine or get_credit_engine()

    def authorize_view_reports(
        self,
        principal: User,
        target_org_id: str,
    ) -> AuthorizationResult:
        """Authorize viewing FinOps cost attribution and spend reports."""
        req = AuthorizationRequest(
            principal=principal,
            permission=Permission.FINOPS_VIEW_REPORTS,
            org_id=target_org_id,
            resource_type="finops_report",
            resource_id=target_org_id,
        )
        res = self.auth_engine.evaluate(req)
        if not res.is_allowed:
            raise FinOpsAccessDeniedError(f"Access to financial reports denied: {res.reason}")
        return res

    def authorize_manage_budgets(
        self,
        principal: User,
        target_org_id: str,
    ) -> AuthorizationResult:
        """Authorize configuring organizational budgets and spending limits."""
        req = AuthorizationRequest(
            principal=principal,
            permission=Permission.FINOPS_MANAGE_BUDGETS,
            org_id=target_org_id,
            resource_type="budget_policy",
            resource_id=target_org_id,
        )
        res = self.auth_engine.evaluate(req)
        if not res.is_allowed:
            raise FinOpsAccessDeniedError(f"Budget management denied: {res.reason}")
        return res

    def authorize_credit_operation(
        self,
        principal: User,
        target_org_id: str,
        operation_type: str,  # "grant", "debit", "refund"
        amount_diamonds: Decimal,
        actor_org_id: Optional[str] = None,
    ) -> AuthorizationResult:
        """
        Authorize virtual credit operations.
        Guards against cross-organization credit manipulation and unauthorized grants.
        """
        # Cross-tenant manipulation check
        if actor_org_id and actor_org_id != target_org_id and not principal.is_superadmin:
            raise CrossTenantFinancialViolationError(
                f"Cross-organization credit manipulation blocked: actor org {actor_org_id} "
                f"cannot modify credits for target org {target_org_id}"
            )

        if operation_type == "grant":
            permission = Permission.FINOPS_MANAGE_CREDITS
        else:
            # Usage debits are part of tool/agent execution
            permission = Permission.TOOL_EXECUTE

        req = AuthorizationRequest(
            principal=principal,
            permission=permission,
            org_id=target_org_id,
            resource_type="virtual_credits",
            resource_id=target_org_id,
            metadata={"amount": str(amount_diamonds), "op": operation_type},
        )
        res = self.auth_engine.evaluate(req)
        if not res.is_allowed:
            raise FinOpsAccessDeniedError(f"Credit operation '{operation_type}' denied: {res.reason}")
        return res


_GLOBAL_FINOPS_GOVERNOR: Optional[IdentityAwareFinOpsGovernor] = None

def get_finops_governor() -> IdentityAwareFinOpsGovernor:
    global _GLOBAL_FINOPS_GOVERNOR
    if _GLOBAL_FINOPS_GOVERNOR is None:
        _GLOBAL_FINOPS_GOVERNOR = IdentityAwareFinOpsGovernor()
    return _GLOBAL_FINOPS_GOVERNOR

