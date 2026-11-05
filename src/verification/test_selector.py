"""
src/verification/test_selector.py - Independent Test Selection Engine.

Phase 11.7: Independent Verification & Quality Assurance.
Determines which tests must execute based on code changes, impact analysis, security surface,
and requirement scope, independently of what the implementation agent selected.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.verification.authority import VerificationAuthority


class IndependentTestSelector:
    """
    Independently determines which tests must be run to verify changes.
    Does NOT trust the implementation agent's chosen test subset.
    """

    def __init__(self, authority: VerificationAuthority) -> None:
        self.authority = authority

    def select_tests(
        self,
        mutated_files: List[str],
        impact_report: Optional[Any] = None,
        regression_baseline: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Calculates the required test plan and identifies unexecutable checks.
        """
        all_discovered_tests = self._discover_all_test_files()
        selected_tests: List[str] = []
        selection_reasons: Dict[str, List[str]] = {}
        unexecutable_checks: List[str] = []

        mutated_set = set(mutated_files)

        # 1. Direct unit tests for changed files
        for test_file in all_discovered_tests:
            tf_lower = test_file.lower()
            for mf in mutated_set:
                mf_base = Path(mf).stem.lower()
                if mf_base in tf_lower or tf_lower.endswith(f"test_{mf_base}.py"):
                    if test_file not in selected_tests:
                        selected_tests.append(test_file)
                        selection_reasons.setdefault(test_file, []).append(
                            f"Direct unit test for modified file '{mf}'"
                        )

        # 2. Impact-based tests from Phase 11.4 ChangeImpactReport
        if impact_report:
            if hasattr(impact_report, "relevant_tests"):
                for t in impact_report.relevant_tests:
                    t_name = t.get("test_name", "") if isinstance(t, dict) else str(t)
                    if t_name and t_name not in selected_tests:
                        selected_tests.append(t_name)
                        selection_reasons.setdefault(t_name, []).append("Impact analysis dependency")

        # 3. Security checks for security-sensitive modifications
        is_security_sensitive = any(
            any(k in f.lower() for k in ["auth", "security", "token", "session", "permission", "rbac", "secret"])
            for f in mutated_set
        )
        if is_security_sensitive:
            for tf in all_discovered_tests:
                if "security" in tf.lower() or "auth" in tf.lower():
                    if tf not in selected_tests:
                        selected_tests.append(tf)
                        selection_reasons.setdefault(tf, []).append("Security-sensitive modification requires security test")

        # 4. If no specific tests match, fallback to general milestone regression suites
        if not selected_tests:
            for tf in all_discovered_tests:
                if "regression" in tf.lower() or "test_phase" in tf.lower():
                    selected_tests.append(tf)
                    selection_reasons.setdefault(tf, []).append("Default milestone regression coverage")
                    if len(selected_tests) >= 3:
                        break

        # 5. Identify unexecutable tests (e.g., live cloud, external hardware, production DB)
        for mf in mutated_set:
            if "stripe" in mf.lower() or "payment" in mf.lower():
                unexecutable_checks.append("Live payment gateway end-to-end sandbox verification (external credentials unavailable)")
            if "cloud" in mf.lower() or "s3" in mf.lower() or "aws" in mf.lower():
                unexecutable_checks.append("Live AWS S3 integration test (cloud credentials not provided)")

        return {
            "selected_tests": selected_tests,
            "selection_reasons": selection_reasons,
            "unexecutable_checks": unexecutable_checks,
            "total_available_tests": len(all_discovered_tests),
        }

    def _discover_all_test_files(self) -> List[str]:
        """Discovers all test files present in the workspace."""
        test_files: List[str] = []
        for root, _, files in os.walk(self.authority.workspace_root):
            for f in files:
                if f.startswith("test_") and f.endswith(".py"):
                    full = Path(root) / f
                    try:
                        rel = full.relative_to(self.authority.workspace_root).as_posix()
                        if not rel.startswith(".crusorai") and not rel.startswith(".git"):
                            test_files.append(rel)
                    except Exception:
                        pass
        return sorted(test_files)

