"""
discovery.py -- Deterministic Repository Discovery Engine.

Phase 11.0: Project & Repository Intelligence.
Extracts languages, frameworks, package managers, entry points, build/run commands,
API routes, database structures, agent/tool configurations, environment variable names,
and Git status from actual workspace evidence without hallucination.
Enforces strict workspace boundaries, bounded traversal budgets, and zero secret leakage.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.intelligence.models import (
    ApiEndpoint,
    BuildCommands,
    ConfidenceLevel,
    DatabaseSchemaInfo,
    EntryPoint,
    EvidenceFinding,
    FrameworkInfo,
    LanguageInfo,
    ProjectType,
)

log = logging.getLogger("crusorai.intelligence.discovery")

# Standard scan skip directories
DEFAULT_SKIP_DIRS: Set[str] = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", "out", ".idea", ".vscode",
    "coverage", ".cache", ".next", ".nuxt", "site-packages"
}

# Sensitive files that must NEVER be parsed for credentials
SENSITIVE_FILES: Set[str] = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_ecdsa", "id_ed25519", "credentials.json",
    "service-account.json", "private_key.pem", "secret.key"
}

# Extension to language mappings
LANGUAGE_EXTENSION_MAP: Dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (JSX)",
    ".js": "JavaScript",
    ".jsx": "JavaScript (JSX)",
    ".rs": "Rust",
    ".go": "Go",
    ".html": "HTML",
    ".css": "CSS",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bat": "Batch",
    ".ps1": "PowerShell",
    ".json": "JSON",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
}


class RepositoryDiscoveryEngine:
    """
    Deterministic workspace scanner that derives evidence-backed project facts.
    """

    def __init__(
        self,
        workspace_root: str,
        max_files: int = 1500,
        max_bytes: int = 25 * 1024 * 1024,  # 25 MB
        timeout_seconds: float = 15.0,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds

    def discover_repository(
        self,
        stop_predicate: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Execute full repository discovery within bounded safety limits.
        """
        start_time = time.time()
        files: List[Tuple[str, Path, os.stat_result]] = []
        file_mtimes: Dict[str, float] = {}
        total_bytes = 0

        # 1. Bounded Filesystem Traversal
        for root, dirs, filenames in os.walk(str(self.workspace_root)):
            if stop_predicate and stop_predicate():
                log.info("Discovery scan cancelled by stop predicate")
                break
            if time.time() - start_time > self.timeout_seconds:
                log.warning(f"Discovery scan timed out after {self.timeout_seconds}s")
                break

            # Prune skipped directories
            dirs[:] = [d for d in dirs if d not in DEFAULT_SKIP_DIRS and not d.startswith(".")]

            root_path = Path(root)
            for fname in filenames:
                if len(files) >= self.max_files:
                    break
                if total_bytes >= self.max_bytes:
                    break
                if stop_predicate and stop_predicate():
                    break

                # Never touch sensitive credential files
                if fname in SENSITIVE_FILES:
                    continue

                full_path = root_path / fname

                # Prevent symlink traversal out of workspace
                if full_path.is_symlink():
                    try:
                        resolved = full_path.resolve()
                        resolved.relative_to(self.workspace_root)
                    except (ValueError, RuntimeError):
                        continue

                try:
                    st = full_path.stat()
                    total_bytes += st.st_size
                    rel_path = str(full_path.relative_to(self.workspace_root)).replace("\\", "/")
                    files.append((rel_path, full_path, st))
                    file_mtimes[rel_path] = st.st_mtime
                except (OSError, PermissionError):
                    continue

        rel_paths = [f[0] for f in files]
        rel_paths_set = set(rel_paths)

        # 2. Language Statistics
        languages = self._detect_languages(files)

        # 3. Framework & Package Manager Manifests
        frameworks, build_commands, project_type, project_purpose = self._analyze_manifests(self.workspace_root, rel_paths_set)

        # 4. Entry Points Discovery
        entry_points = self._detect_entry_points(self.workspace_root, files)

        # 5. Source & Test Directories
        source_dirs, test_dirs, config_files = self._categorize_directories(rel_paths)

        # 6. API Endpoints Extraction
        api_endpoints = self._detect_api_endpoints(self.workspace_root, files)

        # 7. Database & Migrations
        database_info = self._detect_database_info(self.workspace_root, rel_paths_set)

        # 8. Agent & Tool Integrations
        agent_tools = self._detect_agent_tools(self.workspace_root, rel_paths_set)

        # 9. Environment Variable Names (names only!)
        env_vars = self._detect_env_var_names(self.workspace_root, files)

        # 10. Git Information
        git_info = self._detect_git_info(self.workspace_root)

        return {
            "workspace_root": str(self.workspace_root),
            "project_purpose": project_purpose,
            "project_type": project_type,
            "languages": languages,
            "frameworks": frameworks,
            "build_commands": build_commands,
            "entry_points": entry_points,
            "source_dirs": source_dirs,
            "test_dirs": test_dirs,
            "config_files": config_files,
            "api_endpoints": api_endpoints,
            "database_info": database_info,
            "agent_tool_integrations": agent_tools,
            "env_var_names": env_vars,
            "git_info": git_info,
            "file_mtimes": file_mtimes,
            "total_files": len(files),
            "total_bytes": total_bytes,
            "discovery_confidence": 0.95 if project_type.confidence == ConfidenceLevel.VERIFIED else 0.70,
        }

    def _detect_languages(self, files: List[Tuple[str, Path, os.stat_result]]) -> Dict[str, LanguageInfo]:
        counts: Dict[str, int] = {}
        bytes_map: Dict[str, int] = {}
        total_b = 0

        for rel, path, st in files:
            ext = path.suffix.lower()
            lang = LANGUAGE_EXTENSION_MAP.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
                bytes_map[lang] = bytes_map.get(lang, 0) + st.st_size
                total_b += st.st_size

        res = {}
        for lang, count in counts.items():
            b = bytes_map[lang]
            pct = (b / total_b * 100.0) if total_b > 0 else 0.0
            res[lang] = LanguageInfo(name=lang, file_count=count, byte_count=b, percentage=pct)
        return res

    def _analyze_manifests(
        self,
        root: Path,
        rel_set: Set[str],
    ) -> Tuple[List[FrameworkInfo], BuildCommands, EvidenceFinding[ProjectType], EvidenceFinding[str]]:
        frameworks: List[FrameworkInfo] = []
        build_cmds = BuildCommands()
        ptype = EvidenceFinding(ProjectType.UNKNOWN, ConfidenceLevel.UNKNOWN, rationale="No manifest found")
        purpose = EvidenceFinding("Software Application", ConfidenceLevel.INFERRED, rationale="Default assumption")

        # Check Node.js package.json
        if "package.json" in rel_set:
            try:
                pkg_data = json.loads((root / "package.json").read_text(encoding="utf-8", errors="replace"))
                scripts = pkg_data.get("scripts", {})
                if "build" in scripts:
                    build_cmds.build = f"npm run build ({scripts['build']})"
                if "start" in scripts:
                    build_cmds.run = f"npm start ({scripts['start']})"
                elif "dev" in scripts:
                    build_cmds.run = f"npm run dev ({scripts['dev']})"
                if "test" in scripts:
                    build_cmds.test = f"npm test ({scripts['test']})"
                if "lint" in scripts:
                    build_cmds.lint = f"npm run lint ({scripts['lint']})"

                deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                if "electron" in deps:
                    frameworks.append(FrameworkInfo("Electron", "desktop", "package.json dependencies"))
                    ptype = EvidenceFinding(ProjectType.DESKTOP_ELECTRON, ConfidenceLevel.VERIFIED, "package.json", rationale="Electron desktop manifest found")
                if "react" in deps:
                    frameworks.append(FrameworkInfo("React", "frontend", "package.json dependencies"))
                if "next" in deps:
                    frameworks.append(FrameworkInfo("Next.js", "frontend", "package.json dependencies"))
                    ptype = EvidenceFinding(ProjectType.WEB_APPLICATION, ConfidenceLevel.VERIFIED, "package.json", rationale="Next.js web manifest found")
                if "express" in deps:
                    frameworks.append(FrameworkInfo("Express", "backend", "package.json dependencies"))
                    if ptype.value == ProjectType.UNKNOWN:
                        ptype = EvidenceFinding(ProjectType.API_SERVICE, ConfidenceLevel.VERIFIED, "package.json", rationale="Express server found")
                if "jest" in deps or "vitest" in deps:
                    fw_test = "Vitest" if "vitest" in deps else "Jest"
                    frameworks.append(FrameworkInfo(fw_test, "testing", "package.json dependencies"))

                if "description" in pkg_data and pkg_data["description"]:
                    purpose = EvidenceFinding(str(pkg_data["description"]), ConfidenceLevel.VERIFIED, "package.json", rationale="package.json description field")
            except Exception as e:
                log.warning(f"Failed to parse package.json: {e}")

        # Check Python pyproject.toml / requirements.txt / setup.py
        if "pyproject.toml" in rel_set or "requirements.txt" in rel_set or "setup.py" in rel_set:
            req_content = ""
            source_file = "requirements.txt" if "requirements.txt" in rel_set else "pyproject.toml"
            try:
                if "requirements.txt" in rel_set:
                    req_content = (root / "requirements.txt").read_text(encoding="utf-8", errors="replace")
                elif "pyproject.toml" in rel_set:
                    req_content = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")

                req_lower = req_content.lower()
                if "fastapi" in req_lower:
                    frameworks.append(FrameworkInfo("FastAPI", "backend", f"{source_file} dependencies"))
                    if ptype.value in {ProjectType.UNKNOWN, ProjectType.MULTI_LANGUAGE}:
                        ptype = EvidenceFinding(ProjectType.API_SERVICE, ConfidenceLevel.VERIFIED, source_file, rationale="FastAPI framework found")
                if "django" in req_lower:
                    frameworks.append(FrameworkInfo("Django", "backend", f"{source_file} dependencies"))
                    ptype = EvidenceFinding(ProjectType.WEB_APPLICATION, ConfidenceLevel.VERIFIED, source_file, rationale="Django framework found")
                if "flask" in req_lower:
                    frameworks.append(FrameworkInfo("Flask", "backend", f"{source_file} dependencies"))
                if "langgraph" in req_lower or "langchain" in req_lower:
                    frameworks.append(FrameworkInfo("LangGraph", "agent", f"{source_file} dependencies"))
                    if ptype.value in {ProjectType.DESKTOP_ELECTRON, ProjectType.UNKNOWN}:
                        ptype = EvidenceFinding(ProjectType.AI_AGENT_PLATFORM, ConfidenceLevel.VERIFIED, source_file, rationale="LangGraph agent runtime found")
                if "pytest" in req_lower or "pytest.ini" in rel_set:
                    frameworks.append(FrameworkInfo("pytest", "testing", f"{source_file} or pytest.ini"))
                    if not build_cmds.test:
                        build_cmds.test = "pytest"
            except Exception as e:
                log.warning(f"Failed to parse python manifest: {e}")

        # Check Rust Cargo.toml
        if "Cargo.toml" in rel_set:
            frameworks.append(FrameworkInfo("Cargo", "build", "Cargo.toml"))
            if not build_cmds.build:
                build_cmds.build = "cargo build"
            if not build_cmds.test:
                build_cmds.test = "cargo test"
            if ptype.value == ProjectType.UNKNOWN:
                ptype = EvidenceFinding(ProjectType.CLI_TOOL, ConfidenceLevel.INFERRED, "Cargo.toml", rationale="Rust Cargo project found")

        # Check README.md for Purpose fallback
        if purpose.confidence != ConfidenceLevel.VERIFIED and "README.md" in rel_set:
            try:
                lines = (root / "README.md").read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines[:25]:
                    line_s = line.strip()
                    if line_s and not line_s.startswith("#") and not line_s.startswith("[!") and len(line_s) > 20:
                        purpose = EvidenceFinding(line_s, ConfidenceLevel.INFERRED, "README.md", rationale="Extracted from README introductory paragraph")
                        break
            except Exception:
                pass

        # Multi-language detection
        has_py = any(r.endswith(".py") for r in rel_set)
        has_js_ts = any(r.endswith((".ts", ".tsx", ".js", ".jsx")) for r in rel_set)
        if has_py and has_js_ts and ptype.value == ProjectType.UNKNOWN:
            ptype = EvidenceFinding(ProjectType.MULTI_LANGUAGE, ConfidenceLevel.VERIFIED, "workspace", rationale="Both Python and TypeScript/JavaScript source trees detected")

        return frameworks, build_cmds, ptype, purpose

    def _detect_entry_points(self, root: Path, files: List[Tuple[str, Path, os.stat_result]]) -> List[EntryPoint]:
        entrypoints: List[EntryPoint] = []
        for rel, p, st in files:
            # Check main python entrypoints
            if p.suffix == ".py":
                fname = p.name.lower()
                if fname in {"main.py", "app.py", "server.py", "cli.py", "__main__.py"}:
                    entrypoints.append(EntryPoint(rel, "python_main", f"Standard Python entrypoint filename '{fname}'"))
                elif st.st_size < 50_000:
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        if '__name__ == "__main__"' in content or "__name__ == '__main__'" in content:
                            entrypoints.append(EntryPoint(rel, "script_main", "Contains '__name__ == \"__main__\"' guard"))
                    except Exception:
                        pass
            # Check JS/TS entrypoints
            elif p.suffix in {".ts", ".js"}:
                fname = p.name.lower()
                if fname in {"index.ts", "index.js", "main.ts", "server.js", "main.js"}:
                    entrypoints.append(EntryPoint(rel, "javascript_entry", f"Standard JS/TS entrypoint filename '{fname}'"))

        return entrypoints

    def _categorize_directories(self, rel_paths: List[str]) -> Tuple[List[str], List[str], List[str]]:
        source_dirs = set()
        test_dirs = set()
        config_files = set()

        for r in rel_paths:
            parts = r.split("/")
            if len(parts) > 1:
                top_dir = parts[0]
                if top_dir in {"src", "lib", "app", "desktop", "core"}:
                    source_dirs.add(top_dir)
                elif "test" in top_dir.lower():
                    test_dirs.add(top_dir)

            fname = parts[-1].lower()
            if fname in {
                "package.json", "tsconfig.json", "pyproject.toml", "pytest.ini",
                "docker-compose.yml", "dockerfile", "makefile", ".eslintrc",
                ".prettierrc", "alembic.ini"
            }:
                config_files.add(r)

        return sorted(list(source_dirs)), sorted(list(test_dirs)), sorted(list(config_files))

    def _detect_api_endpoints(self, root: Path, files: List[Tuple[str, Path, os.stat_result]]) -> List[ApiEndpoint]:
        endpoints: List[ApiEndpoint] = []
        # Pattern for FastAPI/Flask: @app.get("/path") or @router.post("/path")
        route_pattern = re.compile(r"""@(app|router)\.(get|post|put|delete|patch)\(\s*["']([^"']+)["']""", re.IGNORECASE)

        for rel, p, st in files:
            if p.suffix == ".py" and st.st_size < 200_000:
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                    for m in route_pattern.finditer(text):
                        scope, method, path = m.groups()
                        endpoints.append(ApiEndpoint(
                            method=method.upper(),
                            path=path,
                            handler=f"{rel}:{scope}",
                            source_file=rel,
                            framework="FastAPI/Flask",
                        ))
                except Exception:
                    pass

        return endpoints

    def _detect_database_info(self, root: Path, rel_set: Set[str]) -> Optional[DatabaseSchemaInfo]:
        model_files = []
        orm = "Unknown"
        mig_dir = None

        if "alembic.ini" in rel_set or any("alembic/" in r for r in rel_set):
            orm = "SQLAlchemy / Alembic"
            mig_dir = "alembic"
        elif any("prisma/schema.prisma" in r for r in rel_set):
            orm = "Prisma"
            mig_dir = "prisma/migrations"
        elif any("migrations/0001_initial.py" in r for r in rel_set):
            orm = "Django ORM"
            mig_dir = "migrations"

        for r in rel_set:
            if "model" in r.lower() and r.endswith(".py"):
                model_files.append(r)

        if orm != "Unknown" or model_files:
            return DatabaseSchemaInfo(orm_or_driver=orm, migration_dir=mig_dir, model_files=sorted(model_files)[:20])
        return None

    def _detect_agent_tools(self, root: Path, rel_set: Set[str]) -> List[str]:
        tools = []
        for r in rel_set:
            if "mcp" in r.lower() and (r.endswith(".py") or r.endswith(".json")):
                tools.append(r)
            elif "tool" in r.lower() and r.endswith(".py"):
                tools.append(r)
        return sorted(tools)[:25]

    def _detect_env_var_names(self, root: Path, files: List[Tuple[str, Path, os.stat_result]]) -> List[str]:
        """
        Extract ONLY environment variable names.
        Zero secret leakage: Values are NEVER read or preserved.
        """
        env_names = set()
        env_pattern = re.compile(r"""(?:os\.environ(?:\[|\.get\()|os\.getenv\()[\s*["']([A-Z0-9_]{3,64})["']""")
        node_env_pattern = re.compile(r"""process\.env\.([A-Z0-9_]{3,64})""")

        # Look in .env.example if present
        for rel, p, st in files:
            fname = p.name.lower()
            if fname in {".env.example", ".env.template", ".env.sample"} and st.st_size < 50_000:
                try:
                    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                        line_s = line.strip()
                        if line_s and not line_s.startswith("#") and "=" in line_s:
                            var_name = line_s.split("=")[0].strip()
                            if re.match(r"^[A-Z0-9_]+$", var_name):
                                env_names.add(var_name)
                except Exception:
                    pass
            elif p.suffix in {".py", ".ts", ".js"} and st.st_size < 150_000:
                try:
                    txt = p.read_text(encoding="utf-8", errors="replace")
                    for m in env_pattern.finditer(txt):
                        env_names.add(m.group(1))
                    for m in node_env_pattern.finditer(txt):
                        env_names.add(m.group(1))
                except Exception:
                    pass

        return sorted(list(env_names))

    def _detect_git_info(self, root: Path) -> Dict[str, Any]:
        """Read git branch and status cleanly without altering workspace."""
        git_dir = root / ".git"
        if not git_dir.exists():
            return {"is_git": False}

        try:
            branch = subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=str(root),
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3.0,
            ).strip()
            rev = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(root),
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3.0,
            ).strip()
            return {"is_git": True, "branch": branch, "head": rev[:8]}
        except Exception:
            return {"is_git": True, "branch": "unknown", "head": "unknown"}

