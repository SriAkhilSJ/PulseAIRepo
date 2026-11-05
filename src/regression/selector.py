"""
src/regression/selector.py - Risk-Based Test Selection Strategy.

Phase 11.5: Regression Prevention & Recovery.
Selects and prioritizes test execution scope using Phase 11.4 Change Impact Analysis:
- P0: Direct validation (modified code and target bug)
- P1: Dependent functionality (callers, related modules)
- P2: Contract validation (API contracts, database, external interfaces)
- P3: Broader regression validation (subsystem and repository regression suites)
- P4: Extended validation (long-running, platform-specific suites)
Explains rationale for test inclusion and exclusion.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.regression.models import TestPriority

log = logging.getLogger("crusor.regression.selector")


class RiskBasedTestSelector:
    """
    Selects and prioritizes tests based on change impact and risk.
    """

    def select_test_scope(
        self,
        change_impact_report: Optional[Any],
        all_discovered_tests: List[str],
        risk_level: str = "MEDIUM",
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Determines included and excluded tests with explicit rationales.
        Returns:
            (selected_tests, excluded_tests)
        """
        selected: List[Dict[str, Any]] = []
        excluded: List[Dict[str, Any]] = []
        selected_paths: Set[str] = set()

        impact_tests = getattr(change_impact_report, "relevant_tests", []) if change_impact_report else []
        for t in impact_tests:
            path = t.get("file_path") or t.get("test_name")
            if path and path not in selected_paths:
                selected_paths.add(path)
                selected.append({
                    "test_id": t.get("test_id", path),
                    "test_name": t.get("test_name", path),
                    "file_path": path,
                    "priority": t.get("priority", "P0"),
                    "rationale": t.get("rationale", "Selected directly by Change Impact Analysis"),
                })

        # If high risk or critical, include broader integration and regression suites (P2, P3)
        if risk_level in ("HIGH", "CRITICAL"):
            for t in all_discovered_tests:
                if t not in selected_paths:
                    if any(k in t.lower() for k in ["regression", "security", "integration", "contract"]):
                        selected_paths.add(t)
                        selected.append({
                            "test_id": t,
                            "test_name": t.split("/")[-1],
                            "file_path": t,
                            "priority": "P2" if "contract" in t.lower() else "P3",
                            "rationale": f"High/Critical risk change requires broad {risk_level} verification",
                        })

        # Classify remaining tests as excluded with clear reasons
        for t in all_discovered_tests:
            if t not in selected_paths:
                excluded.append({
                    "test_id": t,
                    "test_name": t.split("/")[-1],
                    "file_path": t,
                    "priority": "P4",
                    "exclusion_reason": "Outside immediate change blast radius; deferred to full system milestone regression",
                })

        # If no tests were selected at all (e.g. new file), select matching or default tests
        if not selected and all_discovered_tests:
            first_test = all_discovered_tests[0]
            selected.append({
                "test_id": first_test,
                "test_name": first_test.split("/")[-1],
                "file_path": first_test,
                "priority": "P0",
                "rationale": "Default baseline verification suite",
            })
            excluded = [e for e in excluded if e["file_path"] != first_test]

        return selected, excluded

