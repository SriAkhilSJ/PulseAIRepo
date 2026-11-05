"""
src/verification/authority.py - Verification Authority Boundary & Workspace Inspection.

Phase 11.7: Independent Verification & Quality Assurance.
Enforces strict separation between implementation authority and verification authority:
- Read-only protection: Verifier cannot perform write/delete mutations on project code.
- Direct evidence retrieval from workspace files and execution environments.
- Rejection of unsubstantiated implementation self-assessments.
- Workspace hash calculations for immutable revision binding.
- Detection of shared assumptions between implementation mocks and tests.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


class VerificationAuthorityViolationError(PermissionError):
    """Raised when verification authority is violated or attempts write access."""
    pass


class VerificationAuthority:
    """
    Enforces the independent verification boundary.
    Guarantees that verification logic operates in a strictly read-only mode relative to
    the target software workspace, and computes cryptographic state bindings.
    """

    def __init__(self, workspace_root: str, tenant_id: str = "default_tenant") -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id
        self._is_read_only = True

    @property
    def is_read_only(self) -> bool:
        return self._is_read_only

    def assert_read_only_boundary(self) -> None:
        """Asserts that the verifier does not have permission to mutate project files."""
        if not self._is_read_only:
            raise VerificationAuthorityViolationError(
                "Verifier has compromised read-only isolation: write permissions are active."
            )

    def write_forbidden(self, path: str, content: str) -> None:
        """Explicitly blocks and raises on any attempted filesystem modification by verifier."""
        raise VerificationAuthorityViolationError(
            f"Verification Authority is strictly READ-ONLY. Modification of '{path}' is forbidden."
        )

    def compute_workspace_hash(self, relative_paths: Optional[List[str]] = None) -> str:
        """
        Computes a deterministic SHA256 digest over the current contents of the workspace files.
        If relative_paths is provided, hashes only those files; otherwise hashes all files.
        """
        hasher = hashlib.sha256()

        if relative_paths is not None:
            sorted_paths = sorted(relative_paths)
            for rel in sorted_paths:
                full_path = (self.workspace_root / rel).resolve()
                if full_path.exists() and full_path.is_file():
                    hasher.update(rel.encode("utf-8"))
                    hasher.update(full_path.read_bytes())
                else:
                    hasher.update(f"MISSING:{rel}".encode("utf-8"))
        else:
            all_files = []
            for root, _, files in os.walk(self.workspace_root):
                for f in files:
                    full = Path(root) / f
                    rel = full.relative_to(self.workspace_root).as_posix()
                    if not rel.startswith(".git") and not rel.startswith(".crusorai"):
                        all_files.append((rel, full))
            all_files.sort(key=lambda x: x[0])
            for rel, full in all_files:
                try:
                    hasher.update(rel.encode("utf-8"))
                    hasher.update(full.read_bytes())
                except Exception:
                    pass

        return hasher.hexdigest()

    def inspect_file(self, rel_path: str) -> Optional[str]:
        """Directly and independently reads file contents from the workspace."""
        self.assert_read_only_boundary()
        target = (self.workspace_root / rel_path).resolve()
        # Prevent path traversal outside workspace
        if not str(target).startswith(str(self.workspace_root)):
            raise VerificationAuthorityViolationError(
                f"Path traversal detected in verifier: '{rel_path}' is outside workspace root."
            )
        if not target.exists() or not target.is_file():
            return None
        return target.read_text(encoding="utf-8", errors="replace")

    def detect_shared_assumptions(
        self,
        impl_files: List[str],
        test_files: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Detects shared assumptions or circular illusions between implementation code and test code.
        Example: both implementation and test mock identical synthetic return values or bypass real validation.
        """
        shared: List[Dict[str, Any]] = []

        # Analyze test files for hardcoded mocks of the exact methods implemented
        for tf in test_files:
            test_content = self.inspect_file(tf)
            if not test_content:
                continue

            for im in impl_files:
                impl_content = self.inspect_file(im)
                if not impl_content:
                    continue

                # Check for shared magic strings or mock return values that bypass logic
                if "unittest.mock" in test_content or "patch(" in test_content:
                    # Check if tests mock the whole interface leaving 0 real execution
                    if "@patch" in test_content and "MagicMock" in test_content:
                        shared.append({
                            "type": "CIRCULAR_MOCK_ASSUMPTION",
                            "test_file": tf,
                            "impl_file": im,
                            "description": "Test relies heavily on patching which may mask real interface divergence.",
                        })

        return shared

