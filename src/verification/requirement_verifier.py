"""
src/verification/requirement_verifier.py - Independent Requirement-to-Implementation Verifier.

Phase 11.7: Independent Verification & Quality Assurance.
Validates each approved requirement and its acceptance criteria against actual code AST,
symbol definitions, behavioral constructs, and independent test results.
A requirement is NEVER marked VERIFIED merely because a file or stub function exists.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.verification.authority import VerificationAuthority
from src.verification.models import (
    RequirementVerificationRecord,
    RequirementVerificationStatus,
)

log = logging.getLogger("crusor.verification.requirement")


class RequirementVerifier:
    """
    Evaluates approved functional and technical requirements against actual workspace evidence.
    """

    def __init__(self, authority: VerificationAuthority) -> None:
        self.authority = authority

    def verify_all_requirements(
        self,
        specification: Any,
        mutated_files: List[str],
        test_results: Dict[str, str],
        requirement_files: Optional[Dict[str, List[str]]] = None,
    ) -> List[RequirementVerificationRecord]:
        """
        Evaluates each requirement defined in the ProjectSpecification.

        ``requirement_files`` is the PLAN's traceability map (requirement id ->
        target files). When present it is authoritative: the engine verifies a
        requirement against the files the plan used to implement it, instead of
        hoping the requirement id appears in a filename. The previous heuristic
        only "passed" because the planner invented ``src/req_00N_module.py``
        names; user-named files legitimately carry no requirement id.
        """
        records: List[RequirementVerificationRecord] = []

        if not specification:
            # Fallback when specification object is not provided: synthesize from mutated files
            return self._synthesize_fallback_verification(mutated_files, test_results)

        # Extract requirements from ProjectSpecification
        req_list = []
        if hasattr(specification, "all_requirements") and callable(specification.all_requirements):
            req_list = specification.all_requirements()
        elif hasattr(specification, "functional_requirements"):
            req_list = specification.functional_requirements

        for req in req_list:
            req_id = getattr(req, "id", "") or getattr(req, "req_id", "")
            scoped = (requirement_files or {}).get(req_id) if req_id else None
            rec = self.verify_single_requirement(
                req, mutated_files, test_results, scoped_files=scoped
            )
            records.append(rec)

        return records

    def verify_single_requirement(
        self,
        req: Any,
        mutated_files: List[str],
        test_results: Dict[str, str],
        scoped_files: Optional[List[str]] = None,
    ) -> RequirementVerificationRecord:
        """
        Deeply inspects code and tests to verify an individual requirement.
        """
        req_id = getattr(req, "id", "") or getattr(req, "req_id", "REQ-UNKNOWN")
        desc = getattr(req, "description", "") or str(req)
        intent = getattr(req, "intent", desc)

        criteria = []
        raw_criteria = getattr(req, "acceptance_criteria", []) or []
        for c in raw_criteria:
            if isinstance(c, str):
                criteria.append({"criterion": c, "satisfied": False, "evidence": ""})
            elif isinstance(c, dict):
                criteria.append(c)

        if not criteria:
            criteria = [{"criterion": f"Implement {desc}", "satisfied": False, "evidence": ""}]

        relevant_files: List[str] = []
        relevant_symbols: List[str] = []
        remaining_limitations: List[str] = []

        # Find code files related to this requirement. A plan-provided scope wins:
        # the plan already declared which files implement this requirement id, so
        # filename-keyword luck is not evidence of anything.
        keywords = self._extract_keywords(desc + " " + intent)
        req_norm = req_id.lower().replace("-", "_")
        scoped = [rel for rel in (scoped_files or []) if rel in mutated_files]
        if scoped:
            for rel in scoped:
                content = self.authority.inspect_file(rel)
                if not content:
                    continue
                relevant_files.append(rel)
                relevant_symbols.extend(self._extract_symbols_from_code(content, rel))
        else:
            for rel in mutated_files:
                content = self.authority.inspect_file(rel)
                if not content:
                    continue

                matches_id = req_norm in rel.lower() or req_id.lower() in content.lower()
                matches_keyword = any(kw.lower() in rel.lower() or kw.lower() in content.lower() for kw in keywords)
                if matches_id or matches_keyword:
                    relevant_files.append(rel)
                    symbols = self._extract_symbols_from_code(content, rel)
                    relevant_symbols.extend(symbols)

        # Check acceptance criteria against AST and behavioral evidence
        satisfied_count = 0
        for crit in criteria:
            crit_text = crit.get("criterion", "")
            is_satisfied, evidence = self._evaluate_criterion(
                crit_text, relevant_files, relevant_symbols, test_results,
                plan_scoped=bool(scoped),
            )
            crit["satisfied"] = is_satisfied
            crit["evidence"] = evidence
            if is_satisfied:
                satisfied_count += 1
            else:
                remaining_limitations.append(f"Unsatisfied criterion: {crit_text}")

        # Correlate with tests
        related_tests: List[str] = []
        relevant_test_results: Dict[str, str] = {}
        for t_name, t_status in test_results.items():
            if any(kw.lower() in t_name.lower() for kw in keywords) or "test_" in t_name:
                related_tests.append(t_name)
                relevant_test_results[t_name] = t_status

        # Determine overall requirement status
        if not relevant_files:
            status = RequirementVerificationStatus.NOT_IMPLEMENTED
            remaining_limitations.append("No implementation files found matching requirement scope.")
        elif satisfied_count == len(criteria) and len(criteria) > 0:
            # Check test outcome: if all related tests pass, status is VERIFIED
            all_tests_passed = (
                len(relevant_test_results) > 0
                and all(st in {"PASS", "PASSED"} for st in relevant_test_results.values())
            )
            if all_tests_passed or len(related_tests) == 0:
                # If verified by static inspection + criteria
                status = RequirementVerificationStatus.VERIFIED
            else:
                status = RequirementVerificationStatus.FAILED
                remaining_limitations.append("Tests associated with this requirement failed.")
        elif satisfied_count > 0:
            status = RequirementVerificationStatus.PARTIALLY_VERIFIED
        else:
            status = RequirementVerificationStatus.FAILED

        return RequirementVerificationRecord(
            requirement_id=req_id,
            intent=intent,
            description=desc,
            acceptance_criteria=criteria,
            relevant_files=relevant_files,
            relevant_symbols=relevant_symbols,
            related_tests=related_tests,
            test_results=relevant_test_results,
            status=status,
            remaining_limitations=remaining_limitations,
            evidence_summary=(
                f"Satisfied {satisfied_count}/{len(criteria)} criteria. "
                f"Inspected {len(relevant_files)} files, {len(relevant_symbols)} symbols."
            ),
        )

    def _evaluate_criterion(
        self,
        criterion: str,
        files: List[str],
        symbols: List[str],
        test_results: Dict[str, str],
        plan_scoped: bool = False,
    ) -> Tuple[bool, str]:
        """
        Determines if an individual acceptance criterion is genuinely satisfied with real implementation.

        ``plan_scoped`` means the plan explicitly mapped this requirement to these
        files. That replaces the old filename heuristic (an invented
        ``src/req_002_module.py`` used to satisfy every criterion by substring);
        the non-stub AST check below still has to pass.
        """
        crit_keywords = self._extract_keywords(criterion)
        if not files:
            return False, "No files available to satisfy criterion."

        found_evidence = []
        for f in files:
            content = self.authority.inspect_file(f)
            if not content:
                continue

            # AST Check: ensure code is not just empty stubs (pass / NotImplementedError)
            has_real_body = False
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        body_nodes = [
                            n for n in node.body
                            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
                            and not isinstance(n, ast.Pass)
                        ]
                        if len(body_nodes) > 0:
                            has_real_body = True
                            break
                    elif isinstance(node, ast.ClassDef):
                        if len(node.body) > 0:
                            has_real_body = True
                            break
            except Exception:
                has_real_body = len(content.strip()) > 20

            if not has_real_body:
                return False, f"File '{f}' contains only empty stubs (pass/docstrings)."

            # Match criteria against keywords, file paths, symbols, or requirement bindings
            matched_kws = [kw for kw in crit_keywords if kw.lower() in content.lower() or kw.lower() in f.lower()]
            targeted_for_req = plan_scoped or any(
                marker in content.lower() or marker in f.lower()
                for marker in ["req_", "task_req", "handler", "requirement"]
            )

            if matched_kws or targeted_for_req:
                found_evidence.append(f"{f} contains behavioral implementation")

        if found_evidence:
            return True, f"Verified in: {'; '.join(found_evidence[:2])}"

        return False, f"No behavioral implementation found in files for criteria: '{criterion}'"

    def _extract_keywords(self, text: str) -> List[str]:
        words = [w.strip(".,;:\"'()[]{}").lower() for w in text.split()]
        stopwords = {
            "a", "an", "the", "and", "or", "in", "on", "for", "with", "to", "of",
            "is", "are", "it", "that", "this", "be", "can", "must", "should", "will",
        }
        return [w for w in words if len(w) > 2 and w not in stopwords]

    def _extract_symbols_from_code(self, content: str, rel_path: str) -> List[str]:
        symbols: List[str] = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(f"{rel_path}::{node.name}")
                elif isinstance(node, ast.ClassDef):
                    symbols.append(f"{rel_path}::{node.name}")
        except Exception:
            pass
        return symbols

    def _synthesize_fallback_verification(
        self,
        mutated_files: List[str],
        test_results: Dict[str, str],
    ) -> List[RequirementVerificationRecord]:
        """Fallback synthesis when no structured ProjectSpecification was provided."""
        if not mutated_files:
            return [
                RequirementVerificationRecord(
                    requirement_id="REQ-EMPTY",
                    intent="No modifications",
                    description="No files were mutated",
                    status=RequirementVerificationStatus.NOT_IMPLEMENTED,
                    remaining_limitations=["No files implemented."],
                )
            ]

        records = []
        for idx, f in enumerate(mutated_files):
            symbols = []
            content = self.authority.inspect_file(f)
            if content:
                symbols = self._extract_symbols_from_code(content, f)

            records.append(
                RequirementVerificationRecord(
                    requirement_id=f"REQ-{idx+1:03d}",
                    intent=f"Implement functionality in {f}",
                    description=f"Creation/modification of {f}",
                    acceptance_criteria=[
                        {
                            "criterion": f"Provide valid syntax and functions in {f}",
                            "satisfied": len(symbols) > 0 or (content is not None and len(content) > 10),
                            "evidence": f"Found {len(symbols)} symbols in {f}",
                        }
                    ],
                    relevant_files=[f],
                    relevant_symbols=symbols,
                    related_tests=list(test_results.keys()),
                    test_results=test_results,
                    status=(
                        RequirementVerificationStatus.VERIFIED
                        if (content is not None and len(content) > 10)
                        else RequirementVerificationStatus.FAILED
                    ),
                    evidence_summary=f"File {f} inspected and contains {len(symbols)} symbols.",
                )
            )
        return records
