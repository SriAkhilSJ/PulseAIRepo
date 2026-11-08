"""In-turn test discovery, execution, evidence and failure diagnosis.

P0.6.7 closes the P0.6.6 gap where the orchestrator generated a test file but
never executed it: the regression baseline only listed filenames and marked them
PASSING. This module runs the project's real test runner against the actual
workspace, captures attributable evidence, and turns failures into structured
diagnostic input for a bounded repair dispatch.

Design boundaries:

* Discovery is scoped: generated tests, user-named tests, and existing tests
  related to the modified files. The whole repository suite is not run.
* Execution is a list-based subprocess (no ``shell=True``) with the workspace as
  cwd, a hard timeout, and a process-tree kill. Every test path must resolve
  inside the workspace.
* Evidence (command, cwd, exit code, timestamps, stdout/stderr, counts, JUnit
  report path, artifact hashes) is persisted under ``<workspace>/.crusorai``.
* Diagnosis never decides to weaken a test to make it pass. Assertion and
  symbol failures are implementation defects by default; only a test file that
  is syntactically invalid or imports a contract the user explicitly rejected is
  a test defect, and even then the caller must still pass it through the test
  integrity auditor.

OS-level network isolation is not available here. That is reported as a
limitation instead of being claimed as sandboxing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

log = logging.getLogger("crusor.orchestration.test_execution")

_MAX_CAPTURE_CHARS = 200_000
_PROMPT_EXCERPT_CHARS = 6_000
_PY_TEST_PATTERNS = (
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"(^|/)[^/]+_test\.py$"),
)
_JS_TEST_PATTERNS = (
    re.compile(r"\.test\.[cm]?[jt]sx?$"),
    re.compile(r"\.spec\.[cm]?[jt]sx?$"),
)
_TEST_PATH_RE = re.compile(
    r"[A-Za-z0-9_./\\-]*(?:test_[A-Za-z0-9_]+\.py|[A-Za-z0-9_]+_test\.py|"
    r"[A-Za-z0-9_./-]+\.(?:test|spec)\.[cm]?[jt]sx?)\b"
)


def is_test_file(path: str) -> bool:
    normalized = str(path).replace("\\", "/")
    return any(p.search(normalized) for p in _PY_TEST_PATTERNS) or any(
        p.search(normalized) for p in _JS_TEST_PATTERNS
    )


class RunnerKind(str, Enum):
    PYTEST = "pytest"
    UNITTEST = "unittest"
    NPM = "npm"
    NONE = "none"


class FailureCategory(str, Enum):
    IMPLEMENTATION_DEFECT = "IMPLEMENTATION_DEFECT"
    TEST_EXPECTATION_DEFECT = "TEST_EXPECTATION_DEFECT"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    DISCOVERY_FAILURE = "DISCOVERY_FAILURE"
    EXECUTION_INFRASTRUCTURE_FAILURE = "EXECUTION_INFRASTRUCTURE_FAILURE"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass
class TestDiscovery:
    """What will run and why."""

    runner: RunnerKind
    files: List[str] = field(default_factory=list)
    generated: List[str] = field(default_factory=list)
    explicit: List[str] = field(default_factory=list)
    related: List[str] = field(default_factory=list)
    command: List[str] = field(default_factory=list)
    cwd: str = ""
    reason: str = ""
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runner": self.runner.value,
            "files": self.files,
            "generated": self.generated,
            "explicit": self.explicit,
            "related": self.related,
            "command": self.command,
            "cwd": self.cwd,
            "reason": self.reason,
            "warnings": self.warnings,
        }


@dataclass
class ExecutedTest:
    test_id: str
    file: Optional[str]
    status: str  # PASSED / FAILED / ERROR / SKIPPED
    duration_s: Optional[float] = None
    failure_type: Optional[str] = None
    message: Optional[str] = None
    traceback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "file": self.file,
            "status": self.status,
            "duration_s": self.duration_s,
            "failure_type": self.failure_type,
            "message": self.message,
            "traceback": self.traceback,
        }


@dataclass
class TestRunResult:
    runner: str
    command: str
    cwd: str
    exit_code: Optional[int]
    started_at: float
    finished_at: float
    stdout: str = ""
    stderr: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    cases: List[ExecutedTest] = field(default_factory=list)
    report_path: Optional[str] = None
    timed_out: bool = False
    infrastructure_error: Optional[str] = None
    source_hashes: Dict[str, str] = field(default_factory=dict)

    @property
    def executed(self) -> bool:
        return self.total > 0

    @property
    def ok(self) -> bool:
        return (
            self.infrastructure_error is None
            and not self.timed_out
            and self.exit_code == 0
            and self.failed == 0
            and self.errors == 0
        )

    @property
    def failing_cases(self) -> List[ExecutedTest]:
        return [c for c in self.cases if c.status in {"FAILED", "ERROR"}]

    def to_dict(self, *, include_streams: bool = True) -> Dict[str, Any]:
        data = {
            "runner": self.runner,
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(max(0.0, self.finished_at - self.started_at), 3),
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "cases": [c.to_dict() for c in self.cases],
            "report_path": self.report_path,
            "timed_out": self.timed_out,
            "infrastructure_error": self.infrastructure_error,
            "source_hashes": self.source_hashes,
        }
        if include_streams:
            data["stdout"] = self.stdout
            data["stderr"] = self.stderr
        return data


@dataclass
class FailureDiagnosis:
    category: FailureCategory
    reason: str
    target_files: List[str] = field(default_factory=list)
    failing_tests: List[str] = field(default_factory=list)
    repairable: bool = False
    details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "reason": self.reason,
            "target_files": self.target_files,
            "failing_tests": self.failing_tests,
            "repairable": self.repairable,
            "details": self.details,
        }


# --------------------------------------------------------------------------- #
# bounded process execution
# --------------------------------------------------------------------------- #

def _kill_tree(pid: int) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10, stdin=subprocess.DEVNULL,
            )
        else:  # pragma: no cover - posix
            os.killpg(os.getpgid(pid), 9)
    except Exception:
        try:
            os.kill(pid, 9)
        except Exception:
            pass


def _run_bounded(command: Sequence[str], cwd: Path, timeout_s: float, env: Dict[str, str]):
    """Run a list command, kill the whole tree on timeout, never wedge on pipes."""
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=creationflags,
    )
    try:
        out, err = proc.communicate(timeout=timeout_s)
        return proc.returncode, out or "", err or "", False
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            out, err = "", ""
        return None, out or "", err or "", True


def _truncate(text: str, limit: int = _MAX_CAPTURE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n...[truncated]...\n" + text[-limit // 2 :]


_SECRET_RE = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|password)\s*[=:]\s*)[^\s\"']{6,}"
)


def _redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1[redacted]", text)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #

def _candidate_python(workspace: Path) -> List[str]:
    candidates: List[str] = []
    # An explicit interpreter wins: the desktop app can pin the project's
    # runner without guessing which venv the workspace will grow later.
    override = os.environ.get("CRUSORAI_TEST_PYTHON", "").strip()
    if override and Path(override).exists():
        candidates.append(override)
    for rel in (
        ".venv/Scripts/python.exe", "venv/Scripts/python.exe",
        ".venv/bin/python", "venv/bin/python",
    ):
        candidate = workspace / rel
        if candidate.exists():
            candidates.append(str(candidate))
    candidates.append(sys.executable)
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(candidates))


def _has_pytest(python: str, workspace: Path) -> bool:
    try:
        rc, _, _, timed_out = _run_bounded(
            [python, "-c", "import pytest"], workspace, 30.0, dict(os.environ)
        )
        return not timed_out and rc == 0
    except OSError:
        return False


def _project_python(workspace: Path) -> tuple[Optional[str], bool]:
    for candidate in _candidate_python(workspace):
        if _has_pytest(candidate, workspace):
            return candidate, True
    for candidate in _candidate_python(workspace):
        try:
            rc, _, _, timed_out = _run_bounded(
                [candidate, "-c", "import sys"], workspace, 20.0, dict(os.environ)
            )
            if not timed_out and rc == 0:
                return candidate, False
        except OSError:
            continue
    return None, False


def _package_has_test_script(workspace: Path) -> bool:
    package = workspace / "package.json"
    if not package.exists():
        return False
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    scripts = data.get("scripts") or {}
    return bool(scripts.get("test"))


def _related_existing_tests(workspace: Path, modified_files: Iterable[str]) -> List[str]:
    """Existing test files that name or import a modified module (bounded scan)."""
    stems = {
        Path(f).stem for f in modified_files
        if not is_test_file(f) and Path(f).suffix in {".py", ".js", ".ts", ".tsx", ".jsx"}
    }
    if not stems:
        return []
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".crusorai"}
    found: List[str] = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for name in files:
            rel = (Path(root) / name).relative_to(workspace).as_posix()
            if not is_test_file(rel) or len(found) >= 20:
                continue
            test_stem = Path(name).stem
            if any(stem and (stem in test_stem or stem in name) for stem in stems):
                found.append(rel)
                continue
            try:
                content = (Path(root) / name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(stem and stem in content for stem in stems):
                found.append(rel)
    return sorted(dict.fromkeys(found))


def _explicit_tests(prompt: str, workspace: Path) -> List[str]:
    explicit: List[str] = []
    for match in _TEST_PATH_RE.findall(prompt or ""):
        cleaned = match.strip("`'\"()[]<>.,;:").replace("\\", "/")
        if not cleaned or not is_test_file(cleaned):
            continue
        candidate = (workspace / cleaned)
        if candidate.exists() and candidate.resolve().is_relative_to(workspace.resolve()):
            explicit.append(cleaned)
    return list(dict.fromkeys(explicit))


def discover_tests(
    workspace: str | Path,
    *,
    modified_files: Iterable[str],
    prompt: str = "",
    requested_files: Optional[Iterable[str]] = None,
) -> TestDiscovery:
    """Discover the tests that belong to this task and build the runner command."""
    root = Path(workspace).resolve()
    modified = [str(f).replace("\\", "/") for f in modified_files]
    requested = [str(f).replace("\\", "/") for f in (requested_files or [])]

    generated = [f for f in modified if is_test_file(f)]
    explicit = _explicit_tests(prompt, root)
    explicit += [f for f in requested if is_test_file(f)]
    explicit = list(dict.fromkeys(explicit))
    related = [f for f in _related_existing_tests(root, modified) if f not in generated and f not in explicit]

    files = list(dict.fromkeys([*generated, *explicit, *related]))
    warnings: List[str] = []
    # Every file must be inside the workspace; never execute outside it.
    safe_files: List[str] = []
    for rel in files:
        candidate = (root / rel).resolve()
        if not candidate.is_relative_to(root):
            warnings.append(f"refused test path outside workspace: {rel}")
            continue
        if not candidate.exists():
            warnings.append(f"test path does not exist: {rel}")
            continue
        safe_files.append(rel)
    files = safe_files

    if not files:
        return TestDiscovery(
            runner=RunnerKind.NONE, cwd=str(root), reason="no tests discovered",
            warnings=warnings,
        )

    if any(f.endswith(".py") for f in files):
        python, has_pytest = _project_python(root)
        if python is None:
            return TestDiscovery(
                runner=RunnerKind.NONE, files=files, generated=generated,
                explicit=explicit, related=related, cwd=str(root),
                reason="no usable Python interpreter in the workspace",
                warnings=warnings,
            )
        py_files = [f for f in files if f.endswith(".py")]
        if has_pytest:
            report = root / ".crusorai" / "test_reports"
            command = [
                python, "-m", "pytest", "-q", "--tb=short", "--no-header",
                "-p", "no:cacheprovider", "-rf",
                f"--junitxml={report / 'latest.xml'}",
                *py_files,
            ]
            return TestDiscovery(
                runner=RunnerKind.PYTEST, files=py_files, generated=generated,
                explicit=explicit, related=related, command=command,
                cwd=str(root), reason="pytest with generated/explicit/related tests",
                warnings=warnings,
            )
        # unittest needs module names, not arbitrary paths.
        module_names = [
            f[:-3].replace("/", ".") for f in py_files if f.endswith(".py")
        ]
        command = [python, "-m", "unittest", "-v", *module_names]
        return TestDiscovery(
            runner=RunnerKind.UNITTEST, files=py_files, generated=generated,
            explicit=explicit, related=related, command=command,
            cwd=str(root), reason="unittest (pytest unavailable)",
            warnings=warnings,
        )

    if any(f.endswith((".js", ".jsx", ".ts", ".tsx")) for f in files):
        if not _package_has_test_script(root):
            return TestDiscovery(
                runner=RunnerKind.NONE, files=files, generated=generated,
                explicit=explicit, related=related, cwd=str(root),
                reason="javascript tests found but package.json has no test script",
                warnings=warnings,
            )
        npm = shutil.which("npm")
        if not npm:
            return TestDiscovery(
                runner=RunnerKind.NONE, files=files, generated=generated,
                explicit=explicit, related=related, cwd=str(root),
                reason="npm not available", warnings=warnings,
            )
        return TestDiscovery(
            runner=RunnerKind.NPM, files=files, generated=generated,
            explicit=explicit, related=related, command=[npm, "test"],
            cwd=str(root), reason="project npm test script", warnings=warnings,
        )

    return TestDiscovery(
        runner=RunnerKind.NONE, files=files, generated=generated,
        explicit=explicit, related=related, cwd=str(root),
        reason="no supported runner for the discovered test files",
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# execution + parsing
# --------------------------------------------------------------------------- #

def _parse_junit(xml_path: Path) -> tuple[List[ExecutedTest], Dict[str, int]]:
    cases: List[ExecutedTest] = []
    counts = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    try:
        tree = ET.parse(xml_path)
    except (OSError, ET.ParseError):
        return cases, counts
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    for suite in suites:
        for element in suite.iter("testcase"):
            name = element.get("name") or "unknown"
            file_attr = element.get("file")
            classname = element.get("classname")
            if not file_attr and classname and "/" not in classname:
                # pytest may emit only a dotted classname; normalize it to a path
                # so the failure can be mapped back to the module under test.
                file_attr = classname.replace(".", "/") + ".py"
            if not file_attr and "." in name and not name.startswith("test_"):
                # Collection errors are emitted as a pseudo-test named after the
                # test module (e.g. "tests.test_mod") with no file/classname.
                dotted = name.replace(".", "/")
                file_attr = dotted if dotted.endswith(".py") else dotted + ".py"
            test_id = f"{file_attr or classname or ''}::{name}".lstrip(":")
            duration = None
            try:
                duration = float(element.get("time") or "")
            except (TypeError, ValueError):
                pass
            failure = element.find("failure")
            error = element.find("error")
            skipped = element.find("skipped")
            if failure is not None or error is not None:
                node = failure if failure is not None else error
                status = "FAILED" if failure is not None else "ERROR"
                cases.append(ExecutedTest(
                    test_id=test_id,
                    file=file_attr,
                    status=status,
                    duration_s=duration,
                    failure_type=(node.get("type") or "").split(".")[-1] or None,
                    message=(node.get("message") or "")[:4000],
                    traceback=(node.text or "")[:12000],
                ))
            elif skipped is not None:
                cases.append(ExecutedTest(
                    test_id=test_id, file=file_attr, status="SKIPPED",
                    duration_s=duration, message=(skipped.get("message") or "")[:1000],
                ))
            else:
                cases.append(ExecutedTest(
                    test_id=test_id, file=file_attr, status="PASSED", duration_s=duration,
                ))
    counts["total"] = len(cases)
    counts["passed"] = sum(1 for c in cases if c.status == "PASSED")
    counts["failed"] = sum(1 for c in cases if c.status == "FAILED")
    counts["errors"] = sum(1 for c in cases if c.status == "ERROR")
    counts["skipped"] = sum(1 for c in cases if c.status == "SKIPPED")
    return cases, counts


def _parse_text_summary(stdout: str, stderr: str) -> Dict[str, int]:
    text = f"{stdout}\n{stderr}"
    counts = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for key, pattern in (
        ("passed", r"(\d+)\s+passed"),
        ("failed", r"(\d+)\s+failed"),
        ("errors", r"(\d+)\s+error"),
        ("skipped", r"(\d+)\s+skipped"),
    ):
        match = re.search(pattern, text)
        if match:
            counts[key] = int(match.group(1))
    counts["total"] = counts["passed"] + counts["failed"] + counts["errors"] + counts["skipped"]
    return counts


def _parse_text_failures(stdout: str) -> List[ExecutedTest]:
    failures: List[ExecutedTest] = []
    for line in stdout.splitlines():
        match = re.match(r"^(?:FAILED|ERROR)\s+(\S+)(?:\s+-\s+(.*))?$", line.strip())
        if not match:
            continue
        test_id = match.group(1)
        message = (match.group(2) or "")[:2000]
        file_path = test_id.split("::")[0] if "::" in test_id else None
        if file_path is None and (test_id.endswith(".py") or "/" in test_id):
            file_path = test_id
        failures.append(ExecutedTest(
            test_id=test_id,
            file=file_path,
            status="FAILED",
            message=message,
        ))
    return failures


def _npm_counts(stdout: str, stderr: str) -> Dict[str, int]:
    text = f"{stdout}\n{stderr}"
    counts = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for key, patterns in (
        ("passed", (r"(\d+)\s+passing", r"Tests:\s+(\d+)\s+passed", r"(\d+)\s+passed")),
        ("failed", (r"(\d+)\s+failing", r"Tests:\s+(\d+)\s+failed", r"(\d+)\s+failed")),
        ("skipped", (r"(\d+)\s+pending", r"(\d+)\s+skipped")),
    ):
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                counts[key] = int(match.group(1))
                break
    counts["total"] = counts["passed"] + counts["failed"] + counts["skipped"]
    return counts


def run_discovered_tests(
    discovery: TestDiscovery,
    *,
    workspace: str | Path,
    modified_files: Iterable[str],
    timeout_s: float = 300.0,
) -> TestRunResult:
    """Execute a discovery plan and return attributable, bounded evidence."""
    root = Path(workspace).resolve()
    started = time.time()
    if discovery.runner is RunnerKind.NONE:
        return TestRunResult(
            runner=discovery.runner.value,
            command="",
            cwd=str(root),
            exit_code=None,
            started_at=started,
            finished_at=time.time(),
            infrastructure_error=discovery.reason or "no test runner",
        )

    env = dict(os.environ)
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "CI": "1",
        "CRUSORAI_TEST_EXECUTION": "1",
    })
    # Tests are executable input composed by a model. Do not hand them provider
    # credentials or the acceptance bookkeeping: a test that tries to call a
    # provider must fail closed instead of becoming an unmetered dispatch.
    scrubbed = {
        key for key in list(env)
        if key.upper().endswith(("_API_KEY", "_SECRET", "_TOKEN", "_PASSWORD"))
        or key.upper() in {
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
            "CRUSORAI_ACCEPTANCE_RUN_ID", "CRUSORAI_ACCEPTANCE_MAX_DISPATCHES",
            "CRUSORAI_ACCEPTANCE_EVIDENCE_PATH",
        }
    }
    for key in scrubbed:
        env.pop(key, None)
    # Project tests must be able to import the workspace's own modules
    # (``src.foo`` or ``foo``) without the runner guessing sys.path.
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(root) + (os.pathsep + existing_path if existing_path else "")
    env.pop("PYTEST_ADDOPTS", None)
    (root / ".crusorai" / "test_reports").mkdir(parents=True, exist_ok=True)
    command = list(discovery.command)
    display = " ".join(command)
    try:
        rc, out, err, timed_out = _run_bounded(command, root, timeout_s, env)
    except OSError as exc:
        return TestRunResult(
            runner=discovery.runner.value, command=display, cwd=str(root),
            exit_code=None, started_at=started, finished_at=time.time(),
            infrastructure_error=f"{type(exc).__name__}: {exc}",
        )
    finished = time.time()
    out = _truncate(_redact(out))
    err = _truncate(_redact(err))

    report_path = root / ".crusorai" / "test_reports" / "latest.xml"
    cases: List[ExecutedTest] = []
    counts = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    if discovery.runner is RunnerKind.PYTEST and report_path.exists():
        cases, counts = _parse_junit(report_path)
    if counts["total"] == 0:
        if discovery.runner is RunnerKind.NPM:
            counts = _npm_counts(out, err)
        else:
            counts = _parse_text_summary(out, err)
    if not cases and discovery.runner is RunnerKind.PYTEST:
        cases = _parse_text_failures(out)
        if cases and counts["failed"] == 0 and counts["errors"] == 0:
            counts["failed"] = sum(1 for c in cases if c.status == "FAILED")
            counts["total"] = max(counts["total"], counts["failed"])

    hashes: Dict[str, str] = {}
    for rel in [*discovery.files, *[f for f in modified_files if not is_test_file(f)]]:
        candidate = root / rel
        if candidate.exists():
            hashes[rel] = _sha256(candidate)

    infra_error = None
    if timed_out:
        infra_error = f"test command exceeded {timeout_s:.0f}s and was terminated"

    return TestRunResult(
        runner=discovery.runner.value,
        command=display,
        cwd=str(root),
        exit_code=rc,
        started_at=started,
        finished_at=finished,
        stdout=out,
        stderr=err,
        total=counts["total"],
        passed=counts["passed"],
        failed=counts["failed"],
        errors=counts["errors"],
        skipped=counts["skipped"],
        cases=cases,
        report_path=str(report_path) if report_path.exists() else None,
        timed_out=timed_out,
        infrastructure_error=infra_error,
        source_hashes=hashes,
    )


def persist_run(
    workspace: str | Path,
    task_id: str,
    index: int,
    discovery: TestDiscovery,
    result: TestRunResult,
) -> str:
    """Persist the run as evidence next to the workspace's other artifacts."""
    root = Path(workspace).resolve()
    target_dir = root / ".crusorai" / "test_reports"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_task = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)
    path = target_dir / f"{safe_task}_run{index}.json"
    payload = {
        "task_id": task_id,
        "run_index": index,
        "discovery": discovery.to_dict(),
        "result": result.to_dict(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# diagnosis
# --------------------------------------------------------------------------- #

_ALLOWED_REPAIR_CATEGORIES = {
    FailureCategory.IMPLEMENTATION_DEFECT,
    FailureCategory.TEST_EXPECTATION_DEFECT,
}


def _normalized_case_file(case: ExecutedTest) -> str:
    """Best-effort workspace-relative test file for an executed case."""
    raw = case.file or (case.test_id.split("::")[0] if "::" in case.test_id else "")
    raw = str(raw or "").replace("\\", "/")
    if raw and "/" not in raw and "." in raw:
        raw = raw.replace(".", "/") + ".py"
    return raw


def _module_for_test(test_file: Optional[str], sources: Sequence[str]) -> List[str]:
    if not test_file:
        return []
    normalized = str(test_file).replace("\\", "/")
    if "/" not in normalized and "." in normalized:
        normalized = normalized.replace(".", "/") + ".py"
    stem = Path(normalized).stem
    stripped = stem[5:] if stem.startswith("test_") else stem
    if stripped.endswith("_test"):
        stripped = stripped[:-5]
    matches = []
    for source in sources:
        source_stem = Path(source).stem
        if source_stem and (source_stem == stripped or source_stem in stem):
            matches.append(source)
    return matches


def _third_party_module(message: str) -> Optional[str]:
    match = re.search(r"No module named ['\"]([^'\"]+)['\"]", message or "")
    if not match:
        return None
    return match.group(1).split(".")[0]


def classify_failure(
    result: TestRunResult,
    *,
    workspace: str | Path,
    modified_files: Iterable[str],
    generated_test_files: Iterable[str] = (),
    prompt: str = "",
    contract: Any = None,
) -> FailureDiagnosis:
    """Turn a run into a normalized, non-destructive diagnosis."""
    root = Path(workspace).resolve()
    sources = [f for f in modified_files if not is_test_file(f)]
    generated_tests = set(generated_test_files)
    failing = result.failing_cases
    failing_ids = [c.test_id for c in failing]

    if result.runner == RunnerKind.NONE.value:
        return FailureDiagnosis(
            category=FailureCategory.DISCOVERY_FAILURE,
            reason="no tests were collected or no runner could execute them",
            failing_tests=failing_ids,
            details=[{"stderr_excerpt": (result.stderr or result.stdout or "")[-4000:]}],
        )
    if result.total == 0 and result.exit_code not in (0, None):
        text = f"{result.stdout}\n{result.stderr}"
        lowered = text.lower()
        if "modulenotfounderror" in lowered or "no module named" in lowered:
            module = _third_party_module(text)
            project_stems = {Path(f).stem for f in sources}
            category = (
                FailureCategory.IMPLEMENTATION_DEFECT
                if module and module in project_stems
                else FailureCategory.ENVIRONMENT_FAILURE
            )
            test_hit = next(
                (f for f in generated_tests if f.replace("\\", "/") in text.replace("\\", "/")),
                None,
            )
            if category is FailureCategory.IMPLEMENTATION_DEFECT and test_hit:
                return FailureDiagnosis(
                    category=FailureCategory.TEST_EXPECTATION_DEFECT,
                    reason=f"generated test '{test_hit}' imports project module '{module}' by an invalid path",
                    target_files=[test_hit],
                    failing_tests=failing_ids,
                    repairable=True,
                    details=[{"stderr_excerpt": text[-4000:]}],
                )
            return FailureDiagnosis(
                category=category,
                reason=f"collection failed on import: {module or 'unknown module'}",
                failing_tests=failing_ids,
                details=[{"stderr_excerpt": text[-4000:]}],
            )
        if "syntaxerror" in lowered:
            return FailureDiagnosis(
                category=FailureCategory.TEST_EXPECTATION_DEFECT,
                reason="a test file is not syntactically valid",
                target_files=sorted({
                    f for f in generated_tests
                    if f.replace("\\", "/") in text.replace("\\", "/")
                }) or (sorted(generated_tests) if len(generated_tests) == 1 else []),
                failing_tests=failing_ids,
                repairable=bool(generated_tests),
                details=[{"stderr_excerpt": text[-4000:]}],
            )
        if "collected 0 items" in lowered or "no tests ran" in lowered:
            return FailureDiagnosis(
                category=FailureCategory.DISCOVERY_FAILURE,
                reason="the runner collected no tests",
                failing_tests=failing_ids,
                details=[{"stderr_excerpt": text[-4000:]}],
            )
        return FailureDiagnosis(
            category=FailureCategory.EXECUTION_INFRASTRUCTURE_FAILURE,
            reason="the test runner exited before producing a test result",
            failing_tests=failing_ids,
            details=[{"stderr_excerpt": text[-4000:]}],
        )
    if result.timed_out:
        return FailureDiagnosis(
            category=FailureCategory.EXECUTION_INFRASTRUCTURE_FAILURE,
            reason=result.infrastructure_error or "test command timed out",
            failing_tests=failing_ids,
        )
    if result.infrastructure_error and not failing:
        return FailureDiagnosis(
            category=FailureCategory.EXECUTION_INFRASTRUCTURE_FAILURE,
            reason=result.infrastructure_error,
            failing_tests=failing_ids,
        )

    details: List[Dict[str, Any]] = []
    env_failures: List[Dict[str, Any]] = []
    impl_failures: List[Dict[str, Any]] = []
    test_failures: List[Dict[str, Any]] = []
    ambiguous: List[Dict[str, Any]] = []
    targets: List[str] = []
    contract_returns: Set[str] = set()
    if contract is not None:
        for component in getattr(contract, "components", []):
            if getattr(component, "role", "") == "SOURCE" and getattr(component, "returns", None):
                contract_returns.add(str(component.returns))

    for case in failing:
        message = f"{case.failure_type or ''}: {case.message or ''}\n{case.traceback or ''}"
        combined = message
        if len(combined.strip()) < 60:
            # Summary-only cases (collection errors) carry no traceback; the
            # runner stream is the only evidence of why nothing ran.
            combined = f"{combined}\n{result.stdout}\n{result.stderr}"
        lowered = combined.lower()
        modules = _module_for_test(_normalized_case_file(case), sources)
        case_file = _normalized_case_file(case)
        syntax_file = next(
            (f for f in generated_tests
             if f.replace("\\", "/") in combined.replace("\\", "/")),
            None,
        )
        category: FailureCategory
        reason: str
        if "syntaxerror" in lowered:
            if case_file in generated_tests or syntax_file:
                category = FailureCategory.TEST_EXPECTATION_DEFECT
                reason = "generated test file is not syntactically valid"
            else:
                category = FailureCategory.IMPLEMENTATION_DEFECT
                reason = "syntax error in the implementation under test"
        elif "modulenotfounderror" in lowered or "no module named" in lowered:
            module = _third_party_module(combined)
            project_stems = {Path(s).stem for s in sources}
            if module and module in project_stems:
                if case_file in generated_tests:
                    # The user named the import contract; a generated test that
                    # imports the project module by a different path contradicts
                    # it. Repair the TEST, not the module.
                    category = FailureCategory.TEST_EXPECTATION_DEFECT
                    reason = (
                        f"generated test imports project module '{module}' by a path "
                        "that contradicts the requested contract"
                    )
                else:
                    category = FailureCategory.IMPLEMENTATION_DEFECT
                    reason = f"the implementation module '{module}' could not be imported"
            else:
                category = FailureCategory.ENVIRONMENT_FAILURE
                reason = f"missing environment dependency: {module or 'unknown module'}"
        elif "importerror" in lowered or "cannot import name" in lowered:
            category = FailureCategory.IMPLEMENTATION_DEFECT
            reason = "the implementation does not expose the symbol the contract requires"
        elif case.status == "ERROR" and ("fixture" in lowered or "setup" in lowered):
            category = FailureCategory.AMBIGUOUS
            reason = "test setup failed; cause is not attributable from the captured evidence"
        elif "assertionerror" in lowered or case.failure_type == "AssertionError":
            category = FailureCategory.IMPLEMENTATION_DEFECT
            reason = "assertion failure against required behavior"
        elif (
            "did not raise" in lowered
            or lowered.startswith("failed:")
        ):
            # pytest reports a missing expected exception as "Failed: DID NOT
            # RAISE ..." with no AssertionError type. The contract required the
            # error; the implementation did not honor it.
            category = FailureCategory.IMPLEMENTATION_DEFECT
            reason = "behavior contradicted the required contract"
        elif (
            contract_returns & {"int", "str", "bool", "float", "list", "dict"}
            and ("has no attribute" in lowered or "not subscriptable" in lowered)
            and case_file in generated_tests
        ):
            # The contract fixes a primitive return; a generated test calling an
            # attribute of a richer type (P0.6.7: timedelta.total_seconds on an
            # int) contradicts the contract. Repair the test, not the code.
            category = FailureCategory.TEST_EXPECTATION_DEFECT
            reason = (
                "generated test expects a different return type than the "
                f"authoritative contract ({', '.join(sorted(contract_returns))})"
            )
        elif case.failure_type in {"TypeError", "ValueError", "AttributeError", "KeyError", "IndexError", "ZeroDivisionError"}:
            category = FailureCategory.IMPLEMENTATION_DEFECT
            reason = f"implementation raised {case.failure_type}"
        else:
            category = FailureCategory.AMBIGUOUS
            reason = "failure is not attributable to implementation or test from the evidence"

        record = {
            "test_id": case.test_id,
            "file": case_file,
            "failure_type": case.failure_type,
            "message": (case.message or "")[:_PROMPT_EXCERPT_CHARS],
            "traceback": (case.traceback or "")[:_PROMPT_EXCERPT_CHARS],
            "modules_under_test": modules,
            "category": category.value,
            "reason": reason,
        }
        details.append(record)
        if category is FailureCategory.ENVIRONMENT_FAILURE:
            env_failures.append(record)
        elif category is FailureCategory.TEST_EXPECTATION_DEFECT:
            test_failures.append(record)
        elif category is FailureCategory.IMPLEMENTATION_DEFECT:
            impl_failures.append(record)
            for module in modules:
                if module not in targets:
                    targets.append(module)
        else:
            ambiguous.append(record)

    if env_failures and not impl_failures and not test_failures:
        return FailureDiagnosis(
            category=FailureCategory.ENVIRONMENT_FAILURE,
            reason="; ".join(sorted({r["reason"] for r in env_failures})),
            failing_tests=failing_ids, details=details,
        )
    if ambiguous and not impl_failures and not test_failures:
        return FailureDiagnosis(
            category=FailureCategory.AMBIGUOUS,
            reason="; ".join(sorted({r["reason"] for r in ambiguous})),
            failing_tests=failing_ids, details=details,
        )
    if env_failures or ambiguous:
        return FailureDiagnosis(
            category=FailureCategory.AMBIGUOUS,
            reason="mixed failure categories; refusing an automatic repair",
            failing_tests=failing_ids, details=details,
        )
    if test_failures and not impl_failures:
        test_targets = sorted({
            f for record in test_failures
            for f in generated_tests
            if record.get("file") == f
            or f in (record.get("message") or "")
            or f in (record.get("traceback") or "")
        })
        if not test_targets and len(generated_tests) == 1:
            test_targets = sorted(generated_tests)
        return FailureDiagnosis(
            category=FailureCategory.TEST_EXPECTATION_DEFECT,
            reason="; ".join(sorted({r["reason"] for r in test_failures})),
            target_files=test_targets,
            failing_tests=failing_ids,
            repairable=bool(test_targets),
            details=details,
        )
    return FailureDiagnosis(
        category=FailureCategory.IMPLEMENTATION_DEFECT,
        reason="; ".join(sorted({r["reason"] for r in impl_failures})) or "implementation defect",
        target_files=[t for t in targets if t],
        failing_tests=failing_ids,
        repairable=bool(targets),
        details=details,
    )


def format_repair_evidence(result: TestRunResult, diagnosis: FailureDiagnosis, *, limit: int = _PROMPT_EXCERPT_CHARS) -> str:
    """Bounded, redacted failure text safe to send to a provider."""
    chunks: List[str] = []
    chunks.append(f"Test command: {result.command}")
    chunks.append(f"Exit code: {result.exit_code}; passed={result.passed}; failed={result.failed}; errors={result.errors}")
    for detail in diagnosis.details:
        chunks.append(
            f"\n--- {detail.get('test_id')} ({detail.get('category')}) ---\n"
            f"{detail.get('message') or ''}\n{detail.get('traceback') or ''}"
        )
    if not diagnosis.details:
        excerpt = (result.stdout or result.stderr or "")[-limit:]
        chunks.append(excerpt)
    text = "\n".join(chunks)
    if len(text) > limit:
        text = text[: limit // 2] + "\n...[truncated]...\n" + text[-limit // 2 :]
    return _redact(text)


def related_test_map(
    executed: TestRunResult,
    *,
    modified_files: Iterable[str],
    requirement_files: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """Map requirement id -> executed test ids that exercise its files."""
    sources = [f for f in modified_files if not is_test_file(f)]
    mapping: Dict[str, List[str]] = {}
    for req_id, files in requirement_files.items():
        req_sources = [f for f in files if not is_test_file(f)]
        req_tests = {f for f in files if is_test_file(f)}
        test_ids: List[str] = []
        for case in executed.cases:
            case_file = _normalized_case_file(case)
            if case_file in req_tests:
                test_ids.append(case.test_id)
                continue
            modules = _module_for_test(case_file, req_sources or sources)
            if modules or any(Path(f).stem in case_file for f in req_sources):
                test_ids.append(case.test_id)
        mapping[req_id] = list(dict.fromkeys(test_ids))
    return mapping
