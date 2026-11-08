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
    "SetNamedSecurityInfoW": re.compile(r"SetNamedSecurityInfoW"),
    "SetNamedSecurityInfoA": re.compile(r"SetNamedSecurityInfoA"),
    "SetKernelObjectSecurity": re.compile(r"SetKernelObjectSecurity"),
    "SetUserObjectSecurity": re.compile(r"SetUserObjectSecurity"),
    "NtSetSecurityObject": re.compile(r"NtSetSecurityObject"),
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


def _assignment_values(function: ast.AST, attr_name: str) -> list[ast.AST]:
    values: list[ast.AST] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == attr_name:
                    values.append(node.value)
    return values


def _security_call_lines(path: Path) -> set[int]:
    """Allow only the documented AppContainer SetSecurityInfo call.

    The enclosing ``_grant_to_object`` must build an EXPLICIT_ACCESS_W with
    GENERIC_ALL for ALL APPLICATION PACKAGES, call SetEntriesInAclW, contain
    exactly one SetSecurityInfo call, and pass the documented handle/object
    arguments. Anything else - including a second mutation inside the same
    function - returns an empty allowlist so the scanner rejects it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_grant_to_object":
            continue
        perms = _assignment_values(node, "grfAccessPermissions")
        trustees = _assignment_values(node, "ptstrName")
        has_entries = any(
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "SetEntriesInAclW"
            for sub in ast.walk(node)
        )
        calls = [
            sub for sub in ast.walk(node)
            if isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "SetSecurityInfo"
        ]
        documented = (
            any(isinstance(v, ast.Name) and v.id == "GENERIC_ALL" for v in perms)
            and any(
                isinstance(v, ast.Constant) and v.value == "ALL APPLICATION PACKAGES"
                for v in trustees
            )
            and has_entries
            and len(calls) == 1
            and len(calls[0].args) == 7
            and isinstance(calls[0].args[0], ast.Name)
            and calls[0].args[0].id == "handle"
            and isinstance(calls[0].args[1], ast.Name)
            and calls[0].args[1].id == "SE_WINDOW_OBJECT"
            and isinstance(calls[0].args[5], ast.Name)
            and calls[0].args[5].id == "p_new_dacl"
        )
        return {calls[0].lineno} if documented else set()
    return set()


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


def _documented_grant_source(extra: str = "") -> str:
    return (
        "def _ensure():\n"
        "    def _grant_to_object(handle):\n"
        "        ea = EXPLICIT_ACCESS_W()\n"
        "        ea.grfAccessPermissions = GENERIC_ALL\n"
        "        ea.Trustee.ptstrName = 'ALL APPLICATION PACKAGES'\n"
        "        ret2 = _advapi32.SetEntriesInAclW(1, byref(ea), p_dacl, byref(p_new_dacl))\n"
        "        if ret2 == 0:\n"
        "            _advapi32.SetSecurityInfo(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_new_dacl, None)\n"
        + extra
    )


def test_sandbox_allowlist_is_narrow() -> None:
    allowed = _sandbox_allowed_lines()
    assert allowed, "the documented AppContainer call was not found"
    text = SANDBOX.read_text(encoding="utf-8")
    assert "ALL APPLICATION PACKAGES" in text
    assert "WD)(A;OICI;GA" not in text


def test_sandbox_allowlist_does_not_hide_calls_elsewhere(tmp_path: Path) -> None:
    source = _documented_grant_source(
        "\n"
        "def other():\n"
        "    _advapi32.SetSecurityInfo(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_other, None)\n"
    )
    sample = tmp_path / "sample.py"
    sample.write_text(source, encoding="utf-8")
    expected = next(
        i for i, line in enumerate(source.splitlines(), 1)
        if "_advapi32.SetSecurityInfo" in line
    )
    assert _security_call_lines(sample) == {expected}


def test_sandbox_allowlist_rejects_second_mutation_inside_grant(tmp_path: Path) -> None:
    source = _documented_grant_source(
        "            _advapi32.SetSecurityInfo(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_other, None)\n"
    )
    sample = tmp_path / "sample.py"
    sample.write_text(source, encoding="utf-8")
    assert _security_call_lines(sample) == set()


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


# ---------------------------------------------------------------------------
# Phase 1.2 filesystem bypass regressions
# ---------------------------------------------------------------------------

def test_invalid_path_fails_closed(tmp_path: Path) -> None:
    result = _probe(tmp_path, "bad_path", "open(object(), 'w')\n")
    assert any(item.startswith("write:") for item in result["violations"]), result


@pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows-specific")
def test_different_drive_fails_closed(tmp_path: Path) -> None:
    target = Path("D:/guard_phase12_escape.txt")
    result = _probe(tmp_path, "bad_drive", f"open({str(target)!r}, 'w')\n")
    assert any(item.startswith("write:") for item in result["violations"]), result
    assert not target.exists()


def test_allowed_repository_local_write(tmp_path: Path) -> None:
    target = ROOT / f".guard_allowed_{tmp_path.name}.txt"
    try:
        result = _probe(
            tmp_path, "allowed_local",
            f"open({str(target)!r}, 'w').write('ok')\n",
        )
        assert result["violations"] == [], result
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "ok"
    finally:
        target.unlink(missing_ok=True)


def test_relative_path_resolves_against_root(tmp_path: Path) -> None:
    name = f".guard_relative_{tmp_path.name}.txt"
    target = ROOT / name
    try:
        result = _probe(tmp_path, "relative_local", f"open({name!r}, 'w').write('ok')\n")
        assert result["violations"] == [], result
        assert target.exists()
    finally:
        target.unlink(missing_ok=True)


def test_custom_opener_nested_external_write_blocked(tmp_path: Path) -> None:
    inside = ROOT / f".guard_opener_{tmp_path.name}.txt"
    outside = tmp_path / "nested_escape.txt"
    code = (
        "import builtins, os\n"
        f"inside = {str(inside)!r}\n"
        f"outside = {str(outside)!r}\n"
        "def opener(path, flags):\n"
        "    os.open(outside, os.O_CREAT | os.O_WRONLY)\n"
        "    return os.open(path, flags)\n"
        "builtins.open(inside, 'w', opener=opener)\n"
    )
    try:
        result = _probe(tmp_path, "nested_opener", code)
        assert any(str(outside) in item for item in result["violations"]), result
        assert not outside.exists()
        assert not inside.exists()
    finally:
        inside.unlink(missing_ok=True)


def test_dir_fd_write_rejected(tmp_path: Path) -> None:
    result = _probe(
        tmp_path, "dir_fd",
        "import os\nos.open('escaped.txt', os.O_CREAT | os.O_WRONLY, dir_fd=0)\n",
    )
    assert "write:dir_fd" in result["violations"], result
    assert not (ROOT / "escaped.txt").exists()


@pytest.mark.skipif(
    os.name == "nt" or not hasattr(os, "supports_dir_fd") or os.open not in os.supports_dir_fd,
    reason="os.open(dir_fd=...) is not supported on this platform",
)
def test_dir_fd_external_directory_rejected(tmp_path: Path) -> None:
    external = tmp_path / "external_dir"
    external.mkdir()
    code = (
        "import os\n"
        f"d = os.open({str(external)!r}, os.O_RDONLY)\n"
        "try:\n"
        "    os.open('escaped.txt', os.O_CREAT | os.O_WRONLY, dir_fd=d)\n"
        "finally:\n"
        "    os.close(d)\n"
    )
    result = _probe(tmp_path, "dir_fd_external", code)
    assert "write:dir_fd" in result["violations"], result
    assert not (external / "escaped.txt").exists()


def test_external_replace_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "replace_escape.txt"
    result = _probe(tmp_path, "replace_ext", f"import os\nos.replace('local_src', {str(outside)!r})\n")
    assert any(str(outside) in item for item in result["violations"]), result
    assert not outside.exists()


def test_external_rename_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "rename_escape.txt"
    result = _probe(tmp_path, "rename_ext", f"import os\nos.rename('local_src', {str(outside)!r})\n")
    assert any(str(outside) in item for item in result["violations"]), result
    assert not outside.exists()


@pytest.mark.skipif(not hasattr(os, "link"), reason="os.link unavailable")
def test_external_link_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "link_escape.txt"
    result = _probe(tmp_path, "link_ext", f"import os\nos.link('local_src', {str(outside)!r})\n")
    assert any(str(outside) in item for item in result["violations"]), result
    assert not outside.exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable")
def test_external_symlink_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "symlink_escape.txt"
    result = _probe(tmp_path, "symlink_ext", f"import os\nos.symlink('target', {str(outside)!r})\n")
    assert any(str(outside) in item for item in result["violations"]), result
    assert not outside.exists()


def test_external_source_move_into_repo_blocked(tmp_path: Path) -> None:
    outside_src = tmp_path / "outside_src.txt"
    local_dst = ROOT / f".guard_move_{tmp_path.name}.txt"
    result = _probe(
        tmp_path, "move_in",
        f"import os\nos.replace({str(outside_src)!r}, {str(local_dst)!r})\n",
    )
    assert any(str(outside_src) in item for item in result["violations"]), result
    assert not local_dst.exists()
