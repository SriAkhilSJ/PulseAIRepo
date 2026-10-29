"""Workspace Revision and Invalidation Ledger.

Implements Decision B of CrusorAI 2.0 Architecture:
1. Monotonically increasing workspace revision counter.
2. Invalidation ledger tracking file writes, edits, and terminal mutations.
3. Marking verification receipts as STALE if code is mutated after verification.
4. Strict exemption policy for pure markdown/rst documentation (.md, .markdown, .rst) only.
   (Files like .txt, requirements.txt, or data files strictly trigger invalidation).
5. Terminal command mutation detection (redirects, installs, removals).
"""
from __future__ import annotations

import fnmatch
import re
import time
from pathlib import Path
from typing import Any, Literal
from typing_extensions import TypedDict


# Pure documentation extensions only (never .txt, .pdf, or config files)
DOC_EXTENSIONS = frozenset({
    ".md", ".markdown", ".rst"
})

MUTATION_COMMAND_PATTERNS = (
    r">", r">>", r"\btouch\b", r"\bmkdir\b", r"\brm\b", r"\bdel\b",
    r"\bmv\b", r"\bmove\b", r"\bcp\b", r"\bcopy\b", r"\bsed\b",
    r"\bnpm install\b", r"\bpip install\b", r"\bcargo add\b",
    r"\bpython -m pip\b", r"\bgit checkout\b", r"\bgit pull\b",
    r"\bcreate\b", r"\bgenerate\b", r"\bbuild\b"
)


class MutationRecord(TypedDict):
    revision: int
    path: str
    tool: str
    is_doc_only: bool
    timestamp: float


class VerificationReceipt(TypedDict):
    check_id: str
    kind: str
    passed: bool
    verified_at_revision: int
    scope_patterns: list[str]
    timestamp: float
    details: dict[str, Any]


class WorkspaceController:
    """Manages workspace revisions, mutation ledger, and receipt invalidation."""

    def __init__(self, initial_revision: int = 0) -> None:
        self.revision = initial_revision
        self.last_verified_revision: int | None = None
        self.mutation_ledger: list[MutationRecord] = []
        self.receipts: dict[str, VerificationReceipt] = {}

    def is_doc_path(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in DOC_EXTENSIONS

    def record_mutation(self, path: str, tool: str) -> int:
        """Increment revision and record mutation in the ledger."""
        self.revision += 1
        is_doc = self.is_doc_path(path)
        record: MutationRecord = {
            "revision": self.revision,
            "path": path,
            "tool": tool,
            "is_doc_only": is_doc,
            "timestamp": time.time(),
        }
        self.mutation_ledger.append(record)
        return self.revision

    def record_terminal_mutation(self, command: str, forced: bool = False) -> int | None:
        """Detect and register mutations caused by terminal commands."""
        low = command.strip().lower()
        is_mut = forced or any(re.search(pat, low) for pat in MUTATION_COMMAND_PATTERNS)
        if not is_mut:
            return None

        self.revision += 1
        record: MutationRecord = {
            "revision": self.revision,
            "path": f"terminal://{command.strip()[:60]}",
            "tool": "terminal",
            "is_doc_only": False,
            "timestamp": time.time(),
        }
        self.mutation_ledger.append(record)
        return self.revision

    def record_verification(
        self,
        check_id: str,
        passed: bool,
        kind: str = "unit_tests",
        scope_patterns: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> VerificationReceipt:
        """Register a verification receipt at the current workspace revision."""
        receipt: VerificationReceipt = {
            "check_id": check_id,
            "kind": kind,
            "passed": passed,
            "verified_at_revision": self.revision,
            "scope_patterns": scope_patterns or ["*"],
            "timestamp": time.time(),
            "details": details or {},
        }
        self.receipts[check_id] = receipt
        if passed:
            self.last_verified_revision = self.revision
        return receipt

    def is_receipt_stale(self, check_id: str) -> bool:
        """Check if a verification receipt has been invalidated by subsequent code mutations."""
        receipt = self.receipts.get(check_id)
        if not receipt:
            return True

        verified_rev = receipt["verified_at_revision"]
        patterns = receipt.get("scope_patterns", ["*"])

        for mut in self.mutation_ledger:
            if mut["revision"] <= verified_rev:
                continue
            # Pure markdown/rst doc changes never invalidate code verification
            if mut["is_doc_only"]:
                continue

            path = mut["path"]
            # If path matches any tracked pattern, it invalidates
            if any(fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(Path(path).name, pat) for pat in patterns):
                return True

        return False

    def get_effective_verification_status(self) -> Literal["verified", "stale", "unverified", "failed"]:
        """Compute the aggregate verification status across all recorded receipts."""
        if not self.receipts:
            return "unverified"

        has_failed = any(not r["passed"] for r in self.receipts.values())
        if has_failed:
            return "failed"

        has_stale = any(self.is_receipt_stale(cid) for cid in self.receipts)
        if has_stale:
            return "stale"

        return "verified"
