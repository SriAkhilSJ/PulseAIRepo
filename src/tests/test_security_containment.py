"""Phase 1 security containment regression tests.

These tests are provider-free and do not launch Electron. They prove that the
removed import-time Windows payloads cannot return, that the context facade is
import-safe, that memory sanitization is fail-closed, and that the agent-core
checkup imports modules only under a safety guard.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]

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

# The AppContainer sandbox intentionally grants a narrow, non-Everyone ACE to
# ALL APPLICATION PACKAGES so unpackaged Win32 children can initialise. It is
# not an import-time payload and does not use the Everyone/GA SDDL.
SCAN_ALLOWLIST = {
    (ROOT / "src" / "security" / "sandbox" / "windows.py").resolve(),
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
            if path.resolve() in SCAN_ALLOWLIST:
                continue
            yield path


def test_static_guard_rejects_removed_payloads() -> None:
    findings: list[str] = []
    for path in _iter_runtime_python():
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, rx in FORBIDDEN.items():
            for line_no, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    findings.append(f"{path.relative_to(ROOT).as_posix()}:{line_no}: {name}")
    assert not findings, "forbidden security payload returned:\n" + "\n".join(findings)


def test_repair_scripts_are_gone() -> None:
    assert not (ROOT / "scripts" / "repair_winsta.py").exists()
    assert not (ROOT / "scripts" / "repair_winsta.ps1").exists()


def _load_checkup():
    path = ROOT / "scripts" / "agent_core_checkup.py"
    spec = importlib.util.spec_from_file_location("phase1_agent_core_checkup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_import_purity_of_context_modules() -> None:
    mod = _load_checkup()
    result = mod.run_guarded_import_probe(
        ("src.context.vector_memory", "src.context.context_engine"),
    )
    assert result["violations"] == [], result["violations"]
    for name in ("src.context.vector_memory", "src.context.context_engine"):
        assert not any(err.startswith(name + ":") for err in result["errors"]), result["errors"]


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


def test_checkup_guard_catches_subprocess(tmp_path: Path) -> None:
    pkg = tmp_path / "bad_subprocess"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "import subprocess\nsubprocess.run(['echo', 'x'])\n", encoding="utf-8",
    )
    result = _load_checkup().run_guarded_import_probe(
        ("bad_subprocess",), extra_path=str(tmp_path),
    )
    assert "subprocess.run" in result["violations"]


def test_checkup_guard_catches_win32_security_import(tmp_path: Path) -> None:
    pkg = tmp_path / "bad_win32"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("import win32security\n", encoding="utf-8")
    result = _load_checkup().run_guarded_import_probe(
        ("bad_win32",), extra_path=str(tmp_path),
    )
    assert "import:win32security" in result["violations"]


def test_checkup_guard_catches_external_write(tmp_path: Path) -> None:
    pkg = tmp_path / "bad_write"
    pkg.mkdir()
    target = tmp_path / "outside" / "evil.log"
    target.parent.mkdir()
    (pkg / "__init__.py").write_text(
        f"open({str(target)!r}, 'w').write('x')\n", encoding="utf-8",
    )
    result = _load_checkup().run_guarded_import_probe(
        ("bad_write",), extra_path=str(tmp_path),
    )
    assert any(item.startswith("write:") for item in result["violations"]), result["violations"]
