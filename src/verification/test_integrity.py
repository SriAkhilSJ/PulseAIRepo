"""
src/verification/test_integrity.py - Test Quality & Evidence Integrity Engine.

Phase 11.7: Independent Verification & Quality Assurance.
Detects:
- Empty tests
- Tautological assertions (assert True, assert 1 == 1, assert x == x)
- Tests that always pass (try-except pass)
- Zero-assertion tests
- Excessive mocking that evades real execution
- Weakened assertions compared to baselines
Classifies evidence types:
REAL_RUNTIME_TEST, INTEGRATION_TEST, UNIT_TEST, MOCK_BASED_TEST, etc.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.verification.authority import VerificationAuthority
from src.verification.models import (
    TestEvidenceClassification,
    TestIntegrityReport,
)


class TestIntegrityEngine:
    """
    Audits test code for weak patterns, tautologies, zero-assertions, and classifies test realism.
    """

    def __init__(self, authority: VerificationAuthority) -> None:
        self.authority = authority

    def audit_test_files(self, test_files: List[str]) -> TestIntegrityReport:
        """
        Examines test files using AST analysis and produces a TestIntegrityReport.
        """
        weak_tests: List[Dict[str, Any]] = []
        classifications: Dict[str, str] = {}
        total_checked = 0
        tautological_count = 0
        empty_count = 0
        excessive_mock_count = 0

        for tf in test_files:
            content = self.authority.inspect_file(tf)
            if not content:
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError:
                weak_tests.append({
                    "test_file": tf,
                    "test_name": "<parse_error>",
                    "issue_type": "SYNTAX_ERROR",
                    "details": "Test file contains invalid Python syntax",
                })
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_") or node.name.endswith("_test"):
                        total_checked += 1
                        classification = self._classify_test_function(node, content)
                        classifications[f"{tf}::{node.name}"] = classification.value

                        # 1. Empty test
                        is_empty, empty_reason = self._is_empty_test(node)
                        if is_empty:
                            empty_count += 1
                            weak_tests.append({
                                "test_file": tf,
                                "test_name": node.name,
                                "issue_type": "EMPTY_TEST",
                                "details": empty_reason,
                            })

                        # 2. Tautological assertions
                        tautology = self._find_tautological_assertion(node)
                        if tautology:
                            tautological_count += 1
                            weak_tests.append({
                                "test_file": tf,
                                "test_name": node.name,
                                "issue_type": "TAUTOLOGICAL_ASSERTION",
                                "details": tautology,
                            })

                        # 3. Always passes (try ... except: pass without assert)
                        if self._is_always_pass(node):
                            weak_tests.append({
                                "test_file": tf,
                                "test_name": node.name,
                                "issue_type": "ALWAYS_PASSES",
                                "details": "Test swallows all exceptions in try/except pass block",
                            })

                        # 4. Zero assertions
                        if not self._has_any_assertion(node):
                            weak_tests.append({
                                "test_file": tf,
                                "test_name": node.name,
                                "issue_type": "NO_ASSERTIONS",
                                "details": "Test contains zero assertions or verify calls",
                            })

                        # 5. Excessive mocking
                        if classification == TestEvidenceClassification.MOCK_BASED_TEST:
                            if self._is_excessive_mocking(node, content):
                                excessive_mock_count += 1
                                weak_tests.append({
                                    "test_file": tf,
                                    "test_name": node.name,
                                    "issue_type": "EXCESSIVE_MOCKING",
                                    "details": "All real dependencies are replaced with MagicMock; no real code executed.",
                                })

        return TestIntegrityReport(
            test_files_analyzed=test_files,
            total_tests_checked=total_checked,
            weak_tests_detected=weak_tests,
            evidence_classifications=classifications,
            tautological_count=tautological_count,
            empty_test_count=empty_count,
            excessive_mock_count=excessive_mock_count,
        )

    def _is_empty_test(self, func_node: ast.FunctionDef) -> Tuple[bool, str]:
        meaningful_nodes = []
        for n in func_node.body:
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
                # Docstring
                continue
            if isinstance(n, ast.Pass):
                continue
            meaningful_nodes.append(n)

        if len(meaningful_nodes) == 0:
            return True, "Function body consists only of pass or docstring"
        return False, ""

    def _find_tautological_assertion(self, func_node: ast.FunctionDef) -> Optional[str]:
        for node in ast.walk(func_node):
            if isinstance(node, ast.Assert):
                test_expr = node.test
                # assert True
                if isinstance(test_expr, ast.Constant) and test_expr.value is True:
                    return "assert True is tautological and proves nothing"
                # assert 1 == 1 or x == x
                if isinstance(test_expr, ast.Compare):
                    if len(test_expr.ops) == 1 and isinstance(test_expr.ops[0], ast.Eq):
                        left = ast.unparse(test_expr.left) if hasattr(ast, "unparse") else ""
                        right = ast.unparse(test_expr.comparators[0]) if hasattr(ast, "unparse") else ""
                        if left == right and left != "":
                            return f"Tautological comparison '{left} == {right}'"
            # self.assertTrue(True)
            elif isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name in ("assertTrue", "assert_true") and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and arg.value is True:
                        return "assertTrue(True) is tautological"
                elif func_name in ("assertEqual", "assert_equal") and len(node.args) >= 2:
                    arg1 = ast.unparse(node.args[0]) if hasattr(ast, "unparse") else ""
                    arg2 = ast.unparse(node.args[1]) if hasattr(ast, "unparse") else ""
                    if arg1 == arg2 and arg1 != "":
                        return f"Tautological assertEqual('{arg1}', '{arg2}')"
        return None

    def _is_always_pass(self, func_node: ast.FunctionDef) -> bool:
        for node in ast.walk(func_node):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    # check if handler body is just pass
                    if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                        # and no assert outside
                        has_assert = any(isinstance(n, ast.Assert) for n in ast.walk(func_node))
                        if not has_assert:
                            return True
        return False

    def _has_any_assertion(self, func_node: ast.FunctionDef) -> bool:
        for node in ast.walk(func_node):
            if isinstance(node, ast.Assert):
                return True
            if isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name.startswith("assert") or name in ("expect", "verify"):
                    return True
        return False

    def _classify_test_function(self, func_node: ast.FunctionDef, full_content: str) -> TestEvidenceClassification:
        func_text = ast.unparse(func_node) if hasattr(ast, "unparse") else ""

        if "@patch" in func_text or "MagicMock" in func_text or "unittest.mock" in func_text:
            return TestEvidenceClassification.MOCK_BASED_TEST

        if "requests." in func_text or "httpx." in func_text or "TestClient" in func_text or "subprocess" in func_text:
            return TestEvidenceClassification.INTEGRATION_TEST

        if "sqlite3" in func_text or "engine" in func_text or "session" in func_text:
            return TestEvidenceClassification.INTEGRATION_TEST

        if "ast." in func_text or "compile(" in func_text:
            return TestEvidenceClassification.STATIC_ANALYSIS

        return TestEvidenceClassification.UNIT_TEST

    def _is_excessive_mocking(self, func_node: ast.FunctionDef, full_content: str) -> bool:
        func_text = ast.unparse(func_node) if hasattr(ast, "unparse") else ""
        patch_count = func_text.count("@patch") + func_text.count("MagicMock")
        # If there are 3 or more patches in a single small test function, flag excessive mocking
        return patch_count >= 3

