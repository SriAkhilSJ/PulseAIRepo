"""
src/workspace/cleanliness.py - Dependency and Project Cleanliness Engine.

Phase 11.3: Workspace Discipline & Change Management.
Enforces:
1. Detecting redundant/duplicate dependencies before addition.
2. Detecting existing implementations and duplicate file responsibilities.
3. Post-implementation scanning for debug scripts, temporary files, and abandoned artifacts.
4. Protecting user-owned files from accidental automated cleanup.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.workspace.baseline import WorkspaceBaselineManager
from src.workspace.path_safety import PathSafetyValidator

log = logging.getLogger("crusor.workspace.cleanliness")

# Recognized temporary/scratch file patterns
DEBUG_FILE_PATTERNS = [
    r"^test_debug.*\.py$",
    r"^scratch.*",
    r"^tmp_.*",
    r"^temp_.*",
    r"^debug_.*",
    r".*\.tmp$",
    r".*\.bak$",
]


class CleanlinessChecker:
    """
    Scans for project cleanliness violations, abandoned debug artifacts,
    and redundant dependencies.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.baseline_mgr = WorkspaceBaselineManager(str(self.workspace_root))

    def detect_redundant_dependency(self, new_dep: str) -> Optional[str]:
        """
        Check if the capability is already satisfied by an existing dependency.
        Returns warning string if redundant, None if genuinely new.
        """
        dep_lower = new_dep.strip().lower()

        # Capability equivalence map
        EQUIVALENCES: Dict[str, Tuple[str, str]] = {
            "requests": ("httpx", "aiohttp"),
            "httpx": ("requests", "aiohttp"),
            "aiohttp": ("httpx", "requests"),
            "pydantic": ("marshmallow", "attrs"),
            "pytest": ("unittest", "nose2"),
            "fastapi": ("flask", "django"),
            "flask": ("fastapi", "django"),
            "prisma": ("sqlalchemy", "tortoise-orm"),
            "sqlalchemy": ("tortoise-orm", "peewee"),
        }

        # Inspect existing project dependencies
        existing = self._scan_existing_dependencies()

        if dep_lower in existing:
            return f"Dependency '{new_dep}' is already installed/declared in project manifests."

        if dep_lower in EQUIVALENCES:
            alternatives = EQUIVALENCES[dep_lower]
            for alt in alternatives:
                if alt in existing:
                    return f"Project already uses '{alt}', which provides equivalent capability to '{new_dep}'."

        return None

    def scan_for_debug_and_temporary_artifacts(self) -> List[Dict[str, Any]]:
        """
        Find debug scripts and temporary files created in the workspace.
        CRITICAL: Never flag or clean files that existed in the baseline as user files!
        """
        artifacts: List[Dict[str, Any]] = []

        for root, dirs, files in os.walk(str(self.workspace_root)):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv", ".venv")]
            for f in files:
                full_p = Path(root) / f
                try:
                    rel_p = PathSafetyValidator.get_relative_normalized(self.workspace_root, full_p)
                except Exception:
                    continue

                # Check if it matches debug or scratch pattern
                if any(re.match(pat, f, re.IGNORECASE) for pat in DEBUG_FILE_PATTERNS):
                    is_user = self.baseline_mgr.is_user_owned(rel_p)
                    artifacts.append({
                        "path": rel_p,
                        "filename": f,
                        "is_user_owned": is_user,
                        "safe_to_cleanup": not is_user,
                        "reason": f"Matches debug/scratch pattern ('{f}')",
                    })

        return artifacts

    def detect_unused_imports(self, py_file_path: str) -> List[str]:
        """
        Inspect a python file for unused imports using AST.
        """
        full_p = self.workspace_root / py_file_path
        if not full_p.exists() or full_p.suffix.lower() != ".py":
            return []

        try:
            content = full_p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content)
        except Exception:
            return []

        imported_names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)

        # Count references in body (excluding import statements)
        used_names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
                used_names.add(node.id)

        unused = [name for name in imported_names if name not in used_names and not name.startswith("_")]
        return unused

    def _scan_existing_dependencies(self) -> Set[str]:
        deps: Set[str] = set()
        pyproj = self.workspace_root / "pyproject.toml"
        if pyproj.exists():
            try:
                for line in pyproj.read_text(encoding="utf-8").splitlines():
                    line = line.strip().lower()
                    if "=" in line and not line.startswith("[") and not line.startswith("#"):
                        key = line.split("=")[0].strip()
                        deps.add(key)
            except Exception:
                pass

        req_txt = self.workspace_root / "requirements.txt"
        if req_txt.exists():
            try:
                for line in req_txt.read_text(encoding="utf-8").splitlines():
                    line = line.strip().lower()
                    if line and not line.startswith("#"):
                        pkg = re.split(r"[><=~]", line)[0].strip()
                        if pkg:
                            deps.add(pkg)
            except Exception:
                pass

        pkg_json = self.workspace_root / "package.json"
        if pkg_json.exists():
            try:
                import json
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                for k in data.get("dependencies", {}).keys():
                    deps.add(k.lower())
                for k in data.get("devDependencies", {}).keys():
                    deps.add(k.lower())
            except Exception:
                pass

        return deps

