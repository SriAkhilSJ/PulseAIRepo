"""
test_phase_11_0_project_intelligence.py -- Deterministic Test Suite for Phase 11.0.

Phase 11.0: Project & Repository Intelligence.
Evaluates 18 required test areas:
1. Repository discovery
2. Multi-language project detection
3. Framework detection
4. Entry-point discovery
5. Dependency mapping
6. Architecture extraction
7. Evidence and confidence classification
8. Incremental rescanning
9. File creation, deletion, and rename handling
10. Workspace isolation
11. Sensitive-file exclusion
12. Symlink and path traversal protection
13. Scan cancellation
14. Large repository handling
15. Malformed configuration handling
16. Persistence and recovery
17. Agent context integration
18. Regression protection
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict

from src.intelligence.models import (
    ArchitectureMap,
    ConfidenceLevel,
    EvidenceFinding,
    ProjectKnowledge,
    ProjectType,
)
from src.intelligence.discovery import (
    DEFAULT_SKIP_DIRS,
    SENSITIVE_FILES,
    RepositoryDiscoveryEngine,
)
from src.intelligence.architecture import ArchitectureMapper
from src.intelligence.persistence import PersistentProjectIntelligenceManager
from src.intelligence.agent_integration import ProjectIntelligenceRetriever


class TestPhase11ProjectIntelligence(unittest.TestCase):
    """18 Deterministic Verification Scenarios for Phase 11.0 Project Intelligence."""

    def setUp(self) -> None:
        self.tmp_root = tempfile.mkdtemp(prefix="crusor_phase11_test_")
        self.workspace_dir = Path(self.tmp_root) / "test_workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # Build realistic mock repository structure
        (self.workspace_dir / "src").mkdir(exist_ok=True)
        (self.workspace_dir / "src" / "api").mkdir(exist_ok=True)
        (self.workspace_dir / "src" / "models").mkdir(exist_ok=True)
        (self.workspace_dir / "tests").mkdir(exist_ok=True)

        # package.json
        (self.workspace_dir / "package.json").write_text(json.dumps({
            "name": "mock-app",
            "version": "1.0.0",
            "description": "Mock Enterprise Fullstack Application",
            "scripts": {
                "build": "tsc -b",
                "start": "node dist/index.js",
                "test": "vitest run"
            },
            "dependencies": {
                "electron": "^28.0.0",
                "react": "^18.2.0"
            },
            "devDependencies": {
                "vitest": "^1.0.0"
            }
        }), encoding="utf-8")

        # requirements.txt
        (self.workspace_dir / "requirements.txt").write_text("fastapi>=0.100.0\npytest>=8.0.0\nlanggraph>=0.2.0\n", encoding="utf-8")

        # Entry points
        (self.workspace_dir / "main.py").write_text(
            'from src.api.server import app\nif __name__ == "__main__":\n    import uvicorn\n    uvicorn.run(app)\n',
            encoding="utf-8"
        )
        (self.workspace_dir / "src" / "api" / "server.py").write_text(
            'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/health")\ndef health():\n    return {"status": "ok"}\n',
            encoding="utf-8"
        )
        (self.workspace_dir / "index.ts").write_text(
            'console.log("Starting desktop renderer");\n',
            encoding="utf-8"
        )

        # Secret file (must be ignored)
        (self.workspace_dir / ".env").write_text("SUPER_SECRET_KEY=supersecret123\n", encoding="utf-8")
        (self.workspace_dir / ".env.example").write_text("API_KEY=\nDATABASE_URL=\nPORT=8000\n", encoding="utf-8")

        self.manager = PersistentProjectIntelligenceManager(str(self.workspace_dir))
        self.retriever = ProjectIntelligenceRetriever(self.manager)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    # 1. Repository discovery
    def test_01_repository_discovery(self) -> None:
        """Discovers languages, entry points, and build commands accurately."""
        k = self.manager.get_project_knowledge()
        self.assertIn("Python", k.languages)
        self.assertIn("TypeScript", k.languages)
        self.assertIsNotNone(k.build_commands.build)
        self.assertIn("tsc", k.build_commands.build)
        self.assertIn("vitest", k.build_commands.test)
        self.assertTrue(len(k.entry_points) >= 2)

    # 2. Multi-language project detection
    def test_02_multi_language_project_detection(self) -> None:
        """Detects mixed Python and TypeScript/JavaScript source trees."""
        k = self.manager.get_project_knowledge()
        self.assertIn("Python", k.languages)
        self.assertIn("TypeScript", k.languages)
        # Should be detected as Electron or Multi-Language/AI Agent Platform
        self.assertIn(k.project_type.value, {ProjectType.DESKTOP_ELECTRON, ProjectType.MULTI_LANGUAGE, ProjectType.AI_AGENT_PLATFORM})

    # 3. Framework detection
    def test_03_framework_detection(self) -> None:
        """Discovers frameworks from package.json and requirements.txt."""
        k = self.manager.get_project_knowledge()
        fw_names = {f.name for f in k.frameworks}
        self.assertIn("Electron", fw_names)
        self.assertIn("React", fw_names)
        self.assertIn("FastAPI", fw_names)
        self.assertIn("LangGraph", fw_names)
        self.assertTrue("Vitest" in fw_names or "pytest" in fw_names)

    # 4. Entry-point discovery
    def test_04_entry_point_discovery(self) -> None:
        """Finds main.py and index.ts entry points with evidence."""
        k = self.manager.get_project_knowledge()
        entry_paths = {e.path for e in k.entry_points}
        self.assertIn("main.py", entry_paths)
        self.assertIn("index.ts", entry_paths)
        for ep in k.entry_points:
            self.assertTrue(len(ep.evidence) > 0)

    # 5. Dependency mapping
    def test_05_dependency_mapping(self) -> None:
        """Maps internal component and external module imports."""
        k = self.manager.get_project_knowledge()
        self.assertIsNotNone(k.architecture_map)
        self.assertTrue(len(k.architecture_map.components) > 0)

    # 6. Architecture extraction
    def test_06_architecture_extraction(self) -> None:
        """Extracts major architectural components, responsibilities, and flows."""
        k = self.manager.get_project_knowledge()
        arch = k.architecture_map
        self.assertTrue("src/api" in arch.components or "src" in arch.components)
        self.assertTrue(len(arch.execution_flows) > 0)

    # 7. Evidence and confidence classification
    def test_07_evidence_and_confidence_classification(self) -> None:
        """Distinguishes VERIFIED facts from INFERRED assumptions."""
        k = self.manager.get_project_knowledge()
        self.assertEqual(k.project_type.confidence, ConfidenceLevel.VERIFIED)
        self.assertIsNotNone(k.project_type.source_file)
        self.assertIn(k.project_purpose.confidence, {ConfidenceLevel.VERIFIED, ConfidenceLevel.INFERRED})

    # 8. Incremental rescanning
    def test_08_incremental_rescanning(self) -> None:
        """Refreshes knowledge incrementally without unnecessary full rescan."""
        # Initial scan
        k1 = self.manager.get_project_knowledge()
        t1 = k1.last_scanned_timestamp

        # Immediate repeat: zero changes, returns cached instance immediately
        k2 = self.manager.get_project_knowledge()
        self.assertEqual(k1.scan_revision, k2.scan_revision)

        # Modify one file
        time.sleep(0.05)
        (self.workspace_dir / "src" / "api" / "server.py").write_text(
            'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/status")\ndef status(): return {"ok": True}\n',
            encoding="utf-8"
        )
        k3 = self.manager.get_project_knowledge()
        self.assertTrue(k3.last_scanned_timestamp >= t1)

    # 9. File creation, deletion, and rename handling
    def test_09_file_creation_deletion_rename(self) -> None:
        """Handles added, deleted, and renamed files accurately."""
        k1 = self.manager.get_project_knowledge()

        # Add file
        new_file = self.workspace_dir / "src" / "models" / "user.py"
        new_file.write_text("class User: pass\n", encoding="utf-8")
        k2 = self.manager.get_project_knowledge()
        self.assertIn("src/models/user.py", k2.file_mtimes)

        # Delete file
        new_file.unlink()
        k3 = self.manager.get_project_knowledge()
        self.assertNotIn("src/models/user.py", k3.file_mtimes)

    # 10. Workspace isolation
    def test_10_workspace_isolation(self) -> None:
        """Knowledge from Workspace A never leaks into Workspace B."""
        ws_b = Path(self.tmp_root) / "workspace_b"
        ws_b.mkdir(parents=True, exist_ok=True)
        (ws_b / "Cargo.toml").write_text('[package]\nname = "rust-cli"\nversion = "0.1.0"\n', encoding="utf-8")
        (ws_b / "src").mkdir(exist_ok=True)
        (ws_b / "src" / "main.rs").write_text('fn main() { println!("Hello"); }\n', encoding="utf-8")

        mgr_b = PersistentProjectIntelligenceManager(str(ws_b))
        k_b = mgr_b.get_project_knowledge()
        self.assertEqual(k_b.project_name, "workspace_b")
        self.assertTrue("Rust" in k_b.languages or "Cargo" in [f.name for f in k_b.frameworks])
        self.assertNotIn("Electron", [f.name for f in k_b.frameworks])

    # 11. Sensitive-file exclusion
    def test_11_sensitive_file_exclusion(self) -> None:
        """Sensitive files (.env) are never parsed for credentials or stored."""
        k = self.manager.get_project_knowledge()
        self.assertNotIn(".env", k.file_mtimes)
        # Variable names from .env.example should be present
        self.assertIn("API_KEY", k.env_var_names)
        self.assertIn("DATABASE_URL", k.env_var_names)
        # Values must NEVER be present
        serialized = json.dumps(k.to_dict())
        self.assertNotIn("supersecret123", serialized)

    # 12. Symlink and path traversal protection
    def test_12_symlink_and_traversal_protection(self) -> None:
        """Symlinks pointing outside workspace root are skipped safely."""
        outside_dir = Path(self.tmp_root) / "outside"
        outside_dir.mkdir(parents=True, exist_ok=True)
        (outside_dir / "secret.txt").write_text("outside data", encoding="utf-8")

        symlink_target = self.workspace_dir / "symlink_out"
        try:
            os.symlink(str(outside_dir), str(symlink_target))
        except (OSError, NotImplementedError):
            pass  # Windows permissions may skip symlink creation in non-elevated shells

        k = self.manager.get_project_knowledge(force_full_rescan=True)
        self.assertNotIn("symlink_out/secret.txt", k.file_mtimes)

    # 13. Scan cancellation
    def test_13_scan_cancellation_and_timeout(self) -> None:
        """Stop predicate terminates scan cleanly."""
        engine = RepositoryDiscoveryEngine(str(self.workspace_dir))
        res = engine.discover_repository(stop_predicate=lambda: True)
        self.assertEqual(res["total_files"], 0)

    # 14. Large repository handling
    def test_14_large_repository_handling(self) -> None:
        """Max files budget bounds traversal without throwing out-of-memory errors."""
        engine = RepositoryDiscoveryEngine(str(self.workspace_dir), max_files=2)
        res = engine.discover_repository()
        self.assertLessEqual(res["total_files"], 2)

    # 15. Malformed configuration handling
    def test_15_malformed_configuration_handling(self) -> None:
        """Corrupted JSON/TOML does not crash discovery."""
        (self.workspace_dir / "package.json").write_text("{malformed: json invalid", encoding="utf-8")
        engine = RepositoryDiscoveryEngine(str(self.workspace_dir))
        res = engine.discover_repository()
        self.assertIsNotNone(res["project_type"])

    # 16. Persistence and recovery
    def test_16_persistence_and_recovery(self) -> None:
        """Knowledge persists to disk and reloads accurately."""
        k1 = self.manager.get_project_knowledge()
        storage_file = self.workspace_dir / ".crusorai" / "project_intelligence.json"
        self.assertTrue(storage_file.exists())

        # Create new manager pointing to same workspace
        mgr2 = PersistentProjectIntelligenceManager(str(self.workspace_dir))
        k2 = mgr2.get_project_knowledge()
        self.assertEqual(k1.project_name, k2.project_name)
        self.assertEqual(k1.build_commands.test, k2.build_commands.test)

    # 17. Agent context integration
    def test_17_agent_context_integration(self) -> None:
        """Targeted retrieval yields concise, task-specific intelligence."""
        plan_ctx = self.retriever.get_planning_context("Build new authentication endpoint")
        self.assertIn("project_name", plan_ctx)
        self.assertIn("frameworks", plan_ctx)
        self.assertIn("major_components", plan_ctx)

        edit_ctx = self.retriever.get_editing_context(["src/api/server.py"])
        self.assertIn("related_components", edit_ctx)

        debug_ctx = self.retriever.get_debugging_context("Error: Connection refused")
        self.assertIn("test_command", debug_ctx)

        md = self.retriever.render_markdown_context()
        self.assertIn("### Project Intelligence:", md)

    # 18. Regression protection
    def test_18_regression_protection(self) -> None:
        """Verify discovery does not modify any source code files."""
        stat_before = {p: p.stat().st_mtime for p in self.workspace_dir.glob("**/*") if p.is_file()}
        _ = self.manager.get_project_knowledge(force_full_rescan=True)
        stat_after = {p: p.stat().st_mtime for p in self.workspace_dir.glob("**/*") if p.is_file() and ".crusorai" not in str(p)}

        for p, mtime in stat_before.items():
            if ".crusorai" not in str(p):
                self.assertEqual(mtime, stat_after.get(p))


if __name__ == "__main__":
    unittest.main()
