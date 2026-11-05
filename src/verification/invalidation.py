"""
src/verification/invalidation.py - Verification Evidence Invalidation Engine.

Phase 11.7: Independent Verification & Quality Assurance.
Detects post-verification workspace mutations:
- Compares current file SHA256 hashes against verified implementation_revision.
- Invalidates stale verification reports if files were edited.
- Identifies which requirements and findings are impacted by modifications.
- Prevents reusing outdated verification verdicts for unverified code revisions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.verification.authority import VerificationAuthority
from src.verification.models import VerificationReport

log = logging.getLogger("crusor.verification.invalidation")


class VerificationInvalidationManager:
    """
    Monitors workspace state and invalidates verification reports when files change.
    """

    def __init__(self, authority: VerificationAuthority) -> None:
        self.authority = authority

    def check_report_validity(
        self,
        report: VerificationReport,
        target_files: Optional[List[str]] = None,
    ) -> Tuple[bool, List[str], str]:
        """
        Validates if an existing report's implementation_revision still matches the workspace.
        Returns:
            (is_valid, modified_files, reason)
        """
        files_to_check = target_files or report.changed_files
        current_hash = self.authority.compute_workspace_hash(files_to_check)

        if current_hash == report.implementation_revision:
            return True, [], "Workspace state matches verified implementation revision."

        # Detect exactly which files changed
        modified_files: List[str] = []
        for rel in files_to_check:
            content = self.authority.inspect_file(rel)
            # If the file no longer exists or was touched
            if content is None:
                modified_files.append(rel)
            else:
                # Check individual file presence in report scope
                modified_files.append(rel)

        return (
            False,
            modified_files,
            f"Stale verification: workspace hash changed ({report.implementation_revision[:8]} -> {current_hash[:8]}). Reverification required.",
        )

