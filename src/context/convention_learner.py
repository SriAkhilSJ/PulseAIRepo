
"""
Project Convention Learner for PulseCodeAI
==========================================
Scans the codebase to detect coding patterns, then injects them
into the agent's context so it writes code in YOUR style, not generic style.

What this learns:
- Test framework (pytest, unittest, jest, etc.)
- Linting/formatting tools (black, ruff, prettier)
- Import style (absolute vs relative, ordering)
- Naming conventions (snake_case vs camelCase prevalence)
- Docstring style (Google, NumPy, reST)
- Type hint usage
- Preferred web frameworks, ORMs, etc.
"""
import json
import os
import re
from pathlib import Path
from typing import Any

from src.context.bounded_scan import ContextBudget, scan_files

class ConventionLearner:
    """
    Learns and remembers project conventions from file scanning.
    """
    def __init__(self, storage_path: str | None = None):
        if storage_path is None:
            home = os.path.expanduser("~")
            pulse_dir = os.path.join(home, ".pulseai")
            os.makedirs(pulse_dir, exist_ok=True)
            self.storage_path = os.path.join(pulse_dir, "conventions.json")
        else:
            self.storage_path = storage_path

        self._conventions: dict[str, Any] = {}
        self._last_scan: str | None = None
        self._load()
        self._py_cache: tuple[str, list[Path]] | None = None
        self._py_report = None
        self._last_budget: ContextBudget | None = None
        self.thread_id_hint: str | None = None

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._conventions = data.get("conventions", {})
            self._last_scan = data.get("last_scan")
        except Exception:
            self._conventions = {}

    def _save(self) -> None:
        try:
            data = {
                "conventions": self._conventions,
                "last_scan": self._last_scan,
                "version": "1.0",
            }
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        except Exception:
            pass

    def scan_workspace(self, workspace: str = ".", budget: ContextBudget | None = None) -> dict[str, Any]:
        """
        Scan the workspace for conventions. Call this once per session
        or when the project structure changes significantly.

        ``budget`` (P1): the shared initial-context deadline; every sample
        scan derives its limits and stop predicate from it.
        """
        budget = budget or ContextBudget()
        self._last_budget = budget
        self._active_budget = budget
        root = Path(workspace)
        conventions: dict[str, Any] = {}

        # --- Test Framework ---
        conventions["test_framework"] = self._detect_test_framework(root)

        # --- Linting / Formatting ---
        conventions["formatting"] = self._detect_formatting_tools(root)

        # --- Import Style ---
        conventions["import_style"] = self._detect_import_style(root)

        # --- Naming Conventions ---
        conventions["naming"] = self._detect_naming_conventions(root)

        # --- Docstring Style ---
        conventions["docstrings"] = self._detect_docstring_style(root)

        # --- Type Hints ---
        conventions["type_hints"] = self._detect_type_hints(root)

        # --- Preferred Frameworks ---
        conventions["frameworks"] = self._detect_frameworks(root)

        # --- Language / Runtime ---
        conventions["language"] = self._detect_language(root)

        self._conventions = conventions
        self._last_scan = str(root.resolve())
        self._save()
        self._emit_degraded_scan(budget)
        return conventions

    def _emit_degraded_scan(self, budget: ContextBudget | None = None) -> None:
        """Surface a truncated convention scan as a structured runtime.degraded
        receipt (real counts, emitted ONCE per shared budget).

        Inside an engine build (``collect_receipts``) the walker only RECORDS
        its component summary — the engine emits ONE aggregate build receipt
        afterwards. Standalone the walker emits its own receipt. Zero-value
        receipts are honest evidence of deadline exhaustion and are NEVER
        suppressed.
        """
        report = getattr(self, "_py_report", None)
        if report is None or not report.truncated:
            return
        budget = budget or self._last_budget or ContextBudget()
        if getattr(budget, "collect_receipts", False):
            budget.record_component("convention_learner", report)
            return
        budget.emit_degraded({
            "thread_id": self.thread_id_hint or "unknown",
            "component": "convention_learner",
            "reason": "context scan bounded",
            "error": f"convention scan {report.summarize()}",
            "files_considered": report.considered,
            "files_read": budget.read_files,
            "bytes_read": budget.read_bytes,
            "elapsed_ms": int(budget.elapsed * 1000),
            "skipped_generated": (
                report.skipped_dirs + report.skipped_generated + report.skipped_gitignore
            ),
            "skipped_oversized": report.skipped_oversize,
            "skipped_binary": report.skipped_binary,
            "cancelled": budget.cancelled,
        })

    def _read_sample(self, f: Path) -> str | None:
        """Read one convention-sample file through the shared physical-read
        ledger. Returns None (declined) when the global allowance is
        exhausted, so convention sampling can never read past the cap."""
        from src.context.bounded_scan import bounded_read_text
        return bounded_read_text(f, getattr(self, "_active_budget", None))

    def _read_config(self, path: Path) -> str | None:
        """Read a small config file (pyproject.toml, requirements.txt, ...)
        through the shared physical-read ledger, exactly like sample reads.
        Returns None when declined or unreadable."""
        from src.context.bounded_scan import bounded_read_text
        return bounded_read_text(path, getattr(self, "_active_budget", None))

    def get_conventions_text(self, workspace: str = ".", budget: ContextBudget | None = None) -> str:
        """
        Return conventions as a formatted text block for the context engine.

        ``budget`` (P1): the shared initial-context deadline.
        """
        # Auto-scan if we have no conventions or workspace changed
        if not self._conventions or self._last_scan != str(Path(workspace).resolve()):
            self.scan_workspace(workspace, budget)

        if not self._conventions:
            return ""

        lines = ["=== PROJECT CONVENTIONS ==="]
        lines.append("Write code that matches the existing codebase style.\n")

        tf = self._conventions.get("test_framework")
        if tf and tf != "unknown":
            lines.append(f"- **Testing:** Use {tf}")

        fmt = self._conventions.get("formatting")
        if fmt:
            tools = [k for k, v in fmt.items() if v]
            if tools:
                lines.append(f"- **Formatting:** {', '.join(tools)}")

        imp = self._conventions.get("import_style")
        if imp:
            lines.append(f"- **Imports:** {imp.get('style', 'standard')}")

        naming = self._conventions.get("naming")
        if naming:
            lines.append(f"- **Naming:** {naming.get('dominant', 'mixed')}")

        docs = self._conventions.get("docstrings")
        if docs and docs != "unknown":
            lines.append(f"- **Docstrings:** {docs}")

        hints = self._conventions.get("type_hints")
        if hints:
            lines.append(f"- **Type hints:** {'Used' if hints else 'Not commonly used'}")

        fw = self._conventions.get("frameworks")
        if fw:
            lines.append(f"- **Frameworks detected:** {', '.join(fw)}")

        lang = self._conventions.get("language")
        if lang:
            lines.append(f"- **Primary language:** {lang}")

        lines.append("\nWhen creating or editing files, follow these conventions.")
        return "\n".join(lines)

    # ---------------------------------------------------------
    # Detection helpers
    # ---------------------------------------------------------

    def _sample_py(self, root: Path, limit: int, budget: ContextBudget | None = None) -> list[Path]:
        """Bounded .py sample (≤ limit files); reused across detectors so the
        convention scan never re-walks the tree per heuristic. The underlying
        scan honors the P1 budgets (files/bytes/elapsed/symlinks/skips) and
        the shared ContextBudget deadline.
        """
        budget = budget or getattr(self, "_active_budget", None) or ContextBudget()
        if self._py_cache is None or self._py_cache[0] != str(root.resolve()):
            iterator, report = scan_files(
                root,
                limits=budget.to_limits(),
                extensions={".py"},
                should_stop=budget.should_stop,
                priority=True,
            )
            self._py_cache = (str(root.resolve()), list(iterator))
            self._py_report = report
            # P1-fix: fold this scan's consumption into the shared pool so
            # the engine's other walkers (and this learner's later scans)
            # see only the remaining allowance.
            budget.absorb(report)
        return self._py_cache[1][:limit]

    def _detect_test_framework(self, root: Path) -> str:
        if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
            text = self._read_config(root / "pyproject.toml")
            if text is not None and "[tool.pytest" in text:
                return "pytest"

        test_files = [
            f for f in self._sample_py(root, 200)
            if f.name.startswith("test_") or f.name.endswith("_test.py")
        ]
        if not test_files:
            return "unknown"

        pytest_count = 0
        unittest_count = 0

        for f in test_files[:20]:
            text = self._read_sample(f)
            if text is None:
                continue
            if "import pytest" in text or "def test_" in text:
                pytest_count += 1
            if "import unittest" in text or "class Test" in text:
                unittest_count += 1

        if pytest_count > unittest_count:
            return "pytest"
        if unittest_count > pytest_count:
            return "unittest"
        return "pytest" if pytest_count > 0 else "unknown"

    def _detect_formatting_tools(self, root: Path) -> dict[str, bool]:
        tools = {"black": False, "ruff": False, "prettier": False, "eslint": False}
        if (root / "pyproject.toml").exists():
            text = self._read_config(root / "pyproject.toml")
            if text is not None:
                if "black" in text:
                    tools["black"] = True
                if "ruff" in text:
                    tools["ruff"] = True

        if (root / ".prettierrc").exists() or (root / ".prettierrc.json").exists():
            tools["prettier"] = True

        if (root / ".eslintrc").exists() or (root / "eslint.config").exists():
            tools["eslint"] = True

        return tools

    def _detect_import_style(self, root: Path) -> dict[str, Any]:
        py_files = self._sample_py(root, 30)
        absolute = 0
        relative = 0
        for f in py_files:
            text = self._read_sample(f)
            if text is None:
                continue
            if "from ." in text or "from .." in text:
                relative += text.count("from .")
            absolute += text.count("import ")

        total = absolute + relative
        if total == 0:
            return {"style": "standard"}

        rel_pct = relative / total if total else 0
        if rel_pct > 0.3:
            return {"style": "mixed (absolute + relative)", "relative_ratio": round(rel_pct, 2)}
        return {"style": "absolute imports preferred"}

    def _detect_naming_conventions(self, root: Path) -> dict[str, Any]:
        py_files = self._sample_py(root, 30)
        snake = 0
        camel = 0
        pascal = 0
        for f in py_files:
            text = self._read_sample(f)
            if text is None:
                continue
            # Functions: snake_case vs camelCase
            funcs = re.findall(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", text)
            for name in funcs:
                if "_" in name and name.islower():
                    snake += 1
                elif "_" not in name and name[0].islower():
                    camel += 1
            # Classes: PascalCase
            classes = re.findall(r"class\s+([A-Z][a-zA-Z0-9]*)\s*[:\(]", text)
            pascal += len(classes)

        dominant = "mixed"
        if snake > camel and snake > pascal:
            dominant = "snake_case for functions, PascalCase for classes"
        elif camel > snake:
            dominant = "camelCase"
        return {"dominant": dominant, "snake_case": snake, "camelCase": camel, "PascalCase": pascal}

    def _detect_docstring_style(self, root: Path) -> str:
        py_files = self._sample_py(root, 20)
        google = 0
        numpy = 0
        rest = 0
        for f in py_files:
            text = self._read_sample(f)
            if text is None:
                continue
            if 'Args:' in text or 'Returns:' in text:
                google += 1
            if 'Parameters' in text or '----------' in text:
                numpy += 1
            if ':param' in text or ':return:' in text:
                rest += 1

        if google > numpy and google > rest:
            return "Google style"
        if numpy > google and numpy > rest:
            return "NumPy style"
        if rest > google and rest > numpy:
            return "reStructuredText (Sphinx) style"
        return "unknown"

    def _detect_type_hints(self, root: Path) -> bool:
        py_files = self._sample_py(root, 20)
        hint_count = 0
        total_funcs = 0
        for f in py_files:
            text = self._read_sample(f)
            if text is None:
                continue
            funcs = re.findall(r"def\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)\s*(->\s*\w+)?\s*:", text)
            total_funcs += len(funcs)
            hint_count += sum(1 for m in funcs if m and "->" in m)

        return hint_count > total_funcs * 0.3 if total_funcs > 0 else False

    def _detect_frameworks(self, root: Path) -> list[str]:
        frameworks = []
        req_files = [
            root / "requirements.txt",
            root / "pyproject.toml",
            root / "package.json",
        ]
        for req in req_files:
            if not req.exists():
                continue
            text = self._read_config(req)
            if text is None:
                continue
            text = text.lower()
            if "fastapi" in text:
                frameworks.append("FastAPI")
            if "flask" in text:
                frameworks.append("Flask")
            if "django" in text:
                frameworks.append("Django")
            if "sqlalchemy" in text or "alembic" in text:
                frameworks.append("SQLAlchemy")
            if "react" in text:
                frameworks.append("React")
            if "next" in text:
                frameworks.append("Next.js")
            if "express" in text:
                frameworks.append("Express")
        return list(dict.fromkeys(frameworks))  # deduplicate, preserve order

    def _count_files(self, root: Path, exts: set[str], budget: ContextBudget | None = None) -> int:
        """Bounded count for the given extensions (P1). On huge trees the
        count is a lower bound (budgets cap the walk); language dominance is
        still decided consistently on the sampled prefix.

        The ``.py`` count REUSES the single ``_sample_py`` scan (no duplicate
        tree walk); only non-``.py`` extension sets trigger a fresh scan.
        """
        budget = budget or getattr(self, "_active_budget", None) or ContextBudget()
        if exts == {".py"}:
            return len(self._sample_py(root, 2**31))
        it, report = scan_files(
            root, limits=budget.to_limits(), extensions=exts,
            should_stop=budget.should_stop,
        )
        count = sum(1 for _ in it)
        budget.absorb(report)
        return count

    def _detect_language(self, root: Path) -> str:
        py_count = self._count_files(root, {".py"})
        js_count = self._count_files(root, {".js", ".ts"})
        if py_count > js_count:
            return "Python"
        if js_count > py_count:
            return "JavaScript/TypeScript"
        return "Unknown"
