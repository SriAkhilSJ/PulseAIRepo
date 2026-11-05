"""
src/verification/__init__.py - Independent Verification & Quality Assurance Package.

Phase 11.7: Independent Verification & Quality Assurance.
"""

from __future__ import annotations

from src.verification.authority import (
    VerificationAuthority,
    VerificationAuthorityViolationError,
)
from src.verification.completion_gate import IndependentCompletionGate
from src.verification.defect_manager import VerificationFindingManager
from src.verification.engine import IndependentVerificationEngine
from src.verification.invalidation import VerificationInvalidationManager
from src.verification.models import (
    ApplicationRuntimeResult,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    RequirementVerificationRecord,
    RequirementVerificationStatus,
    RuntimeStartupResult,
    TestEvidenceClassification,
    TestIntegrityReport,
    VerificationFinding,
    VerificationReport,
    VerificationVerdict,
    WorkflowVerificationRecord,
)
from src.verification.quality_verifier import CodeQualityVerifier
from src.verification.requirement_verifier import RequirementVerifier
from src.verification.runtime_verifier import ApplicationRuntimeVerifier
from src.verification.security_verifier import IndependentSecurityVerifier
from src.verification.test_integrity import TestIntegrityEngine
from src.verification.test_selector import IndependentTestSelector
from src.verification.visibility import DesktopVerificationVisibility

__all__ = [
    "IndependentVerificationEngine",
    "VerificationAuthority",
    "VerificationAuthorityViolationError",
    "IndependentCompletionGate",
    "VerificationFindingManager",
    "VerificationInvalidationManager",
    "DesktopVerificationVisibility",
    "RequirementVerifier",
    "IndependentTestSelector",
    "TestIntegrityEngine",
    "ApplicationRuntimeVerifier",
    "WorkflowVerifier",
    "IndependentSecurityVerifier",
    "CodeQualityVerifier",
    "VerificationVerdict",
    "RequirementVerificationStatus",
    "TestEvidenceClassification",
    "FindingCategory",
    "FindingSeverity",
    "FindingStatus",
    "RuntimeStartupResult",
    "VerificationFinding",
    "RequirementVerificationRecord",
    "ApplicationRuntimeResult",
    "WorkflowVerificationRecord",
    "TestIntegrityReport",
    "VerificationReport",
]

