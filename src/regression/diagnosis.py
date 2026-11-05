"""
src/regression/diagnosis.py - Failure Diagnosis Engine.

Phase 11.5: Regression Prevention & Recovery.
Performs structured root-cause analysis on test and verification failures:
- Parses stack traces, assertion messages, and exception types.
- Traces failure locations back to modified files and symbols.
- Categorizes root cause certainty: CONFIRMED, PROBABLE, POSSIBLE, UNKNOWN.
- Never claims root-cause certainty without concrete evidence.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from src.regression.models import (
    FailureClassification,
    FailureDiagnosis,
    RootCauseCertainty,
    TestCaseResult,
)

log = logging.getLogger("crusor.regression.diagnosis")


class FailureDiagnosisEngine:
    """
    Diagnoses the root cause and origin of test failures.
    """

    def diagnose_failure(
        self,
        test_result: TestCaseResult,
        changed_files: List[str],
        changed_symbols: List[str],
        classification: FailureClassification = FailureClassification.NEW_REGRESSION,
    ) -> FailureDiagnosis:
        """Construct structured failure diagnosis."""
        failure_id = f"FAIL-{uuid.uuid4().hex[:8]}"
        err_msg = test_result.error_message or "Unknown failure"
        stack_trace = test_result.stack_trace or ""

        # Extract exception type
        exc_type = test_result.exception_type
        if not exc_type and err_msg:
            match = re.search(r"([A-Za-z0-9_]+Error|[A-Za-z0-9_]+Exception):", err_msg)
            if match:
                exc_type = match.group(1)

        # Parse expected vs actual from assertion message
        expected_behavior = "Test assertions to succeed"
        actual_behavior = err_msg

        assert_match = re.search(r"AssertionError:\s*(.*)", err_msg)
        if assert_match:
            actual_behavior = assert_match.group(1).strip()
            if "!=" in actual_behavior:
                parts = actual_behavior.split("!=")
                if len(parts) == 2:
                    expected_behavior = f"Expected equality with: {parts[1].strip()}"
                    actual_behavior = f"Received: {parts[0].strip()}"

        # Correlate with changed files and symbols
        associated_files = []
        associated_symbols = []
        evidence_records = []

        all_text = f"{err_msg}\n{stack_trace}"
        for cf in changed_files:
            cf_name = cf.split("/")[-1].split("\\")[-1]
            if cf in all_text or cf_name in all_text:
                associated_files.append(cf)
                evidence_records.append(f"Stack trace directly references changed file '{cf}'")

        for sym in changed_symbols:
            if sym in all_text:
                associated_symbols.append(sym)
                evidence_records.append(f"Failure log directly references changed symbol '{sym}'")

        # Determine certainty
        if associated_symbols or associated_files:
            certainty = RootCauseCertainty.CONFIRMED if associated_symbols else RootCauseCertainty.PROBABLE
            summary = f"Failure directly caused by modification in {', '.join(associated_files or associated_symbols)}"
        elif classification == FailureClassification.ENVIRONMENT_FAILURE:
            certainty = RootCauseCertainty.PROBABLE
            summary = f"Environment misconfiguration or missing dependency: {exc_type or 'Unknown'}"
        else:
            certainty = RootCauseCertainty.POSSIBLE
            summary = f"Indirect failure in test {test_result.test_name}: {err_msg[:120]}"

        return FailureDiagnosis(
            failure_id=failure_id,
            test_id=test_result.test_id,
            classification=classification,
            expected_behavior=expected_behavior,
            actual_behavior=actual_behavior,
            exception_type=exc_type,
            stack_trace=stack_trace,
            root_cause_certainty=certainty,
            root_cause_summary=summary,
            associated_symbols=associated_symbols,
            associated_files=associated_files,
            evidence_records=evidence_records,
        )

