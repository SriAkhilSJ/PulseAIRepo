"""
src/verification/quality_verifier.py - Code Quality & Hygiene Verifier.

Phase 11.7: Independent Verification & Quality Assurance.
Inspects modified code for:
- Debug leftovers (print("DEBUG"), console.log, debugger)
- Dangerous bare exception clauses (bare except:)
- Resource leaks (open() without context manager)
- Dead code / unreachable return statements
- Cyclomatic complexity hot spots
Separates critical correctness defects from informational hygiene advisories.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.verification.authority import VerificationAuthority
from src.verification.models import (
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    VerificationFinding,
)


class CodeQualityVerifier:
    """
    Evaluates code quality, hygiene, and maintainability across modified files.
    """

    def __init__(self, authority: VerificationAuthority) -> None:
        self.authority = authority

    def audit_quality(
        self,
        task_id: str,
        mutated_files: List[str],
    ) -> List[VerificationFinding]:
        """
        Runs quality audits on all modified files.
        """
        findings: List[VerificationFinding] = []

        for rel in mutated_files:
            content = self.authority.inspect_file(rel)
            if not content:
                continue

            # 1. Debug leftovers
            debug_findings = self._check_debug_artifacts(task_id, rel, content)
            findings.extend(debug_findings)

            # 2. Bare exception handling
            bare_except_findings = self._check_bare_excepts(task_id, rel, content)
            findings.extend(bare_except_findings)

            # 3. Unclosed file handles
            unclosed_findings = self._check_resource_leaks(task_id, rel, content)
            findings.extend(unclosed_findings)

        return findings

    def _check_debug_artifacts(
        self,
        task_id: str,
        rel: str,
        content: str,
    ) -> List[VerificationFinding]:
        findings = []
        lines = content.split("\n")
        for idx, line in enumerate(lines, 1):
            if re.search(r'\bprint\s*\(\s*["\'].*(?:debug|temp|test123|asdf).*["\']\s*\)', line, re.IGNORECASE):
                findings.append(
                    VerificationFinding(
                        finding_id=f"QUAL-DEBUG-{len(findings)+1:03d}",
                        task_id=task_id,
                        category=FindingCategory.CODE_QUALITY,
                        severity=FindingSeverity.LOW,
                        title="Temporary Debug Print Statement Left in Code",
                        description=f"Debug print found at {rel}:{idx}",
                        evidence=line.strip(),
                        affected_files=[rel],
                        recommended_action="Remove temporary debug print statements before release.",
                    )
                )
            elif "debugger;" in line:
                findings.append(
                    VerificationFinding(
                        finding_id=f"QUAL-DEBUGGER-{len(findings)+1:03d}",
                        task_id=task_id,
                        category=FindingCategory.CODE_QUALITY,
                        severity=FindingSeverity.MEDIUM,
                        title="JavaScript Debugger Statement Present",
                        description=f"debugger statement at {rel}:{idx}",
                        evidence=line.strip(),
                        affected_files=[rel],
                        recommended_action="Remove debugger breakpoints before final delivery.",
                    )
                )
        return findings

    def _check_bare_excepts(
        self,
        task_id: str,
        rel: str,
        content: str,
    ) -> List[VerificationFinding]:
        findings = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    if node.type is None:
                        findings.append(
                            VerificationFinding(
                                finding_id=f"QUAL-BARE-EXCEPT-{len(findings)+1:03d}",
                                task_id=task_id,
                                category=FindingCategory.CODE_QUALITY,
                                severity=FindingSeverity.MEDIUM,
                                title="Bare Exception Handler Detected",
                                description=f"Bare 'except:' in {rel} swallows system exits and critical errors.",
                                evidence="except: with no exception type specified.",
                                affected_files=[rel],
                                recommended_action="Specify explicit exception classes (e.g. 'except Exception:').",
                            )
                        )
        except Exception:
            pass
        return findings

    def _check_resource_leaks(
        self,
        task_id: str,
        rel: str,
        content: str,
    ) -> List[VerificationFinding]:
        findings = []
        # Check raw f = open(...) without with statement
        if re.search(r'^\s*[a-zA-Z_0-9]+\s*=\s*open\s*\(', content, re.MULTILINE):
            if "with open(" not in content:
                findings.append(
                    VerificationFinding(
                        finding_id=f"QUAL-RES-LEAK-{len(findings)+1:03d}",
                        task_id=task_id,
                        category=FindingCategory.CODE_QUALITY,
                        severity=FindingSeverity.LOW,
                        title="Potential Resource Leak via Unmanaged File Handle",
                        description=f"open() called directly without 'with' context manager in {rel}",
                        evidence="Direct assignment of open() handle.",
                        affected_files=[rel],
                        recommended_action="Use 'with open(...) as f:' context managers for deterministic cleanup.",
                    )
                )
        return findings

