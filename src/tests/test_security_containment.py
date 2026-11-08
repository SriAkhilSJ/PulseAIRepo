"""Phase 1/1.1 security containment and guard-hardening tests.

Provider-free. No Electron, no external process execution, no real Windows
security API call, no write outside the repository.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = ROOT / "src" / "security" / "sandbox" / "windows.py"

FORBIDDEN = {
    "SetSecurityInfo": re.compile(r"SetSecurityInfo"),
    "Everyone_GA_SDDL": re.compile(r"WD\)\(A;OICI;GA"),
    "runner.exe": re.compile(r"runner\.exe", re.IGNORECASE),
    "repair_winsta": re.compile(r"repair_winsta"),
    "ExecutionPolicy Bypass": re.compile(r"-ExecutionPolicy\s+Bypass", re.IGNORECASE),
    "trigger_repairs": re.compile(r"_trigger_repairs"),
    "diag_pid": re.compile(r"_diag_pid"),
    "dev_path": re.compile(r"[cC]:[\\/]+Users[\\/]+Administrator[\\/]+Downloads[\\/]+CRUSORAI"),
    "win32security_import": re.compile(r"^\s*(import|from)\s+win32security\b", re.MULTILINE),
}

SCRIPT_PAYLOADS = {
    "SetSecurityInfo": FORBIDDEN["SetSecurityInfo"],
    "Everyone_GA_SDDL": FORBIDDEN["Everyone_GA_SDDL"],
    "runner.exe": FORBIDDEN["runner.exe"],
    "repair_winsta": FORBIDDEN["repair_winsta"],
    "ExecutionPolicy Bypass": FORBIDDEN["ExecutionPolicy Bypass"],
    "trigger_repairs": FORBIDDEN["trigger_repairs"],
    "diag_pid": FORBIDDEN["diag_pid"],
}

# Documented P1 findings from Phase 0/1: standalone patch/audit scripts that
# embed the original developer path. These are not import-time runtime payloads
# and are deliberately preserved as explicit items, not ignored by a blanket
# directory exclusion.
KNOWN_P1_DEV_PATH_FILES = {
    "scripts/dump_raw_ledger_records.py",
    "scripts/find_config_uses.py",
    "scripts/generate_system_message_files.py",
    "scripts/patch_extract_workspace_fail_closed.py",
    "scripts/patch_file_tools.py",
    "scripts/reconcile_phase931_finops.py",
    "scripts/restore_read_resolve.py",
    "scripts/secret_scan_p0_6_6.py",
    "scripts/update_benchmark_script.py",
    "scripts/update_file_tools_guidance.py",
    "scripts/update_task_validation_patterns.py",
}


def _iter_runtime_python():
    roots = [
        ROOT / "src",
        ROOT / "benchmarks",
        ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai",
    ]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            yield path


def _iter_scripts():
    root = ROOT / "scripts"
    if not root.exists():
        return
    for path in root.rglob("*.py"):
        yield path


def _security_call_lines(path: Path) -> set[int]:
    """Line numbers of SetSecurityInfo calls inside _grant_to_object only."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_grant_to_object":
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "SetSecurityInfo"
                ):
                    allowed.add(sub.lineno)
    return allowed


def _sandbox_allowed_lines() -> set[int]:
    if not SANDBOX.exists():
        return set()
    text = SANDBOX.read_text(encoding="utf-8")
    if "ALL APPLICATION PACKAGES" not in text or "WD)(A;OICI;GA" in text:
        return set()
    return _security_call_lines(SANDBOX)


def test_static_guard_rejects_removed_payloads() -> None:
    allowed = _sandbox_allowed_lines()
    findings: list[str] = []
    for path in _iter_runtime_python():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, rx in FORBIDDEN.items():
            for line_no, line in enumerate(text.splitlines(), 1):
                if not rx.search(line):
                    continue
                if (
                    name == "SetSecurityInfo"
                    and path.resolve() == SANDBOX.resolve()
                    and line_no in allowed
                ):
                    continue
                findings.append(f"{rel}:{line_no}: {name}")
    assert not findings, "forbidden security payload returned:\n" + "\n".join(findings)


def test_sandbox_allowlist_is_narrow() -> None:
    allowed = _sandbox_allowed_lines()
    assert allowed, "the documented AppContainer call was not found"
    text = SANDBOX.read_text(encoding="utf-8")
    assert "ALL APPLICATION PACKAGES" in text
    assert "WD)(A;OICI;GA" not in text


def test_sandbox_allowlist_does_not_hide_calls_elsewhere(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def _grant_to_object():\n"
        "    dll.SetSecurityInfo()\n"
        "\n"
        "def other():\n"
        "    dll.SetSecurityInfo()\n",
        encoding="utf-8",
    )
    assert _security_call_lines(sample) == {2}


def test_repair_scripts_are_gone() -> None:
    assert not (ROOT / "scripts" / "repair_winsta.py").exists()
    assert not (ROOT / "scripts" / "repair_winsta.ps1").exists()


def test_scripts_have_no_repair_payloads() -> None:
    findings: list[str] = []
    for path in _iter_scripts():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, rx in SCRIPT_PAYLOADS.items():
            for line_no, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    findings.append(f"{rel}:{line_no}: {name}")
    assert not findings, "repair payload returned in scripts:\n" + "\n".join(findings)


def test_known_p1_dev_paths_are_documented() -> None:
    found = set()
    for path in _iter_scripts():
        if FORBIDDEN["dev_path"].search(path.read_text(encoding="utf-8", errors="replace")):
            found.add(path.relative_to(ROOT).as_posix())
    assert found == KNOWN_P1_DEV_PATH_FILES, (
        "the documented P1 dev-path set changed; update the audit record:\n"
        f"new={sorted(found - KNOWN_P1_DEV_PATH_FILES)}\n"
        f"gone={sorted(KNOWN_P1_DEV_PATH_FILES - found)}"
    )


def _load_checkup():
    path = ROOT / "scripts" / "agent_core_checkup.py"
    spec = importlib.util.spec_from_file_location("phase1_agent_core_checkup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_package(tmp_path: Path, name: str, code: str) -> Path:
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text(code, encoding="utf-8")
    return pkg


def _probe(tmp_path: Path, name: str, code: str) -> dict:
    _make_package(tmp_path, name, code)
    return _load_checkup().run_guarded_import_probe((name,), extra_path=str(tmp_path))


def test_import_purity_of_context_modules() -> None:
    mod = _load_checkup()
    result = mod.run_guarded_import_probe(
        ("src.context.vector_memory", "src.context.context_engine"),
    )
    assert result["violations"] == [], result["violations"]
    for name in ("src.context.vector_memory", "src.context.context_engine"):
        assert not any(err.startswith(name + ":") for err in result["errors"]), result["errors"]


def test_full_guarded_import_surface() -> None:
    result = _load_checkup().run_guarded_import_probe()
    assert result["returncode"] == 0, result
    assert result["probe_error"] == "", result["probe_error"]
    assert result["violations"] == [], result["violations"]
    assert result["ok"] is True, result


def test_sanitizer_redacts_and_bounds() -> None:
    from src.context.engine import (
        MEMORY_CONTEXT_MAX_CHARS,
        _MEMORY_CONTEXT_TRUNCATION_MARKER,
        sanitize_memory_context,
    )

    secret = "AKIAIOSFODNN7EXAMPLE"
    out = sanitize_memory_context(f"key={secret} end")
    assert secret not in out

    url = "https://alice:s3cr3t-pass@example.com/path"
    out = sanitize_memory_context(url)
    assert "s3cr3t-pass" not in out

    long_text = "x" * (MEMORY_CONTEXT_MAX_CHARS + 5_000)
    out = sanitize_memory_context(long_text)
    assert _MEMORY_CONTEXT_TRUNCATION_MARKER in out
    assert len(out) < len(long_text)


def test_sanitizer_is_fail_closed() -> None:
    from src.context.engine import sanitize_memory_context

    with patch(
        "src.utils.redact.redact_sensitive_text",
        side_effect=RuntimeError("redactor unavailable"),
    ):
        with pytest.raises(RuntimeError) as excinfo:
            sanitize_memory_context("secret=AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in str(excinfo.value)


def test_sanitizer_has_no_windows_or_diagnostic_side_effects() -> None:
    from src.context.engine import sanitize_memory_context

    with patch("ctypes.WinDLL", side_effect=AssertionError("WinDLL must not be called")):
        assert sanitize_memory_context("hello") == "hello"


PROCESS_CASES = [
    ("subprocess.run", "import subprocess\nsubprocess.run(['echo', 'x'])\n"),
    ("subprocess.Popen", "import subprocess\nsubprocess.Popen(['echo', 'x'])\n"),
    ("subprocess.call", "import subprocess\nsubprocess.call(['echo', 'x'])\n"),
    ("subprocess.check_call", "import subprocess\nsubprocess.check_call(['echo', 'x'])\n"),
    ("subprocess.check_output", "import subprocess\nsubprocess.check_output(['echo', 'x'])\n"),
    ("os.system", "import os\nos.system('echo x')\n"),
    ("os.popen", "import os\nos.popen('echo x')\n"),
    ("os.execv", "import os\nos.execv('x', [])\n"),
    ("os.spawnv", "import os\nos.spawnv(0, 'x', [])\n"),
    ("asyncio.create_subprocess_exec", "import asyncio\nasyncio.create_subprocess_exec('x')\n"),
    (
        "multiprocessing.Process.start",
        "import multiprocessing\nmultiprocessing.Process(target=lambda: None).start()\n",
    ),
]


@pytest.mark.parametrize("label, code", PROCESS_CASES)
def test_process_guard_blocks(label: str, code: str, tmp_path: Path) -> None:
    result = _probe(tmp_path, "proc_case", code)
    assert label in result["violations"], result


@pytest.mark.skipif(not hasattr(os, "startfile"), reason="Windows-only API")
def test_process_guard_blocks_startfile(tmp_path: Path) -> None:
    result = _probe(tmp_path, "proc_startfile", "import os\nos.startfile('x')\n")
    assert "os.startfile" in result["violations"]


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX-only API")
def test_process_guard_blocks_fork(tmp_path: Path) -> None:
    result = _probe(tmp_path, "proc_fork", "import os\nos.fork()\n")
    assert "os.fork" in result["violations"]


def test_write_guard_blocks_open(tmp_path: Path) -> None:
    target = tmp_path / "open.txt"
    result = _probe(tmp_path, "write_open", f"open({str(target)!r}, 'w').write('x')\n")
    assert any(item.startswith("write:") for item in result["violations"]), result
    assert not target.exists()


def test_write_guard_blocks_io_open(tmp_path: Path) -> None:
    target = tmp_path / "io.txt"
    result = _probe(tmp_path, "write_io", f"import io\nio.open({str(target)!r}, 'w')\n")
    assert any(item.startswith("write:") for item in result["violations"]), result
    assert not target.exists()


def test_write_guard_blocks_pathlib_write_text(tmp_path: Path) -> None:
    target = tmp_path / "path.txt"
    result = _probe(
        tmp_path, "write_path",
        f"from pathlib import Path\nPath({str(target)!r}).write_text('x')\n",
    )
    assert any(item.startswith("write:") for item in result["violations"]), result
    assert not target.exists()


def test_write_guard_blocks_os_open(tmp_path: Path) -> None:
    target = tmp_path / "os.txt"
    result = _probe(
        tmp_path, "write_os",
        f"import os\nos.open({str(target)!r}, os.O_CREAT | os.O_WRONLY)\n",
    )
    assert any(item.startswith("write:") for item in result["violations"]), result
    assert not target.exists()


def test_write_guard_rejects_sibling_prefix_collision(tmp_path: Path) -> None:
    sibling = Path(str(ROOT) + "_sibling_probe") / "evil.txt"
    result = _probe(
        tmp_path, "write_sibling",
        f"open({str(sibling)!r}, 'w')\n",
    )
    assert any(item.startswith("write:") for item in result["violations"]), result
    assert not sibling.exists()


def _cdll_call(api: str, args: str = "0, 0, 0, 0, 0, 0, 0") -> str:
    lib = "kernel32" if os.name == "nt" else None
    return f"import ctypes\ndll = ctypes.CDLL({lib!r})\ndll.{api}({args})\n"


def test_ctypes_security_api_guard(tmp_path: Path) -> None:
    result = _probe(tmp_path, "bad_api", _cdll_call("SetSecurityInfo"))
    assert "security-api:SetSecurityInfo" in result["violations"], result


def test_ctypes_named_security_api_guard(tmp_path: Path) -> None:
    result = _probe(tmp_path, "bad_api_named", _cdll_call("SetNamedSecurityInfoW"))
    assert "security-api:SetNamedSecurityInfoW" in result["violations"], result


@pytest.mark.skipif(not hasattr(__import__("ctypes"), "WinDLL"), reason="Windows-only loader")
def test_ctypes_windll_security_api_guard(tmp_path: Path) -> None:
    result = _probe(
        tmp_path, "bad_api_windll",
        "import ctypes\n"
        "dll = ctypes.WinDLL('advapi32')\n"
        "dll.SetUserObjectSecurity(0, 0, 0)\n",
    )
    assert "security-api:SetUserObjectSecurity" in result["violations"], result


def test_checkup_guard_catches_win32_security_import(tmp_path: Path) -> None:
    result = _probe(tmp_path, "bad_win32", "import win32security\n")
    assert "import:win32security" in result["violations"], result


def test_probe_reports_crashed_child(tmp_path: Path) -> None:
    result = _probe(tmp_path, "hard_exit", "import os\nos._exit(3)\n")
    assert result["ok"] is False, result
    assert result["returncode"] != 0, result
    assert result["probe_error"], result


def test_probe_classifies_import_error_as_non_security(tmp_path: Path) -> None:
    result = _probe(tmp_path, "import_error", "raise RuntimeError('optional dep missing')\n")
    assert result["violations"] == [], result
    assert result["errors"], result
    assert result["ok"] is True, result
