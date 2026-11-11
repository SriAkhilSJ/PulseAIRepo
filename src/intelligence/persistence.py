"""
persistence.py -- Persistent Project Context & Incremental Refresh Manager.

Phase 11.0: Project & Repository Intelligence.
Stores structured project knowledge independently per workspace.
Tracks filesystem modifications via mtimes, enabling fast incremental updates
without unnecessary full-repository rescans.
Guarantees workspace isolation, crash recovery, and zero credential persistence.
"""

from __future__ import annotations

from src.runtime.app_paths import app_data_root

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.intelligence.architecture import ArchitectureMapper
from src.intelligence.discovery import RepositoryDiscoveryEngine
from src.intelligence.models import (
    ArchitectureMap,
    ConfidenceLevel,
    EvidenceFinding,
    ProjectKnowledge,
    ProjectType,
)

log = logging.getLogger("crusorai.intelligence.persistence")

KNOWLEDGE_FILENAME = "project_intelligence.json"


class PersistentProjectIntelligenceManager:
    """
    Manages persistence, caching, and incremental refreshing of ProjectKnowledge.
    """

    def __init__(
        self,
        workspace_root: str,
        storage_dir: Optional[str] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if storage_dir:
            self.storage_dir = Path(storage_dir).resolve()
        else:
            from src.runtime.app_paths import app_data_root
            self.storage_dir = app_data_root(self.workspace_root)

        self.storage_path = self.storage_dir / KNOWLEDGE_FILENAME
        self._lock = threading.Lock()
        self._cached_knowledge: Optional[ProjectKnowledge] = None
        self.discovery_engine = RepositoryDiscoveryEngine(str(self.workspace_root))
        self.architecture_mapper = ArchitectureMapper(str(self.workspace_root))

    def get_project_knowledge(
        self,
        force_full_rescan: bool = False,
        stop_predicate: Optional[Callable[[], bool]] = None,
    ) -> ProjectKnowledge:
        """
        Retrieve project knowledge:
        - If cached and up-to-date, returns immediately.
        - If modified files are detected, performs incremental refresh.
        - If cache is missing or force_full_rescan is True, executes full scan.
        """
        with self._lock:
            # 1. Try loading from memory or disk
            if not self._cached_knowledge and not force_full_rescan:
                self._cached_knowledge = self._load_from_disk()

            # 2. If no cache or forced full rescan, execute full discovery
            if not self._cached_knowledge or force_full_rescan:
                log.info(f"Performing full repository discovery for {self.workspace_root}")
                knowledge = self._execute_full_discovery(stop_predicate=stop_predicate)
                self._cached_knowledge = knowledge
                self._save_to_disk(knowledge)
                return knowledge

            # 3. Incremental Change Detection
            changed, added, deleted = self._detect_file_changes(self._cached_knowledge.file_mtimes)
            if not changed and not added and not deleted:
                # Zero file changes: return clean cached knowledge
                return self._cached_knowledge

            log.info(f"Incremental refresh: {len(changed)} modified, {len(added)} added, {len(deleted)} deleted")
            self._incremental_refresh(self._cached_knowledge, changed, added, deleted, stop_predicate=stop_predicate)
            self._save_to_disk(self._cached_knowledge)
            return self._cached_knowledge

    def _execute_full_discovery(self, stop_predicate: Optional[Callable[[], bool]] = None) -> ProjectKnowledge:
        """Perform a complete bounded repository scan and architecture mapping."""
        disc_data = self.discovery_engine.discover_repository(stop_predicate=stop_predicate)
        rel_paths = list(disc_data.get("file_mtimes", {}).keys())

        # Map architecture
        arch_map = self.architecture_mapper.map_architecture(rel_paths)

        knowledge = ProjectKnowledge(
            project_name=self.workspace_root.name,
            workspace_root=str(self.workspace_root),
            project_purpose=disc_data["project_purpose"],
            project_type=disc_data["project_type"],
            languages=disc_data["languages"],
            frameworks=disc_data["frameworks"],
            build_commands=disc_data["build_commands"],
            entry_points=disc_data["entry_points"],
            source_dirs=disc_data["source_dirs"],
            test_dirs=disc_data["test_dirs"],
            config_files=disc_data["config_files"],
            api_endpoints=disc_data["api_endpoints"],
            database_info=disc_data["database_info"],
            agent_tool_integrations=disc_data["agent_tool_integrations"],
            env_var_names=disc_data["env_var_names"],
            architecture_map=arch_map,
            git_info=disc_data["git_info"],
            last_scanned_timestamp=time.time(),
            scan_revision=disc_data["git_info"].get("head", ""),
            discovery_confidence=disc_data["discovery_confidence"],
            file_mtimes=disc_data["file_mtimes"],
        )
        return knowledge

    def _detect_file_changes(self, cached_mtimes: Dict[str, float]) -> Tuple[Set[str], Set[str], Set[str]]:
        """
        Compare current workspace file mtimes against cached mtimes.
        Returns (modified_files, added_files, deleted_files).
        """
        current_mtimes: Dict[str, float] = {}
        for root, dirs, filenames in os.walk(str(self.workspace_root)):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {".git", "node_modules", ".venv", "__pycache__"}]
            r_path = Path(root)
            for fname in filenames:
                f_path = r_path / fname
                try:
                    rel = str(f_path.relative_to(self.workspace_root)).replace("\\", "/")
                    current_mtimes[rel] = f_path.stat().st_mtime
                except (OSError, PermissionError):
                    continue

        curr_keys = set(current_mtimes.keys())
        cached_keys = set(cached_mtimes.keys())

        added = curr_keys - cached_keys
        deleted = cached_keys - curr_keys
        modified = set()

        for k in curr_keys.intersection(cached_keys):
            if abs(current_mtimes[k] - cached_mtimes[k]) > 0.001:
                modified.add(k)

        return modified, added, deleted

    def _incremental_refresh(
        self,
        knowledge: ProjectKnowledge,
        modified: Set[str],
        added: Set[str],
        deleted: Set[str],
        stop_predicate: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Update knowledge model for changed files without rescanning entire tree."""
        # 1. Update file_mtimes
        for f in deleted:
            knowledge.file_mtimes.pop(f, None)

        for f in added.union(modified):
            p = self.workspace_root / f
            try:
                knowledge.file_mtimes[f] = p.stat().st_mtime
            except OSError:
                pass

        # 2. If manifests changed (e.g. package.json, pyproject.toml), re-evaluate frameworks & commands
        manifest_changes = any(
            f in {"package.json", "pyproject.toml", "requirements.txt", "Cargo.toml"}
            for f in added.union(modified).union(deleted)
        )
        if manifest_changes:
            fw, bc, pt, pur = self.discovery_engine._analyze_manifests(self.workspace_root, set(knowledge.file_mtimes.keys()))
            knowledge.frameworks = fw
            knowledge.build_commands = bc
            knowledge.project_type = pt
            if pur.confidence == ConfidenceLevel.VERIFIED:
                knowledge.project_purpose = pur

        # 3. Update architecture map components
        rel_paths = list(knowledge.file_mtimes.keys())
        knowledge.architecture_map = self.architecture_mapper.map_architecture(rel_paths)
        knowledge.last_scanned_timestamp = time.time()

    def _load_from_disk(self) -> Optional[ProjectKnowledge]:
        """Load knowledge from workspace storage path if exists."""
        if not self.storage_path.exists():
            return None
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8", errors="replace"))
            # Ensure workspace path matches (prevent cross-workspace leakage)
            if data.get("workspace_root") != str(self.workspace_root):
                log.warning("Storage workspace_root mismatch. Ignoring cached knowledge.")
                return None
            return ProjectKnowledge.from_dict(data)
        except Exception as e:
            log.warning(f"Failed to load cached project knowledge from {self.storage_path}: {e}")
            return None

    def _save_to_disk(self, knowledge: ProjectKnowledge) -> None:
        """Persist knowledge model safely with directory creation."""
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(json.dumps(knowledge.to_dict(), indent=2), encoding="utf-8")
            log.info(f"Persisted project knowledge to {self.storage_path}")
        except Exception as e:
            log.warning(f"Failed to save project knowledge: {e}")

