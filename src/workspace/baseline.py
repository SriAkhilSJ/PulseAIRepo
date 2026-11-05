"""
src/workspace/baseline.py - Workspace State Baseline Manager.

Phase 11.3: Workspace Discipline & Change Management.
Captures comprehensive workspace state prior to modifications:
- Git branch, commit, staged changes, unstaged changes, untracked files
- File hashes (SHA-256) and metadata
- Explicit distinction between pre-existing user state and agent modifications
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.workspace.models import FileOwnershipCategory, WorkspaceBaseline
from src.workspace.path_safety import PathSafetyValidator

log = logging.getLogger("crusor.workspace.baseline")

# Standard skip directories for hash computation to preserve efficiency
DEFAULT_SKIP_DIRS = frozenset({
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".crusorai",
})


def compute_file_sha256(path: Path) -> str:
    """Compute deterministic SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


class WorkspaceBaselineManager:
    """
    Captures, persists, and queries the pre-task workspace baseline.
    Ensures pre-existing user work is never assumed to belong to Crusor.
    """

    def __init__(self, workspace_root: str, storage_dir: Optional[str] = None) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if storage_dir:
            self.storage_dir = Path(storage_dir).resolve()
        else:
            self.storage_dir = self.workspace_root / ".crusorai" / "baseline"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.baseline_file = self.storage_dir / "workspace_baseline.json"
        self._current_baseline: Optional[WorkspaceBaseline] = None

    def capture_baseline(self, force_refresh: bool = False) -> WorkspaceBaseline:
        """
        Capture current workspace and git status.
        If baseline already captured and force_refresh is False, returns cached baseline.
        """
        if self._current_baseline and not force_refresh:
            return self._current_baseline

        git_root, branch, commit_hash = self._inspect_git_info()
        staged, unstaged, untracked = self._inspect_git_status(git_root)

        clean_files: Dict[str, str] = {}
        modified_files: Dict[str, str] = {}
        staged_files: Dict[str, str] = {}
        untracked_files: Dict[str, str] = {}
        ignored_files: List[str] = []

        # Hash tracked and untracked files within workspace
        for root, dirs, files in os.walk(str(self.workspace_root)):
            dirs[:] = [d for d in dirs if d not in DEFAULT_SKIP_DIRS and not d.startswith(".crusorai")]
            root_p = Path(root)
            for fname in files:
                full_p = root_p / fname
                try:
                    rel_p = PathSafetyValidator.get_relative_normalized(self.workspace_root, full_p)
                except Exception:
                    continue

                fhash = compute_file_sha256(full_p)
                if rel_p in staged:
                    staged_files[rel_p] = fhash
                elif rel_p in unstaged:
                    modified_files[rel_p] = fhash
                elif rel_p in untracked:
                    untracked_files[rel_p] = fhash
                else:
                    # Clean file
                    clean_files[rel_p] = fhash

        baseline = WorkspaceBaseline(
            workspace_root=str(self.workspace_root),
            git_root=git_root,
            branch=branch,
            commit_hash=commit_hash,
            clean_files=clean_files,
            modified_files=modified_files,
            staged_files=staged_files,
            untracked_files=untracked_files,
            ignored_files=ignored_files,
            captured_timestamp=time.time(),
        )

        self._current_baseline = baseline
        self._save_to_disk(baseline)
        return baseline

    def get_baseline(self) -> WorkspaceBaseline:
        """Get or load active baseline."""
        if self._current_baseline:
            return self._current_baseline
        if self.baseline_file.exists():
            try:
                data = json.loads(self.baseline_file.read_text(encoding="utf-8"))
                self._current_baseline = WorkspaceBaseline.from_dict(data)
                return self._current_baseline
            except Exception:
                pass
        return self.capture_baseline()

    def classify_file_provenance(self, rel_path: str) -> FileOwnershipCategory:
        """
        Classifies the baseline ownership category of a relative path.
        """
        base = self.get_baseline()
        norm = rel_path.replace("\\", "/")
        if norm in base.staged_files:
            return FileOwnershipCategory.EXISTING_USER_STAGED
        if norm in base.modified_files:
            return FileOwnershipCategory.EXISTING_USER_MODIFIED
        if norm in base.untracked_files:
            return FileOwnershipCategory.EXISTING_USER_UNTRACKED
        if norm in base.clean_files:
            return FileOwnershipCategory.EXISTING_USER_CLEAN
        # Not present in baseline -> newly created file
        return FileOwnershipCategory.AGENT_CREATED

    def is_user_owned(self, rel_path: str) -> bool:
        """True if file existed in baseline (clean, modified, staged, or untracked)."""
        cat = self.classify_file_provenance(rel_path)
        return cat in {
            FileOwnershipCategory.EXISTING_USER_CLEAN,
            FileOwnershipCategory.EXISTING_USER_MODIFIED,
            FileOwnershipCategory.EXISTING_USER_STAGED,
            FileOwnershipCategory.EXISTING_USER_UNTRACKED,
        }

    def _inspect_git_info(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        if not (self.workspace_root / ".git").exists():
            return None, None, None
        try:
            res_root = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res_root.returncode != 0:
                return None, None, None
            git_root = res_root.stdout.strip()

            res_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            branch = res_branch.stdout.strip() if res_branch.returncode == 0 else "HEAD"

            res_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            commit = res_commit.stdout.strip() if res_commit.returncode == 0 else None

            return git_root, branch, commit
        except Exception:
            return None, None, None

    def _inspect_git_status(
        self, git_root: Optional[str]
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        staged: Set[str] = set()
        unstaged: Set[str] = set()
        untracked: Set[str] = set()

        if not git_root:
            return staged, unstaged, untracked

        try:
            res = subprocess.run(
                ["git", "status", "--porcelain=v1", "-uall"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode != 0:
                return staged, unstaged, untracked

            for line in res.stdout.splitlines():
                if len(line) < 4:
                    continue
                x = line[0]
                y = line[1]
                path_str = line[3:].strip()
                # If path contains ' -> ' (rename), take destination
                if " -> " in path_str:
                    path_str = path_str.split(" -> ")[1].strip()
                path_str = path_str.strip('"').replace("\\", "/")

                # Staged changes (X is not space or ?)
                if x in {"M", "A", "D", "R", "C"}:
                    staged.add(path_str)
                # Unstaged changes (Y is not space or ?)
                if y in {"M", "D"}:
                    unstaged.add(path_str)
                # Untracked files
                if x == "?" and y == "?":
                    untracked.add(path_str)

        except Exception as e:
            log.warning(f"Failed to inspect git status: {e}")

        return staged, unstaged, untracked

    def _save_to_disk(self, baseline: WorkspaceBaseline) -> None:
        try:
            tmp = self.baseline_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(baseline.to_dict(), indent=2), encoding="utf-8")
            os.replace(tmp, self.baseline_file)
        except Exception as e:
            log.error(f"Failed to save baseline: {e}")
