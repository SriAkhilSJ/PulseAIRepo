"""
src/regression/__init__.py - Regression Prevention & Recovery Subsystem Exports.

Phase 11.5: Regression Prevention & Recovery.
"""

from src.regression.baseline import TestBaselineManager
from src.regression.detector import PostChangeRegressionDetector
from src.regression.diagnosis import FailureDiagnosisEngine
from src.regression.engine import RegressionPreventionEngine
from src.regression.fix_loop import ControlledRegressionFixLoop
from src.regression.flaky import FlakyTestDetector
from src.regression.integrity import TestIntegrityAuditor
from src.regression.models import (
    FailureClassification,
    FailureDiagnosis,
    FlakyTestRecord,
    IntegrityViolationType,
    RecoveryActionType,
    RecoveryEvaluation,
    RegressionReport,
    RegressionStatus,
    RootCauseCertainty,
    TestBaseline,
    TestCaseResult,
    TestIntegrityViolation,
    TestPriority,
    TestStatus,
)
from src.regression.performance_gate import PerformanceRegressionAuditor
from src.regression.persistence import RegressionPersistence
from src.regression.recovery import SafeRecoveryCoordinator
from src.regression.security_gate import SecurityRegressionGate
from src.regression.selector import RiskBasedTestSelector

__all__ = [
    "TestStatus",
    "FailureClassification",
    "RootCauseCertainty",
    "TestPriority",
    "RegressionStatus",
    "RecoveryActionType",
    "IntegrityViolationType",
    "TestCaseResult",
    "TestBaseline",
    "FailureDiagnosis",
    "FlakyTestRecord",
    "TestIntegrityViolation",
    "RecoveryEvaluation",
    "RegressionReport",
    "TestBaselineManager",
    "RiskBasedTestSelector",
    "PostChangeRegressionDetector",
    "FailureDiagnosisEngine",
    "FlakyTestDetector",
    "ControlledRegressionFixLoop",
    "TestIntegrityAuditor",
    "SafeRecoveryCoordinator",
    "SecurityRegressionGate",
    "PerformanceRegressionAuditor",
    "RegressionPersistence",
    "RegressionPreventionEngine",
]

