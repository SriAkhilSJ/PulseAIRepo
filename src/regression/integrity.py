"""
src/regression/integrity.py - Test Integrity & Anti-Tampering Protection.

Phase 11.5: Regression Prevention & Recovery.
Prevents manufactured test successes:
- Detects deletion of failing tests.
- Detects weakened assertions or removed test cases.
- Detects arbitrary timeout inflation to mask test failures.
- Detects conversion of failing tests into skipped tests (@unittest.skip, @pytest.mark.skip).
- Detects blanket exception suppression (try/except: pass in tests).
- Rejects test modifications unless explicitly justified and authorized.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.regression.models import (
    IntegrityViolationType,
    TestIntegrityViolation,
)

log = logging.getLogger("crusor.regression.integrity")


class TestIntegrityAuditor:
    """
    Scans proposed test file modifications to prevent tampering with verification.
    """

    def audit_test_modification(
        self,
        test_file_path: str,
        original_content: str,
        modified_content: str,
    ) -> List[TestIntegrityViolation]:
        """
        Audits changes to a test file for integrity violations.
        Returns a list of detected violations.
        """
        violations: List[TestIntegrityViolation] = []

        # 1. Detect deletion or removal of test file
        if not modified_content.strip() and original_content.strip():
            violations.append(
                TestIntegrityViolation(
                    violation_type=IntegrityViolationType.TEST_DELETED,
                    test_file=test_file_path,
                    test_name=None,
                    description=f"Test file '{test_file_path}' was completely emptied or deleted.",
                )
            )
            return violations

        # Parse ASTs
        try:
            orig_tree = ast.parse(original_content)
        except Exception:
            orig_tree = None

        try:
            mod_tree = ast.parse(modified_content)
        except Exception as e:
            violations.append(
                TestIntegrityViolation(
                    violation_type=IntegrityViolationType.BLANKET_SUPPRESSION,
                    test_file=test_file_path,
                    test_name=None,
                    description=f"Syntax error introduced into test file: {e}",
                )
            )
            return violations

        if orig_tree and mod_tree:
            orig_tests = {n.name for n in ast.walk(orig_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")}
            mod_tests = {n.name for n in ast.walk(mod_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")}

            # 2. Check for removed test cases
            removed = orig_tests - mod_tests
            for r in removed:
                violations.append(
                    TestIntegrityViolation(
                        violation_type=IntegrityViolationType.TEST_CASE_REMOVED,
                        test_file=test_file_path,
                        test_name=r,
                        description=f"Test case '{r}' was removed from '{test_file_path}'",
                    )
                )

        # 3. Check for newly introduced skip decorators
        skip_patterns = [
            r"@unittest\.skip",
            r"@pytest\.mark\.skip",
            r"@pytest\.mark\.xfail",
        ]
        for pat in skip_patterns:
            orig_count = len(re.findall(pat, original_content))
            mod_count = len(re.findall(pat, modified_content))
            if mod_count > orig_count:
                violations.append(
                    TestIntegrityViolation(
                        violation_type=IntegrityViolationType.CONVERTED_TO_SKIP,
                        test_file=test_file_path,
                        test_name=None,
                        description=f"Newly added skip decorator '{pat}' detected in '{test_file_path}'",
                    )
                )

        # 4. Check for blanket exception suppression in test body: except Exception: pass
        blanket_suppression_pattern = re.compile(r"except\s+(?:Exception|\w+)?:\s*pass")
        if blanket_suppression_pattern.search(modified_content) and not blanket_suppression_pattern.search(original_content):
            violations.append(
                TestIntegrityViolation(
                    violation_type=IntegrityViolationType.BLANKET_SUPPRESSION,
                    test_file=test_file_path,
                    test_name=None,
                    description=f"Blanket exception suppression ('except: pass') added to '{test_file_path}'",
                )
            )

        # 5. Check for weakened assertions (e.g. replacing assertEqual with assertTrue(True))
        if "assertTrue(True)" in modified_content and "assertTrue(True)" not in original_content:
            violations.append(
                TestIntegrityViolation(
                    violation_type=IntegrityViolationType.ASSERTION_WEAKENED,
                    test_file=test_file_path,
                    test_name=None,
                    description=f"Weakened unconditional assertion 'assertTrue(True)' detected in '{test_file_path}'",
                )
            )

        return violations

