"""
src/regression/security_gate.py - Security Regression Completion Gate.

Phase 11.5: Regression Prevention & Recovery.
Enforces security completion gates:
- Audits test failures against security-critical subsystems:
  * Authentication and session management
  * Role-Based Access Control (RBAC)
  * Tenant and workspace isolation
  * Execution sandboxing and AppContainer boundaries
  * Upstream Invariant 7 selective manifest integrity
- Unconditionally blocks completion if a security regression is detected.
- Never allows passing functional tests to compensate for a security failure.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.regression.models import (
    RegressionStatus,
    TestCaseResult,
    TestStatus,
)

log = logging.getLogger("crusor.regression.security_gate")

SECURITY_KEYWORDS = frozenset({
    "auth", "login", "password", "jwt", "session", "rbac", "permission",
    "tenant", "isolation", "sandbox", "appcontainer", "dacl", "secret", "invariant_7",
})


class SecurityRegressionGate:
    """
    Enforces zero-tolerance completion policy for security-sensitive regressions.
    """

    def evaluate_security_gates(
        self,
        failures: List[TestCaseResult],
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Audits test failures for security violations.
        Returns:
            (gate_passed, security_findings)
        """
        security_findings: List[Dict[str, Any]] = []
        gate_passed = True

        for fail in failures:
            test_text = f"{fail.test_id} {fail.test_name} {fail.error_message or ''}".lower()
            for kw in SECURITY_KEYWORDS:
                if kw in test_text:
                    gate_passed = False
                    security_findings.append({
                        "test_id": fail.test_id,
                        "test_name": fail.test_name,
                        "security_domain": kw,
                        "severity": "CRITICAL",
                        "error": fail.error_message,
                        "gate_effect": "BLOCKS_COMPLETION",
                    })
                    break

        return gate_passed, security_findings

