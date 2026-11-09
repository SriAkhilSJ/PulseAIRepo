"""Phase 1/1.1 security containment and guard-hardening tests.

Provider-free. No Electron, no external process execution, no real Windows
security API call, no write outside the repository.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
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


def _assignments_to(function: ast.AST, name: str) -> list[ast.Assign]:
    found: list[ast.Assign] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    found.append(node)
    return found


def _single_name(function: ast.AST, attr_name: str, expected: str) -> bool:
    values = _assignment_values(function, attr_name)
    return (
        len(values) == 1
        and isinstance(values[0], ast.Name)
        and values[0].id == expected
    )


def _single_constant(function: ast.AST, attr_name: str, expected: str) -> bool:
    values = _assignment_values(function, attr_name)
    return (
        len(values) == 1
        and isinstance(values[0], ast.Constant)
        and values[0].value == expected
    )


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _arg_name(call: ast.Call, index: int) -> str | None:
    if index >= len(call.args):
        return None
    arg = call.args[index]
    return arg.id if isinstance(arg, ast.Name) else None


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _byref_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "byref":
        return None
    if len(node.args) != 1 or not isinstance(node.args[0], ast.Name):
        return None
    return node.args[0].id


def _inside_ret2_zero_if(function: ast.AST, call: ast.Call) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "ret2"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == 0
        ):
            continue
        if any(candidate is call for candidate in ast.walk(node)):
            return True
    return False


def _security_call_lines(path: Path) -> set[int]:
    """Allow only the exact documented AppContainer operation.

    Every security-relevant property must have exactly one assignment with the
    documented value. The SetEntriesInAclW and SetSecurityInfo calls, the
    p_new_dacl allocation/free flow, and the ret2 guard are all validated.
    Any second assignment, extra mutation, or changed argument fails closed.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_grant_to_object":
            continue

        required = {
            "grfAccessPermissions": "GENERIC_ALL",
            "grfAccessMode": "GRANT_ACCESS",
            "grfInheritance": "NO_INHERITANCE",
            "TrusteeForm": "TRUSTEE_IS_NAME",
            "TrusteeType": "TRUSTEE_IS_WELL_KNOWN_GROUP",
        }
        for attr, expected in required.items():
            if not _single_name(node, attr, expected):
                return set()
        if not _single_constant(node, "ptstrName", "ALL APPLICATION PACKAGES"):
            return set()

        calls = [sub for sub in ast.walk(node) if isinstance(sub, ast.Call)]
        entries = [call for call in calls if _call_name(call) == "SetEntriesInAclW"]
        if len(entries) != 1:
            return set()
        entries_call = entries[0]
        if len(entries_call.args) != 4:
            return set()
        if not (
            isinstance(entries_call.args[0], ast.Constant)
            and entries_call.args[0].value == 1
        ):
            return set()
        if _byref_name(entries_call.args[1]) != "ea":
            return set()
        if _arg_name(entries_call, 2) != "p_dacl":
            return set()
        if _byref_name(entries_call.args[3]) != "p_new_dacl":
            return set()

        ret2_assigns = _assignments_to(node, "ret2")
        if len(ret2_assigns) != 1:
            return set()
        if not (
            isinstance(ret2_assigns[0].value, ast.Call)
            and _call_name(ret2_assigns[0].value) == "SetEntriesInAclW"
        ):
            return set()

        pnew_assigns = _assignments_to(node, "p_new_dacl")
        if len(pnew_assigns) != 1:
            return set()
        pnew_value = pnew_assigns[0].value
        if not (
            isinstance(pnew_value, ast.Call)
            and isinstance(pnew_value.func, ast.Attribute)
            and pnew_value.func.attr == "c_void_p"
        ):
            return set()

        mutation_names = {
            "SetSecurityInfo",
            "SetNamedSecurityInfoW",
            "SetNamedSecurityInfoA",
            "SetKernelObjectSecurity",
            "SetUserObjectSecurity",
            "NtSetSecurityObject",
        }
        mutations = [call for call in calls if _call_name(call) in mutation_names]
        if len(mutations) != 1 or _call_name(mutations[0]) != "SetSecurityInfo":
            return set()
        security_call = mutations[0]

        if len(security_call.args) != 7:
            return set()
        expected_args: list[str | None] = [
            "handle",
            "SE_WINDOW_OBJECT",
            "DACL_SECURITY_INFORMATION",
            None,
            None,
            "p_new_dacl",
            None,
        ]
        for index, expected in enumerate(expected_args):
            arg = security_call.args[index]
            if expected is None:
                if not _is_none(arg):
                    return set()
            elif not (isinstance(arg, ast.Name) and arg.id == expected):
                return set()

        if not _inside_ret2_zero_if(node, security_call):
            return set()

        frees = [
            call for call in calls
            if _call_name(call) == "LocalFree"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "p_new_dacl"
        ]
        if len(frees) != 1:
            return set()

        return {security_call.lineno}
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
        "        ea.grfAccessMode = GRANT_ACCESS\n"
        "        ea.grfInheritance = NO_INHERITANCE\n"
        "        ea.Trustee.TrusteeForm = TRUSTEE_IS_NAME\n"
        "        ea.Trustee.TrusteeType = TRUSTEE_IS_WELL_KNOWN_GROUP\n"
        "        ea.Trustee.ptstrName = 'ALL APPLICATION PACKAGES'\n"
        "        p_new_dacl = ctypes.c_void_p()\n"
        "        ret2 = _advapi32.SetEntriesInAclW(1, ctypes.byref(ea), p_dacl, ctypes.byref(p_new_dacl))\n"
        "        if ret2 == 0:\n"
        "            _advapi32.SetSecurityInfo(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_new_dacl, None)\n"
        "            _kernel32.LocalFree(p_new_dacl)\n"
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


# ---------------------------------------------------------------------------
# Phase 1.3: CWD, filesystem mutation, strict AppContainer allowlist
# ---------------------------------------------------------------------------

def test_chdir_escape_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "cwd_outside"
    outside.mkdir()
    code = (
        "import os\n"
        f"os.chdir({str(outside)!r})\n"
        "open('escape.txt', 'w').write('x')\n"
    )
    try:
        result = _probe(tmp_path, "cwd_chdir", code)
        assert any(item.startswith("chdir:") for item in result["violations"]), result
        assert not (outside / "escape.txt").exists()
        assert not (ROOT / "escape.txt").exists()
    finally:
        (ROOT / "escape.txt").unlink(missing_ok=True)


@pytest.mark.skipif(not hasattr(os, "fchdir"), reason="os.fchdir unavailable")
def test_fchdir_escape_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "fchdir_outside"
    outside.mkdir()
    code = (
        "import os\n"
        f"fd = os.open({str(outside)!r}, os.O_RDONLY)\n"
        "try:\n"
        "    os.fchdir(fd)\n"
        "finally:\n"
        "    os.close(fd)\n"
    )
    result = _probe(tmp_path, "cwd_fchdir", code)
    assert any(item.startswith("chdir:") for item in result["violations"]), result


def _relative_outside(tmp_path: Path, name: str) -> tuple[str, Path] | None:
    target = tmp_path / name
    try:
        return os.path.relpath(target, ROOT), target
    except ValueError:
        return None


def test_relative_replace_escape_blocked(tmp_path: Path) -> None:
    pair = _relative_outside(tmp_path, "relative_replace.txt")
    if pair is None:
        pytest.skip("target is on a different drive")
    rel, target = pair
    result = _probe(
        tmp_path, "rel_replace",
        f"import os\nos.replace('local_src', {rel!r})\n",
    )
    assert any(str(target) in item or rel in item for item in result["violations"]), result
    assert not target.exists()


def test_relative_rename_escape_blocked(tmp_path: Path) -> None:
    pair = _relative_outside(tmp_path, "relative_rename.txt")
    if pair is None:
        pytest.skip("target is on a different drive")
    rel, target = pair
    result = _probe(
        tmp_path, "rel_rename",
        f"import os\nos.rename('local_src', {rel!r})\n",
    )
    assert any(str(target) in item or rel in item for item in result["violations"]), result
    assert not target.exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable")
def test_relative_symlink_escape_blocked(tmp_path: Path) -> None:
    pair = _relative_outside(tmp_path, "relative_symlink.txt")
    if pair is None:
        pytest.skip("target is on a different drive")
    rel, target = pair
    result = _probe(
        tmp_path, "rel_symlink",
        f"import os\nos.symlink('target', {rel!r})\n",
    )
    assert any(str(target) in item or rel in item for item in result["violations"]), result
    assert not target.exists()


def test_external_mkdir_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "new_dir"
    result = _probe(tmp_path, "mkdir_ext", f"import os\nos.mkdir({str(outside)!r})\n")
    assert any(str(outside) in item for item in result["violations"]), result
    assert not outside.exists()


def test_external_makedirs_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "new_tree" / "nested"
    result = _probe(tmp_path, "makedirs_ext", f"import os\nos.makedirs({str(outside)!r})\n")
    assert any(str(outside) in item for item in result["violations"]), result
    assert not outside.exists()


def test_external_path_mkdir_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "path_new_dir"
    result = _probe(
        tmp_path, "path_mkdir_ext",
        f"from pathlib import Path\nPath({str(outside)!r}).mkdir()\n",
    )
    assert any(str(outside) in item for item in result["violations"]), result
    assert not outside.exists()


def test_external_unlink_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "delete_me.txt"
    outside.write_text("keep", encoding="utf-8")
    result = _probe(tmp_path, "unlink_ext", f"import os\nos.unlink({str(outside)!r})\n")
    assert any(str(outside) in item for item in result["violations"]), result
    assert outside.exists()
    assert outside.read_text(encoding="utf-8") == "keep"


def test_external_remove_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "remove_me.txt"
    outside.write_text("keep", encoding="utf-8")
    result = _probe(tmp_path, "remove_ext", f"import os\nos.remove({str(outside)!r})\n")
    assert any(str(outside) in item for item in result["violations"]), result
    assert outside.exists()


def test_external_path_unlink_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "path_delete.txt"
    outside.write_text("keep", encoding="utf-8")
    result = _probe(
        tmp_path, "path_unlink_ext",
        f"from pathlib import Path\nPath({str(outside)!r}).unlink()\n",
    )
    assert any(str(outside) in item for item in result["violations"]), result
    assert outside.exists()


def test_external_rmdir_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "delete_dir"
    outside.mkdir()
    result = _probe(tmp_path, "rmdir_ext", f"import os\nos.rmdir({str(outside)!r})\n")
    assert any(str(outside) in item for item in result["violations"]), result
    assert outside.exists()


def test_external_removedirs_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "removedirs_tree"
    outside.mkdir()
    result = _probe(tmp_path, "removedirs_ext", f"import os\nos.removedirs({str(outside)!r})\n")
    assert any(str(outside) in item for item in result["violations"]), result
    assert outside.exists()


def test_external_path_rmdir_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "path_delete_dir"
    outside.mkdir()
    result = _probe(
        tmp_path, "path_rmdir_ext",
        f"from pathlib import Path\nPath({str(outside)!r}).rmdir()\n",
    )
    assert any(str(outside) in item for item in result["violations"]), result
    assert outside.exists()


def test_external_truncate_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "truncate.txt"
    outside.write_text("keep", encoding="utf-8")
    result = _probe(
        tmp_path, "truncate_ext",
        f"import os\nos.truncate({str(outside)!r}, 0)\n",
    )
    assert any(str(outside) in item for item in result["violations"]), result
    assert outside.read_text(encoding="utf-8") == "keep"


@pytest.mark.skipif(not hasattr(os, "ftruncate"), reason="os.ftruncate unavailable")
def test_descriptor_truncate_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "fd_truncate.txt"
    outside.write_text("keep", encoding="utf-8")
    code = (
        "import os\n"
        f"fd = os.open({str(outside)!r}, os.O_RDONLY)\n"
        "try:\n"
        "    os.ftruncate(fd, 0)\n"
        "finally:\n"
        "    os.close(fd)\n"
    )
    result = _probe(tmp_path, "fd_truncate", code)
    assert any(item.startswith("write:fd:") for item in result["violations"]), result
    assert outside.read_text(encoding="utf-8") == "keep"


def test_writable_fdopen_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "fdopen.txt"
    outside.write_text("keep", encoding="utf-8")
    code = (
        "import os\n"
        f"fd = os.open({str(outside)!r}, os.O_RDONLY)\n"
        "try:\n"
        "    os.fdopen(fd, 'w')\n"
        "finally:\n"
        "    os.close(fd)\n"
    )
    result = _probe(tmp_path, "fdopen_write", code)
    assert any(item.startswith("write:fd:") for item in result["violations"]), result
    assert outside.read_text(encoding="utf-8") == "keep"


def test_local_filesystem_mutations_allowed(tmp_path: Path) -> None:
    base = ROOT / f".guard_fs_{tmp_path.name}"
    code = (
        "import os\n"
        f"base = {str(base)!r}\n"
        "os.mkdir(base)\n"
        "p = os.path.join(base, 'x.txt')\n"
        "with open(p, 'w') as f:\n"
        "    f.write('ok')\n"
        "os.unlink(p)\n"
        "os.rmdir(base)\n"
    )
    try:
        result = _probe(tmp_path, "local_fs", code)
        assert result["violations"] == [], result
        assert not base.exists()
    finally:
        if base.exists():
            shutil.rmtree(base, ignore_errors=True)


def _assert_grant_rejected(tmp_path: Path, source: str, name: str) -> None:
    sample = tmp_path / f"{name}.py"
    sample.write_text(source, encoding="utf-8")
    assert _security_call_lines(sample) == set()


def test_sandbox_rejects_trustee_reassignment(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        ea.Trustee.ptstrName = 'Everyone'\n"),
        "trustee_reassign",
    )


def test_sandbox_rejects_permission_reassignment(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        ea.grfAccessPermissions = GENERIC_READ\n"),
        "permission_reassign",
    )


def test_sandbox_rejects_trustee_type_reassignment(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        ea.Trustee.TrusteeType = TRUSTEE_IS_USER\n"),
        "trustee_type_reassign",
    )


def test_sandbox_rejects_changed_information_flags(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "DACL_SECURITY_INFORMATION", "OWNER_SECURITY_INFORMATION",
    )
    _assert_grant_rejected(tmp_path, source, "changed_flags")


def test_sandbox_rejects_changed_owner_group_dacl_sacl(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "None, None, p_new_dacl, None",
        "p_owner, p_group, p_other, p_sacl",
    )
    _assert_grant_rejected(tmp_path, source, "changed_args")


def test_sandbox_rejects_extra_security_mutation(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            "        _advapi32.SetNamedSecurityInfoW(handle, SE_WINDOW_OBJECT, 0, None, None, None, None)\n"
        ),
        "extra_mutation",
    )


def test_sandbox_rejects_changed_entries_flow(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "ctypes.byref(p_new_dacl)", "p_other",
    )
    _assert_grant_rejected(tmp_path, source, "entries_flow")


def test_sandbox_rejects_missing_local_free(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "            _kernel32.LocalFree(p_new_dacl)\n", "",
    )
    _assert_grant_rejected(tmp_path, source, "missing_free")


def test_sandbox_rejects_missing_ret2_guard(tmp_path: Path) -> None:
    source = _documented_grant_source().replace("if ret2 == 0:", "if True:")
    _assert_grant_rejected(tmp_path, source, "missing_ret2")
