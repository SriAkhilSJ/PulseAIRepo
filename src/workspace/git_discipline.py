"""
src/workspace/git_discipline.py - Git Safety Rules & Upstream Invariant 7 Protection.

Phase 11.3: Workspace Discipline & Change Management.
Enforces:
1. Strict preservation of pre-existing user staged, unstaged, and untracked changes.
2. Prohibiting automated git reset, git clean, git stash, branch switching, commit, and push.
3. Upstream Invariant 7 enforcement on `desktop/SELECTIVE_MANIFEST.json` (exactly 5 files, 0 drift).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("crusor.workspace.git")

# Exactly the 5 permitted overlay files per Upstream Invariant 7
PERMITTED_INVARIANT_7_FILES = frozenset({
    "build/buildfile.ts",
    "build/next/index.ts",
    "product.json",
    "src/vs/workbench/workbench.common.main.ts",
    "src/vs/workbench/workbench.desktop.main.ts",
})


class GitDisciplineManager:
    """
    Guarantees that Git operations never destroy user work and preserves Invariant 7.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def verify_invariant_7(self) -> Tuple[bool, int, List[str], str]:
        """
        Verify Upstream Invariant 7:
        `desktop/SELECTIVE_MANIFEST.json` must contain exactly 5 permitted files.
        Returns (is_valid, file_count, file_list, message).
        """
        manifest_path = self.workspace_root / "desktop" / "SELECTIVE_MANIFEST.json"
        if not manifest_path.exists():
            # If not in desktop repo root, check current directory
            manifest_path = Path("desktop") / "SELECTIVE_MANIFEST.json"
            if not manifest_path.exists():
                return False, 0, [], "desktop/SELECTIVE_MANIFEST.json not found."

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            files_dict = data.get("files", {})
            file_keys = sorted(list(files_dict.keys()))
            count = len(file_keys)

            if count != 5:
                return (
                    False,
                    count,
                    file_keys,
                    f"Invariant 7 violation: Expected exactly 5 permitted files in SELECTIVE_MANIFEST.json, found {count}.",
                )

            diff_set = set(file_keys).symmetric_difference(PERMITTED_INVARIANT_7_FILES)
            if diff_set:
                return (
                    False,
                    count,
                    file_keys,
                    f"Invariant 7 drift detected: Keys do not match expected 5 files. Mismatch: {diff_set}",
                )

            return True, 5, file_keys, "Invariant 7 VERIFIED: Exactly 5 permitted files, zero drift."

        except Exception as e:
            return False, 0, [], f"Failed to verify Invariant 7: {e}"

    def audit_git_safety(self) -> Dict[str, Any]:
        """
        Audit current Git working tree status.
        """
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain=v1"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode != 0:
                return {"is_git": False, "status": "Not a git repository"}

            staged = []
            unstaged = []
            untracked = []

            for line in res.stdout.splitlines():
                if len(line) < 4:
                    continue
                x, y = line[0], line[1]
                path = line[3:].strip()
                if x in ("M", "A", "D", "R", "C"):
                    staged.append(path)
                if y in ("M", "D"):
                    unstaged.append(path)
                if x == "?" and y == "?":
                    untracked.append(path)

            return {
                "is_git": True,
                "staged_count": len(staged),
                "unstaged_count": len(unstaged),
                "untracked_count": len(untracked),
                "staged_files": staged,
                "unstaged_files": unstaged,
                "untracked_files": untracked,
            }
        except Exception as e:
            return {"is_git": False, "error": str(e)}

    def is_operation_permitted(self, git_subcommand: str) -> Tuple[bool, str]:
        """
        Verify whether an automated Git subcommand is permitted without user authorization.
        """
        sub = git_subcommand.strip().lower()
        prohibited = {"reset", "clean", "checkout", "restore", "push", "commit", "branch", "switch", "stash", "rebase"}
        for p in prohibited:
            if sub == p or sub.startswith(p + " "):
                return False, f"Automated 'git {sub}' is strictly prohibited. Requires explicit user authorization."

        return True, "Safe query or inspection operation."

