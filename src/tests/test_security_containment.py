"""Phase 1/1.1 security containment and guard-hardening tests.

Provider-free. No Electron, no external process execution, no real Windows
security API call, no write outside the repository.
"""
from __future__ import annotations

import ast
import copy
import ctypes
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


def _target_path(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _target_path(node.value)
        if base:
            return f"{base}.{node.attr}"
    return None


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value)
        if base:
            return f"{base}.{node.attr}"
    return None


def _call_qualified_name(call: ast.Call) -> str | None:
    return _qualified_name(call.func)


# Names whose binding changes what an approved security call means. The
# documented module already binds them; any *additional* binding, or any local
# binding in an enclosing scope, fails closed.
_PROTECTED_NAMES = frozenset({
    "_advapi32",
    "_kernel32",
    "ctypes",
    "EXPLICIT_ACCESS_W",
    "GENERIC_ALL",
    "GRANT_ACCESS",
    "NO_INHERITANCE",
    "TRUSTEE_IS_NAME",
    "TRUSTEE_IS_WELL_KNOWN_GROUP",
    "SE_WINDOW_OBJECT",
    "DACL_SECURITY_INFORMATION",
})

_EXPECTED_CONSTANTS = {
    "GENERIC_ALL": 0x10000000,
    "GRANT_ACCESS": 1,
    "NO_INHERITANCE": 0,
    "TRUSTEE_IS_NAME": 1,
    "TRUSTEE_IS_WELL_KNOWN_GROUP": 5,
    "SE_WINDOW_OBJECT": 7,
    "DACL_SECURITY_INFORMATION": 4,
}

_GET_SECURITY_INFO_ARGS: tuple[tuple[str, object], ...] = (
    ("name", "handle"),
    ("name", "SE_WINDOW_OBJECT"),
    ("name", "DACL_SECURITY_INFORMATION"),
    ("none", None),
    ("none", None),
    ("byref", "p_dacl"),
    ("none", None),
    ("byref", "p_sec_desc"),
)

_SET_ENTRIES_ARGS: tuple[tuple[str, object], ...] = (
    ("const", 1),
    ("byref", "ea"),
    ("name", "p_dacl"),
    ("byref", "p_new_dacl"),
)

_SET_SECURITY_ARGS: tuple[tuple[str, object], ...] = (
    ("name", "handle"),
    ("name", "SE_WINDOW_OBJECT"),
    ("name", "DACL_SECURITY_INFORMATION"),
    ("none", None),
    ("none", None),
    ("name", "p_new_dacl"),
    ("none", None),
)

_GRANT_ASSIGNMENTS: tuple[tuple[str, tuple], ...] = (
    ("ea", ("call", "EXPLICIT_ACCESS_W")),
    ("ea.grfAccessPermissions", ("name", "GENERIC_ALL")),
    ("ea.grfAccessMode", ("name", "GRANT_ACCESS")),
    ("ea.grfInheritance", ("name", "NO_INHERITANCE")),
    ("ea.Trustee.pMultipleTrustee", ("none", None)),
    ("ea.Trustee.MultipleTrusteeOperation", ("const", 0)),
    ("ea.Trustee.TrusteeForm", ("name", "TRUSTEE_IS_NAME")),
    ("ea.Trustee.TrusteeType", ("name", "TRUSTEE_IS_WELL_KNOWN_GROUP")),
    ("ea.Trustee.ptstrName", ("const", "ALL APPLICATION PACKAGES")),
    ("p_dacl", ("call", "ctypes.c_void_p")),
    ("p_sec_desc", ("call", "ctypes.c_void_p")),
)


def _arg_matches(node: ast.AST, spec: tuple[str, object]) -> bool:
    kind, value = spec
    if kind == "name":
        return isinstance(node, ast.Name) and node.id == value
    if kind == "none":
        return isinstance(node, ast.Constant) and node.value is None
    if kind == "const":
        return (
            isinstance(node, ast.Constant)
            and type(node.value) is int
            and node.value == value
        )
    if kind == "byref":
        if not isinstance(node, ast.Call):
            return False
        if _call_qualified_name(node) != "ctypes.byref":
            return False
        if node.keywords or len(node.args) != 1:
            return False
        inner = node.args[0]
        return isinstance(inner, ast.Name) and inner.id == value
    return False


def _call_with_args(
    node: ast.AST,
    qualified: str,
    args: tuple[tuple[str, object], ...],
) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if _call_qualified_name(node) != qualified:
        return False
    if node.keywords or len(node.args) != len(args):
        return False
    return all(_arg_matches(arg, spec) for arg, spec in zip(node.args, args))


def _matches_value(node: ast.AST, spec: tuple) -> bool:
    kind = spec[0]
    if kind == "name":
        return isinstance(node, ast.Name) and node.id == spec[1]
    if kind == "const":
        expected = spec[1]
        if isinstance(expected, int):
            return (
                isinstance(node, ast.Constant)
                and type(node.value) is int
                and node.value == expected
            )
        return isinstance(node, ast.Constant) and node.value == expected
    if kind == "none":
        return isinstance(node, ast.Constant) and node.value is None
    if kind == "call":
        args = spec[2] if len(spec) > 2 else ()
        return _call_with_args(node, str(spec[1]), args)
    return False


def _simple_assignment(
    stmt: ast.stmt,
    path: str,
    spec: tuple,
) -> bool:
    return (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and _target_path(stmt.targets[0]) == path
        and _matches_value(stmt.value, spec)
    )


def _is_int_compare(
    node: ast.AST,
    name: str,
    op: type[ast.cmpop],
    value: int,
) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == name
        and len(node.ops) == 1
        and isinstance(node.ops[0], op)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and type(node.comparators[0].value) is int
        and node.comparators[0].value == value
    )


def _expr_call(
    stmt: ast.stmt,
    qualified: str,
    args: tuple[tuple[str, object], ...],
) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and _call_with_args(stmt.value, qualified, args)
    )


def _grant_body_ok(body: list[ast.stmt]) -> bool:
    """Require the exact eighteen-statement documented function body.

    Anything extra - an alias, a rebinding, a loop, a with-as, a walrus, a
    nested def/class, a second call, a changed argument, a changed branch or a
    changed return - makes the body stop matching and fails closed.
    """
    if len(body) != 18:
        return False

    for index, (path, spec) in enumerate(_GRANT_ASSIGNMENTS):
        if not _simple_assignment(body[index], path, spec):
            return False

    if not _simple_assignment(
        body[11],
        "ret",
        ("call", "_advapi32.GetSecurityInfo", _GET_SECURITY_INFO_ARGS),
    ):
        return False

    failure_branch = body[12]
    if not (
        isinstance(failure_branch, ast.If)
        and _is_int_compare(failure_branch.test, "ret", ast.NotEq, 0)
        and not failure_branch.orelse
        and len(failure_branch.body) == 1
        and isinstance(failure_branch.body[0], ast.Return)
        and isinstance(failure_branch.body[0].value, ast.Constant)
        and failure_branch.body[0].value.value is False
    ):
        return False

    if not _simple_assignment(
        body[13],
        "p_new_dacl",
        ("call", "ctypes.c_void_p"),
    ):
        return False

    if not _simple_assignment(
        body[14],
        "ret2",
        ("call", "_advapi32.SetEntriesInAclW", _SET_ENTRIES_ARGS),
    ):
        return False

    success_branch = body[15]
    if not (
        isinstance(success_branch, ast.If)
        and _is_int_compare(success_branch.test, "ret2", ast.Eq, 0)
        and not success_branch.orelse
        and len(success_branch.body) == 2
        and _expr_call(
            success_branch.body[0],
            "_advapi32.SetSecurityInfo",
            _SET_SECURITY_ARGS,
        )
        and _expr_call(
            success_branch.body[1],
            "_kernel32.LocalFree",
            (("name", "p_new_dacl"),),
        )
    ):
        return False

    if not _expr_call(
        body[16],
        "_kernel32.LocalFree",
        (("name", "p_sec_desc"),),
    ):
        return False

    final_return = body[17]
    return (
        isinstance(final_return, ast.Return)
        and _is_int_compare(final_return.value, "ret2", ast.Eq, 0)
    )


def _grant_signature_ok(function: ast.FunctionDef) -> bool:
    args = function.args
    if function.decorator_list:
        return False
    if function.type_comment:
        return False
    if args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg:
        return False
    if len(args.args) != 1 or args.args[0].arg != "handle":
        return False
    if args.args[0].annotation is not None:
        return False
    if args.defaults or args.kw_defaults:
        return False
    returns = function.returns
    return returns is None or (
        isinstance(returns, ast.Name) and returns.id == "bool"
    )


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_target_names(element))
        return names
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []


def _scope_walk(scope: ast.AST):
    """Yield nodes in one scope, never descending into a nested scope."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _binding_entries(scope: ast.AST):
    for node in _scope_walk(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _target_names(target):
                    yield name, node, "assign"
        elif isinstance(node, ast.AnnAssign):
            for name in _target_names(node.target):
                yield name, node, "annassign"
        elif isinstance(node, ast.AugAssign):
            for name in _target_names(node.target):
                yield name, node, "augassign"
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                for name in _target_names(target):
                    yield name, node, "delete"
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            for name in _target_names(node.target):
                yield name, node, "for"
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is None:
                    continue
                for name in _target_names(item.optional_vars):
                    yield name, node, "with"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                yield (alias.asname or alias.name.split(".")[0]), node, "import"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node, "def"
        elif isinstance(node, ast.ClassDef):
            yield node.name, node, "class"
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                yield name, node, "global"
        elif isinstance(node, ast.ExceptHandler) and node.name:
            yield node.name, node, "except"
        elif isinstance(node, ast.NamedExpr):
            for name in _target_names(node.target):
                yield name, node, "walrus"
        elif isinstance(node, ast.comprehension):
            for name in _target_names(node.target):
                yield name, node, "comprehension"
        elif isinstance(node, ast.arg):
            yield node.arg, node, "param"
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            yield node.name, node, "match"
        elif isinstance(node, ast.MatchMapping) and node.rest:
            yield node.rest, node, "match"


def _canonical_constant(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and _target_path(node.targets[0]) == name
        and isinstance(node.value, ast.Constant)
        and type(node.value.value) is int
        and node.value.value == _EXPECTED_CONSTANTS[name]
    )


def _is_win32_platform_test(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Compare)
        and _target_path(node.left) == "sys.platform"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Eq)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and type(node.comparators[0].value) is str
        and node.comparators[0].value == "win32"
    )


def _canonical_windll_value(name: str, value: ast.AST) -> bool:
    """Require the exact documented platform-conditional DLL load."""
    if not isinstance(value, ast.IfExp):
        return False
    if not _is_win32_platform_test(value.test):
        return False
    call = value.body
    if not isinstance(call, ast.Call):
        return False
    if _call_qualified_name(call) != "ctypes.WinDLL":
        return False
    if len(call.args) != 1 or len(call.keywords) != 1:
        return False
    keyword = call.keywords[0]
    if keyword.arg != "use_last_error":
        return False
    if not (
        isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
    ):
        return False
    if not (
        isinstance(value.orelse, ast.Constant)
        and value.orelse.value is None
    ):
        return False
    expected = name.removeprefix("_")
    first = call.args[0]
    return (
        isinstance(first, ast.Constant)
        and type(first.value) is str
        and first.value == expected
    )


def _canonical_windll(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and _target_path(node.targets[0]) == name
        and _canonical_windll_value(name, node.value)
    )


# Exact ctypes.Structure layouts used by the Windows sandbox. The string on the
# right is the normalized type expression, e.g. "ctypes.POINTER(wintypes.BYTE)".
_EXPECTED_STRUCTURES: dict[str, tuple[tuple[str, str], ...]] = {
    "IO_COUNTERS": (
        ("ReadOperationCount", "ctypes.c_uint64"),
        ("WriteOperationCount", "ctypes.c_uint64"),
        ("OtherOperationCount", "ctypes.c_uint64"),
        ("ReadTransferCount", "ctypes.c_uint64"),
        ("WriteTransferCount", "ctypes.c_uint64"),
        ("OtherTransferCount", "ctypes.c_uint64"),
    ),
    "JOBOBJECT_BASIC_LIMIT_INFORMATION": (
        ("PerProcessUserTimeLimit", "ctypes.c_int64"),
        ("PerJobUserTimeLimit", "ctypes.c_int64"),
        ("LimitFlags", "wintypes.DWORD"),
        ("MinimumWorkingSetSize", "ctypes.c_size_t"),
        ("MaximumWorkingSetSize", "ctypes.c_size_t"),
        ("ActiveProcessLimit", "wintypes.DWORD"),
        ("Affinity", "ctypes.c_size_t"),
        ("PriorityClass", "wintypes.DWORD"),
        ("SchedulingClass", "wintypes.DWORD"),
    ),
    "JOBOBJECT_EXTENDED_LIMIT_INFORMATION": (
        ("BasicLimitInformation", "JOBOBJECT_BASIC_LIMIT_INFORMATION"),
        ("IoInfo", "IO_COUNTERS"),
        ("ProcessMemoryLimit", "ctypes.c_size_t"),
        ("JobMemoryLimit", "ctypes.c_size_t"),
        ("PeakProcessMemoryUsed", "ctypes.c_size_t"),
        ("PeakJobMemoryUsed", "ctypes.c_size_t"),
    ),
    "JOBOBJECT_CPU_RATE_CONTROL_INFORMATION": (
        ("ControlFlags", "wintypes.DWORD"),
        ("CpuRate", "wintypes.DWORD"),
    ),
    "SECURITY_ATTRIBUTES": (
        ("nLength", "wintypes.DWORD"),
        ("lpSecurityDescriptor", "ctypes.c_void_p"),
        ("bInheritHandle", "wintypes.BOOL"),
    ),
    "SECURITY_CAPABILITIES": (
        ("AppContainerSid", "ctypes.c_void_p"),
        ("Capabilities", "ctypes.c_void_p"),
        ("CapabilityCount", "wintypes.DWORD"),
        ("Reserved", "wintypes.DWORD"),
    ),
    "STARTUPINFOW": (
        ("cb", "wintypes.DWORD"),
        ("lpReserved", "wintypes.LPWSTR"),
        ("lpDesktop", "wintypes.LPWSTR"),
        ("lpTitle", "wintypes.LPWSTR"),
        ("dwX", "wintypes.DWORD"),
        ("dwY", "wintypes.DWORD"),
        ("dwXSize", "wintypes.DWORD"),
        ("dwYSize", "wintypes.DWORD"),
        ("dwXCountChars", "wintypes.DWORD"),
        ("dwYCountChars", "wintypes.DWORD"),
        ("dwFillAttribute", "wintypes.DWORD"),
        ("dwFlags", "wintypes.DWORD"),
        ("wShowWindow", "wintypes.WORD"),
        ("cbReserved2", "wintypes.WORD"),
        ("lpReserved2", "ctypes.POINTER(wintypes.BYTE)"),
        ("hStdInput", "wintypes.HANDLE"),
        ("hStdOutput", "wintypes.HANDLE"),
        ("hStdError", "wintypes.HANDLE"),
    ),
    "STARTUPINFOEXW": (
        ("StartupInfo", "STARTUPINFOW"),
        ("lpAttributeList", "ctypes.c_void_p"),
    ),
    "PROCESS_INFORMATION": (
        ("hProcess", "wintypes.HANDLE"),
        ("hThread", "wintypes.HANDLE"),
        ("dwProcessId", "wintypes.DWORD"),
        ("dwThreadId", "wintypes.DWORD"),
    ),
    "TRUSTEE_W": (
        ("pMultipleTrustee", "ctypes.c_void_p"),
        ("MultipleTrusteeOperation", "wintypes.DWORD"),
        ("TrusteeForm", "wintypes.DWORD"),
        ("TrusteeType", "wintypes.DWORD"),
        ("ptstrName", "wintypes.LPWSTR"),
    ),
    "EXPLICIT_ACCESS_W": (
        ("grfAccessPermissions", "wintypes.DWORD"),
        ("grfAccessMode", "wintypes.DWORD"),
        ("grfInheritance", "wintypes.DWORD"),
        ("Trustee", "TRUSTEE_W"),
    ),
}


def _type_expression(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _type_expression(node.value)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Call):
        function = _type_expression(node.func)
        if function is None or node.keywords or not node.args:
            return None
        parts: list[str] = []
        for argument in node.args:
            part = _type_expression(argument)
            if part is None:
                return None
            parts.append(part)
        return f"{function}({','.join(parts)})"
    return None


def _structure_body_ok(
    node: ast.ClassDef,
    expected: tuple[tuple[str, str], ...],
) -> bool:
    """Require one exact _fields_ list and nothing else in the class body."""
    if node.decorator_list or node.keywords:
        return False
    if len(node.bases) != 1 or _target_path(node.bases[0]) != "ctypes.Structure":
        return False
    if len(node.body) != 1:
        return False
    statement = node.body[0]
    if not (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "_fields_"
        and isinstance(statement.value, ast.List)
    ):
        return False
    fields = statement.value.elts
    if len(fields) != len(expected):
        return False
    for element, (name, type_name) in zip(fields, expected):
        if not (
            isinstance(element, ast.Tuple)
            and len(element.elts) == 2
            and isinstance(element.elts[0], ast.Constant)
            and type(element.elts[0].value) is str
            and element.elts[0].value == name
            and _type_expression(element.elts[1]) == type_name
        ):
            return False
    return True


def _canonical_explicit_access(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.ClassDef)
        and node.name == "EXPLICIT_ACCESS_W"
        and _structure_body_ok(
            node,
            _EXPECTED_STRUCTURES["EXPLICIT_ACCESS_W"],
        )
    )


def _methods_only_class_ok(node: ast.ClassDef) -> bool:
    """Allow a docstring and methods only; no class-level executable code."""
    if node.decorator_list or node.keywords:
        return False
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and type(statement.value.value) is str
        ):
            continue
        return False
    return True


def _module_classes_ok(
    module: ast.Module,
    *,
    require_all: bool = False,
) -> bool:
    """Validate every module-level class body, not just its header."""
    seen: set[str] = set()
    for statement in module.body:
        if not isinstance(statement, ast.ClassDef):
            continue
        bases = [_target_path(base) for base in statement.bases]
        if "ctypes.Structure" in bases:
            expected = _EXPECTED_STRUCTURES.get(statement.name)
            if expected is None or statement.name in seen:
                return False
            if not _structure_body_ok(statement, expected):
                return False
            seen.add(statement.name)
            continue
        if (
            statement.name == "WindowsSandboxManager"
            and bases == ["BaseSandboxManager"]
        ):
            if not _methods_only_class_ok(statement):
                return False
            continue
        return False
    if require_all and seen != set(_EXPECTED_STRUCTURES):
        return False
    return True


def _module_bindings_ok(module: ast.Module) -> bool:
    grouped: dict[str, list[tuple[ast.AST, str]]] = {}
    for name, node, kind in _binding_entries(module):
        if name in _PROTECTED_NAMES:
            grouped.setdefault(name, []).append((node, kind))

    for name, entries in grouped.items():
        if len(entries) != 1:
            return False
        node, kind = entries[0]
        if name == "ctypes":
            if kind != "import" or not isinstance(node, ast.Import):
                return False
            if len(node.names) != 1:
                return False
            alias = node.names[0]
            if alias.name != "ctypes" or alias.asname is not None:
                return False
        elif name in {"_advapi32", "_kernel32"}:
            if kind != "assign" or not _canonical_windll(node, name):
                return False
        elif name == "EXPLICIT_ACCESS_W":
            if kind != "class" or not _canonical_explicit_access(node):
                return False
        else:
            if kind != "assign" or not _canonical_constant(node, name):
                return False
    return True


def _target_root(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _target_root(node.value)
    if isinstance(node, ast.Subscript):
        return _target_root(node.value)
    return None


def _module_assignment_value_ok(name: str, value: ast.AST) -> bool:
    if isinstance(value, ast.Constant):
        return True
    return name.startswith("_") and _canonical_windll_value(name, value)


def _module_shape_ok(module: ast.Module) -> bool:
    """Allow only docstrings, imports, safe assignments and definitions."""
    for stmt in module.body:
        if isinstance(
            stmt,
            (
                ast.Import,
                ast.ImportFrom,
                ast.ClassDef,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            continue
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1:
                return False
            target = stmt.targets[0]
            if not isinstance(target, ast.Name):
                return False
            if not _module_assignment_value_ok(target.id, stmt.value):
                return False
            continue
        if isinstance(stmt, ast.AnnAssign):
            if not isinstance(stmt.target, ast.Name):
                return False
            if not isinstance(stmt.value, ast.Constant):
                return False
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if isinstance(stmt.value.value, str):
                continue
        return False
    return True


def _attribute_mutations_ok(module: ast.Module) -> bool:
    """Reject monkeypatching protected receivers or their callables."""
    protected_roots = {"ctypes", "_advapi32", "_kernel32", "EXPLICIT_ACCESS_W"}
    for node in ast.walk(module):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
            if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            elif isinstance(node, ast.Delete):
                targets = list(node.targets)
            else:
                targets = list(node.targets)
            for target in targets:
                if not isinstance(target, (ast.Attribute, ast.Subscript)):
                    continue
                root = _target_root(target)
                if root in protected_roots:
                    return False
        if isinstance(node, ast.Call):
            last = (_call_qualified_name(node) or "").split(".")[-1]
            if last in {"setattr", "__setattr__"}:
                return False
    return True


def _local_bindings_ok(module: ast.Module) -> bool:
    """Reject protected bindings in any function or class scope.

    The documented module binds these names once at module scope. A local
    rebinding, parameter, nested def/class, import alias, loop target,
    with-as target, walrus, or match binding would shadow that meaning.
    """
    for node in ast.walk(module):
        if not isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            continue
        for name, _binding_node, _kind in _binding_entries(node):
            if name in _PROTECTED_NAMES:
                return False
    return True


_ALIASABLE_PROTECTED = frozenset({
    "ctypes",
    "_advapi32",
    "_kernel32",
    "EXPLICIT_ACCESS_W",
})


def _bare_protected_name(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _ALIASABLE_PROTECTED
    if isinstance(node, (ast.Tuple, ast.List)):
        return any(_bare_protected_name(element) for element in node.elts)
    return False


def _protected_alias_ok(module: ast.Module) -> bool:
    """Reject copying a protected object into an untracked local alias."""
    for node in ast.walk(module):
        if isinstance(node, ast.Assign):
            if not any(
                isinstance(target, (ast.Name, ast.Tuple, ast.List))
                for target in node.targets
            ):
                continue
            if _bare_protected_name(node.value):
                return False
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, (ast.Name, ast.Tuple, ast.List)):
                continue
            if node.value is not None and _bare_protected_name(node.value):
                return False
    return True


_EXPECTED_IMPORTS: tuple[
    tuple[str, str, int, tuple[tuple[str, str | None], ...]],
    ...,
] = (
    ("from", "__future__", 0, (("annotations", None),)),
    ("import", "", 0, (("ctypes", None),)),
    ("import", "", 0, (("os", None),)),
    ("import", "", 0, (("re", None),)),
    ("import", "", 0, (("shlex", None),)),
    ("import", "", 0, (("shutil", None),)),
    ("import", "", 0, (("subprocess", None),)),
    ("import", "", 0, (("sys", None),)),
    ("import", "", 0, (("threading", None),)),
    ("import", "", 0, (("time", None),)),
    ("import", "", 0, (("uuid", None),)),
    ("from", "ctypes", 0, (("wintypes", None),)),
    ("from", "pathlib", 0, (("Path", None),)),
    (
        "from",
        "typing",
        0,
        (
            ("Any", None),
            ("Dict", None),
            ("List", None),
            ("Optional", None),
            ("Tuple", None),
        ),
    ),
    (
        "from",
        "src.security.contracts",
        0,
        (
            ("ExecutionMode", None),
            ("ExecutionRequest", None),
            ("SAFE_ENVIRONMENT_KEYS", None),
            ("SENSITIVE_SECRET_PATTERNS", None),
            ("SandboxBackendType", None),
            ("SecurityViolationType", None),
        ),
    ),
    (
        "from",
        "src.security.sandbox.base",
        0,
        (("BaseSandboxManager", None),),
    ),
)

_EXPECTED_WINDLL_DECLARATIONS = (
    "_kernel32",
    "_advapi32",
    "_userenv",
    "_user32",
)

_EXPECTED_MODULE_CONSTANTS: tuple[tuple[str, int], ...] = (
    ("JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE", 8192),
    ("JOB_OBJECT_LIMIT_ACTIVE_PROCESS", 8),
    ("JOB_OBJECT_LIMIT_JOB_MEMORY", 512),
    ("JobObjectExtendedLimitInformation", 9),
    ("JOB_OBJECT_CPU_RATE_CONTROL_ENABLE", 1),
    ("JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP", 4),
    ("JobObjectCpuRateControlInformation", 15),
    ("PROC_THREAD_ATTRIBUTE_HANDLE_LIST", 131074),
    ("PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES", 131081),
    ("EXTENDED_STARTUPINFO_PRESENT", 524288),
    ("CREATE_NO_WINDOW", 134217728),
    ("CREATE_SUSPENDED", 4),
    ("STARTF_USESTDHANDLES", 256),
    ("GENERIC_ALL", 0x10000000),
    ("GENERIC_WRITE", 0x40000000),
    ("GENERIC_READ", 0x80000000),
    ("FILE_SHARE_READ", 1),
    ("FILE_SHARE_WRITE", 2),
    ("CREATE_ALWAYS", 2),
    ("OPEN_EXISTING", 3),
    ("FILE_ATTRIBUTE_NORMAL", 0x80),
    ("SE_WINDOW_OBJECT", 7),
    ("DACL_SECURITY_INFORMATION", 4),
    ("GRANT_ACCESS", 1),
    ("NO_INHERITANCE", 0),
    ("TRUSTEE_IS_NAME", 1),
    ("TRUSTEE_IS_WELL_KNOWN_GROUP", 5),
)

_EXPECTED_STRUCTURE_ORDER = (
    "IO_COUNTERS",
    "JOBOBJECT_BASIC_LIMIT_INFORMATION",
    "JOBOBJECT_EXTENDED_LIMIT_INFORMATION",
    "JOBOBJECT_CPU_RATE_CONTROL_INFORMATION",
    "SECURITY_ATTRIBUTES",
    "SECURITY_CAPABILITIES",
    "STARTUPINFOW",
    "STARTUPINFOEXW",
    "PROCESS_INFORMATION",
    "TRUSTEE_W",
    "EXPLICIT_ACCESS_W",
)

_EXPECTED_DECLARATIONS: tuple[tuple[str, str | None], ...] = (
    ("docstring", None),
    *[("import", None)] * len(_EXPECTED_IMPORTS),
    *[("assign", name) for name in _EXPECTED_WINDLL_DECLARATIONS],
    *[("assign", name) for name, _value in _EXPECTED_MODULE_CONSTANTS],
    *[("class", name) for name in _EXPECTED_STRUCTURE_ORDER],
    ("assign", "_winsta_desktop_granted"),
    ("function", "_ensure_windowstation_desktop_access"),
    ("class", "WindowsSandboxManager"),
)

_HELPER_SPEC = (
    "_ensure_windowstation_desktop_access",
    (),
    "bool",
    (),
)

_MANAGER_DOCSTRING = (
    "\n"
    "    Windows execution sandbox enforcing:\n"
    "    1. AppContainer Token Isolation: kernel-enforced network denial "
    "(0 capabilities) and NTFS DACL jailing.\n"
    "    2. Windows Job Object: process tree termination (KILL_ON_JOB_CLOSE), "
    "active process cap, memory limits, CPU hard cap.\n"
    "    3. Minimal Allowlisted Environment: stripping all API keys, SSH keys, "
    "cloud credentials.\n"
    "    4. Output Byte Capping: Preventing memory exhaustion via excessive "
    "stdout/stderr (1MB cap).\n"
    "    5. Fallback Protection: Fail-closed fallback to Job Object isolation "
    "if AppContainer is unavailable.\n"
    "    "
)

_MANAGER_METHOD_SPECS: tuple[
    tuple[
        str,
        tuple[tuple[str, str | None, str | None], ...],
        str,
        tuple[str, ...],
    ],
    ...,
] = (
    (
        "__init__",
        (
            ("self", None, None),
            ("use_appcontainer", "bool", "True"),
        ),
        "None",
        (),
    ),
    (
        "backend_type",
        (("self", None, None),),
        "SandboxBackendType",
        ("property",),
    ),
    (
        "appcontainer_sid_str",
        (("self", None, None),),
        "Optional[str]",
        ("property",),
    ),
    (
        "get_capabilities",
        (("self", None, None),),
        "Dict[str, bool]",
        (),
    ),
    (
        "initialize",
        (
            ("self", None, None),
            ("request", "ExecutionRequest", None),
            ("staging_dir", "Path", None),
        ),
        "None",
        (),
    ),
    (
        "_sanitize_environment",
        (
            ("self", None, None),
            ("request", "ExecutionRequest", None),
            ("staging_dir", "Path", None),
        ),
        "Dict[str, str]",
        (),
    ),
    (
        "_inspect_filesystem_safety",
        (
            ("self", None, None),
            ("request", "ExecutionRequest", None),
            ("staging_dir", "Path", None),
        ),
        "Tuple[bool, Optional[str]]",
        (),
    ),
    (
        "execute",
        (
            ("self", None, None),
            ("request", "ExecutionRequest", None),
            ("staging_dir", "Path", None),
            ("abort_event", "Optional[Any]", "None"),
        ),
        "Dict[str, Any]",
        (),
    ),
    (
        "_execute_appcontainer",
        (
            ("self", None, None),
            ("request", "ExecutionRequest", None),
            ("staging_dir", "Path", None),
            ("cwd", "str", None),
            ("env", "Dict[str, str]", None),
            ("abort_event", "Optional[Any]", None),
        ),
        "Dict[str, Any]",
        (),
    ),
    (
        "_execute_job_object_fallback",
        (
            ("self", None, None),
            ("request", "ExecutionRequest", None),
            ("staging_dir", "Path", None),
            ("cwd", "str", None),
            ("env", "Dict[str, str]", None),
            ("abort_event", "Optional[Any]", None),
        ),
        "Dict[str, Any]",
        (),
    ),
    (
        "_query_job_counters",
        (("self", None, None),),
        "None",
        (),
    ),
    (
        "terminate",
        (("self", None, None),),
        "None",
        (),
    ),
    (
        "cleanup",
        (
            ("self", None, None),
            ("staging_dir", "Path", None),
        ),
        "str",
        (),
    ),
)


def _import_spec(
    node: ast.stmt,
) -> tuple[str, str, int, tuple[tuple[str, str | None], ...]] | None:
    if isinstance(node, ast.Import):
        return (
            "import",
            "",
            0,
            tuple((alias.name, alias.asname) for alias in node.names),
        )
    if isinstance(node, ast.ImportFrom):
        return (
            "from",
            node.module or "",
            node.level,
            tuple((alias.name, alias.asname) for alias in node.names),
        )
    return None


def _module_declarations_ok(module: ast.Module) -> bool:
    """Require the exact declaration sequence, identity, type and order."""
    if len(module.body) != len(_EXPECTED_DECLARATIONS):
        return False
    constants = dict(_EXPECTED_MODULE_CONSTANTS)
    windll_names = set(_EXPECTED_WINDLL_DECLARATIONS)
    import_index = 0

    for stmt, (kind, name) in zip(module.body, _EXPECTED_DECLARATIONS):
        if kind == "docstring":
            if not (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and type(stmt.value.value) is str
            ):
                return False
            continue

        if kind == "import":
            if import_index >= len(_EXPECTED_IMPORTS):
                return False
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                if any(alias.name == "*" for alias in stmt.names):
                    return False
            if _import_spec(stmt) != _EXPECTED_IMPORTS[import_index]:
                return False
            import_index += 1
            continue

        if kind == "assign":
            if not (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == name
            ):
                return False
            if name in windll_names:
                if not _canonical_windll_value(name, stmt.value):
                    return False
            elif name in constants:
                if not (
                    isinstance(stmt.value, ast.Constant)
                    and type(stmt.value.value) is int
                    and stmt.value.value == constants[name]
                ):
                    return False
            elif name == "_winsta_desktop_granted":
                if not (
                    isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is False
                ):
                    return False
            else:
                return False
            continue

        if kind == "class":
            if not (
                isinstance(stmt, ast.ClassDef)
                and stmt.name == name
            ):
                return False
            continue

        if kind == "function":
            if not (
                isinstance(stmt, ast.FunctionDef)
                and stmt.name == name
            ):
                return False
            continue

        return False

    return import_index == len(_EXPECTED_IMPORTS)


def _function_signature_ok(
    node: ast.AST,
    params: tuple[tuple[str, str | None, str | None], ...],
    returns: str,
    decorators: tuple[str, ...],
) -> bool:
    if not isinstance(node, ast.FunctionDef):
        return False
    if getattr(node, "type_params", []):
        return False
    if node.type_comment:
        return False
    if [ast.unparse(item) for item in node.decorator_list] != list(decorators):
        return False

    args = node.args
    if args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg:
        return False
    if len(args.args) != len(params):
        return False
    for argument, (name, annotation, _default) in zip(args.args, params):
        if argument.arg != name:
            return False
        actual_annotation = (
            ast.unparse(argument.annotation)
            if argument.annotation is not None
            else None
        )
        if actual_annotation != annotation:
            return False

    expected_defaults = [
        default for (_name, _annotation, default) in params
        if default is not None
    ]
    if [ast.unparse(item) for item in args.defaults] != expected_defaults:
        return False
    if args.kw_defaults:
        return False

    actual_returns = (
        ast.unparse(node.returns) if node.returns is not None else None
    )
    return actual_returns == returns


def _helper_declaration_ok(module: ast.Module) -> bool:
    helpers = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_ensure_windowstation_desktop_access"
    ]
    if len(helpers) != 1:
        return False
    name, params, returns, decorators = _HELPER_SPEC
    return (
        helpers[0].name == name
        and _function_signature_ok(
            helpers[0],
            params,  # type: ignore[arg-type]
            returns,  # type: ignore[arg-type]
            decorators,
        )
    )


def _manager_declaration_ok(module: ast.Module) -> bool:
    managers = [
        node
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and node.name == "WindowsSandboxManager"
    ]
    if len(managers) != 1:
        return False
    node = managers[0]
    if node.decorator_list or node.keywords:
        return False
    if getattr(node, "type_params", []):
        return False
    if [ast.unparse(base) for base in node.bases] != ["BaseSandboxManager"]:
        return False
    if not node.body:
        return False
    docstring = node.body[0]
    if not (
        isinstance(docstring, ast.Expr)
        and isinstance(docstring.value, ast.Constant)
        and docstring.value.value == _MANAGER_DOCSTRING
    ):
        return False
    methods = node.body[1:]
    if len(methods) != len(_MANAGER_METHOD_SPECS):
        return False
    for method, spec in zip(methods, _MANAGER_METHOD_SPECS):
        if not isinstance(method, ast.FunctionDef):
            return False
        name, params, returns, decorators = spec
        if method.name != name:
            return False
        if not _function_signature_ok(
            method,
            params,
            returns,
            decorators,
        ):
            return False
    return True


def _security_call_lines(path: Path, *, full_module: bool = False) -> set[int]:
    """Allow only the exact documented AppContainer operation.

    This is an exact structural whitelist, not a permissive traversal. The
    function must have the documented signature and its body must be exactly
    the eighteen documented statements. Protected names may not be rebound or
    shadowed at module scope, in an enclosing scope, or inside the function.

    ``full_module=True`` additionally requires the exact sandbox import
    manifest, module declaration manifest, helper signature, manager method
    manifest, and the complete set of ctypes structures. Synthetic snippets in
    earlier phases use the default partial mode.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_grant_to_object"
    ]
    if len(functions) != 1:
        return set()
    function = functions[0]

    if not _grant_signature_ok(function):
        return set()
    if not _grant_body_ok(function.body):
        return set()
    if not _module_shape_ok(tree):
        return set()
    if not _module_bindings_ok(tree):
        return set()
    if not _module_classes_ok(tree, require_all=full_module):
        return set()
    if not _local_bindings_ok(tree):
        return set()
    if not _protected_alias_ok(tree):
        return set()
    if not _attribute_mutations_ok(tree):
        return set()
    if full_module:
        if not _module_declarations_ok(tree):
            return set()
        if not _helper_declaration_ok(tree):
            return set()
        if not _manager_declaration_ok(tree):
            return set()

    security_call = function.body[15].body[0].value
    return {security_call.lineno}


def _sandbox_allowed_lines() -> set[int]:
    if not SANDBOX.exists():
        return set()
    text = SANDBOX.read_text(encoding="utf-8")
    if "ALL APPLICATION PACKAGES" not in text or "WD)(A;OICI;GA" in text:
        return set()
    return _security_call_lines(SANDBOX, full_module=True)


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


def _documented_grant_source(
    extra: str = "",
    *,
    before: str = "",
    module_prefix: str = "",
) -> str:
    return (
        module_prefix
        + "def _ensure():\n"
        "    def _grant_to_object(handle):\n"
        + before
        + "        ea = EXPLICIT_ACCESS_W()\n"
        "        ea.grfAccessPermissions = GENERIC_ALL\n"
        "        ea.grfAccessMode = GRANT_ACCESS\n"
        "        ea.grfInheritance = NO_INHERITANCE\n"
        "        ea.Trustee.pMultipleTrustee = None\n"
        "        ea.Trustee.MultipleTrusteeOperation = 0\n"
        "        ea.Trustee.TrusteeForm = TRUSTEE_IS_NAME\n"
        "        ea.Trustee.TrusteeType = TRUSTEE_IS_WELL_KNOWN_GROUP\n"
        "        ea.Trustee.ptstrName = 'ALL APPLICATION PACKAGES'\n"
        "        p_dacl = ctypes.c_void_p()\n"
        "        p_sec_desc = ctypes.c_void_p()\n"
        "        ret = _advapi32.GetSecurityInfo(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, ctypes.byref(p_dacl), None, ctypes.byref(p_sec_desc))\n"
        "        if ret != 0:\n"
        "            return False\n"
        "        p_new_dacl = ctypes.c_void_p()\n"
        "        ret2 = _advapi32.SetEntriesInAclW(1, ctypes.byref(ea), p_dacl, ctypes.byref(p_new_dacl))\n"
        "        if ret2 == 0:\n"
        "            _advapi32.SetSecurityInfo(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_new_dacl, None)\n"
        "            _kernel32.LocalFree(p_new_dacl)\n"
        "        _kernel32.LocalFree(p_sec_desc)\n"
        "        return ret2 == 0\n"
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
        "        _advapi32.SetSecurityInfo(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_other, None)\n"
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


@pytest.mark.skipif(not hasattr(ctypes, "WinDLL"), reason="Windows-only ctypes loader")
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


# Phase 1.3.1: alternate AST mutation forms and receiver validation

def test_sandbox_rejects_annotated_trustee_reassignment(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        ea.Trustee.ptstrName: str = 'Everyone'\n"),
        "ann_trustee",
    )


def test_sandbox_rejects_augmented_permissions(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        ea.grfAccessPermissions |= GENERIC_READ\n"),
        "aug_permissions",
    )


def test_sandbox_rejects_setattr_trustee(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        setattr(ea.Trustee, 'ptstrName', 'Everyone')\n"),
        "setattr_trustee",
    )


def test_sandbox_rejects_pmultiple_trustee_mutation(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        ea.Trustee.pMultipleTrustee = p_evil\n"),
        "pmultiple",
    )


def test_sandbox_rejects_multiple_trustee_operation_mutation(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        ea.Trustee.MultipleTrusteeOperation = 1\n"),
        "multiple_op",
    )


def test_sandbox_rejects_p_new_dacl_reassignment(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        p_new_dacl = p_other\n"),
        "pnew_reassign",
    )


def test_sandbox_rejects_p_new_dacl_annotated(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        p_new_dacl: int = 0\n"),
        "pnew_ann",
    )


def test_sandbox_rejects_ea_reassignment(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        ea = other_ea\n"),
        "ea_reassign",
    )


def test_sandbox_rejects_subscript_mutation(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            "        ea.__dict__['grfAccessPermissions'] = GENERIC_READ\n"
        ),
        "subscript_mutation",
    )


def test_sandbox_rejects_fake_setsecurity_receiver(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "_advapi32.SetSecurityInfo", "evil.SetSecurityInfo",
    )
    _assert_grant_rejected(tmp_path, source, "fake_setsecurity")


def test_sandbox_rejects_fake_setentries_receiver(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "_advapi32.SetEntriesInAclW", "evil.SetEntriesInAclW",
    )
    _assert_grant_rejected(tmp_path, source, "fake_setentries")


def test_sandbox_rejects_fake_byref_receiver(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "ctypes.byref(ea)", "evil.byref(ea)",
    )
    _assert_grant_rejected(tmp_path, source, "fake_byref")


def test_sandbox_rejects_fake_c_void_p_receiver(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "p_new_dacl = ctypes.c_void_p()", "p_new_dacl = evil.c_void_p()",
    )
    _assert_grant_rejected(tmp_path, source, "fake_cvoidp")


def test_sandbox_rejects_localfree_before_setsecurity(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "            _advapi32.SetSecurityInfo(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_new_dacl, None)\n"
        "            _kernel32.LocalFree(p_new_dacl)\n",
        "            _kernel32.LocalFree(p_new_dacl)\n"
        "            _advapi32.SetSecurityInfo(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_new_dacl, None)\n",
    )
    _assert_grant_rejected(tmp_path, source, "free_before_security")


def test_sandbox_rejects_extra_unapproved_mutation(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        ea.grfAccessMode = DENY_ACCESS\n"),
        "extra_mode",
    )


def test_sandbox_rejects_extra_unapproved_call(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        helper()\n"),
        "extra_call",
    )


def test_sandbox_rejects_dynamic_security_call(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            "        getattr(_advapi32, 'SetSecurityInfo')"
            "(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_new_dacl, None)\n"
        ),
        "dynamic_call",
    )


def test_documented_grant_remains_accepted(tmp_path: Path) -> None:
    source = _documented_grant_source()
    sample = tmp_path / "positive.py"
    sample.write_text(source, encoding="utf-8")
    expected = next(
        i for i, line in enumerate(source.splitlines(), 1)
        if "_advapi32.SetSecurityInfo" in line
    )
    assert _security_call_lines(sample) == {expected}

# ---------------------------------------------------------------------------
# Phase 1.3.2: alias, binding, shadowing and full-contract validation
# ---------------------------------------------------------------------------

_GET_INFO_LINE = (
    "        ret = _advapi32.GetSecurityInfo(handle, SE_WINDOW_OBJECT, "
    "DACL_SECURITY_INFORMATION, None, None, ctypes.byref(p_dacl), None, "
    "ctypes.byref(p_sec_desc))\n"
)


@pytest.mark.parametrize(
    "snippet",
    [
        "        ea_alias = ea\n"
        "        ea_alias.Trustee.ptstrName = 'Everyone'\n",
        "        trustee = ea.Trustee\n"
        "        trustee.ptstrName = 'Everyone'\n",
        "        advapi_alias = _advapi32\n"
        "        advapi_alias.SetSecurityInfo(handle, SE_WINDOW_OBJECT, "
        "DACL_SECURITY_INFORMATION, None, None, p_new_dacl, None)\n",
        "        kernel_alias = _kernel32\n"
        "        kernel_alias.LocalFree(p_new_dacl)\n",
        "        ctypes_alias = ctypes\n"
        "        ctypes_alias.byref(ea)\n",
        "        pnew_alias = p_new_dacl\n"
        "        pnew_alias = p_other\n",
    ],
)
def test_sandbox_rejects_protected_object_aliases(
    tmp_path: Path,
    snippet: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(snippet),
        "protected_alias",
    )


@pytest.mark.parametrize("name", ["_advapi32", "_kernel32", "ctypes"])
def test_sandbox_rejects_receiver_rebinding(
    tmp_path: Path,
    name: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(before=f"        {name} = evil\n"),
        "receiver_rebind",
    )


@pytest.mark.parametrize(
    "name",
    [
        "EXPLICIT_ACCESS_W",
        "GENERIC_ALL",
        "GRANT_ACCESS",
        "NO_INHERITANCE",
        "TRUSTEE_IS_NAME",
        "TRUSTEE_IS_WELL_KNOWN_GROUP",
        "SE_WINDOW_OBJECT",
        "DACL_SECURITY_INFORMATION",
    ],
)
def test_sandbox_rejects_constant_or_constructor_rebinding(
    tmp_path: Path,
    name: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(before=f"        {name} = evil\n"),
        "constant_rebind",
    )


def test_sandbox_rejects_nested_constructor_shadowing(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "    def _grant_to_object(handle):",
        "    def EXPLICIT_ACCESS_W():\n"
        "        return evil\n"
        "    def _grant_to_object(handle):",
    )
    _assert_grant_rejected(tmp_path, source, "nested_constructor")


def test_sandbox_rejects_nested_function_shadowing(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "    def _grant_to_object(handle):",
        "    def _advapi32():\n"
        "        return evil\n"
        "    def _grant_to_object(handle):",
    )
    _assert_grant_rejected(tmp_path, source, "nested_function")


def test_sandbox_rejects_nested_class_shadowing(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "    def _grant_to_object(handle):",
        "    class ctypes:\n"
        "        pass\n"
        "    def _grant_to_object(handle):",
    )
    _assert_grant_rejected(tmp_path, source, "nested_class")


def test_sandbox_rejects_module_receiver_rebinding(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(module_prefix="_advapi32 = evil\n"),
        "module_receiver",
    )


def test_sandbox_rejects_module_constant_rebinding(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(module_prefix="GENERIC_ALL = 0\n"),
        "module_constant",
    )


def test_sandbox_rejects_module_ctypes_rebinding(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(module_prefix="ctypes = evil\n"),
        "module_ctypes",
    )


def test_sandbox_rejects_import_alias_shadowing_in_enclosing_scope(
    tmp_path: Path,
) -> None:
    source = _documented_grant_source().replace(
        "    def _grant_to_object(handle):",
        "    import evil as _advapi32\n"
        "    def _grant_to_object(handle):",
    )
    _assert_grant_rejected(tmp_path, source, "import_alias_local")


def test_sandbox_rejects_module_import_alias_shadowing(tmp_path: Path) -> None:
    _assert_rejected_module_prefix(
        tmp_path,
        "import evil as ctypes\n",
        "import_alias_module",
    )


def test_sandbox_rejects_module_from_import_shadowing(tmp_path: Path) -> None:
    _assert_rejected_module_prefix(
        tmp_path,
        "from evil import _advapi32\n",
        "from_import_module",
    )


def _assert_rejected_module_prefix(
    tmp_path: Path,
    prefix: str,
    name: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(module_prefix=prefix),
        name,
    )


@pytest.mark.parametrize(
    "snippet",
    [
        "        ea.Trustee.ptstrName, = ('Everyone',)\n",
        "        [ea.Trustee.ptstrName] = ['Everyone']\n",
        "        ea, = (evil,)\n",
        "        [ea] = [evil]\n",
    ],
)
def test_sandbox_rejects_destructuring_mutation(
    tmp_path: Path,
    snippet: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(snippet),
        "destructuring",
    )


@pytest.mark.parametrize(
    "snippet",
    [
        "        (ea := evil)\n",
        "        (ret2 := 0)\n",
        "        (ctypes := evil)\n",
    ],
)
def test_sandbox_rejects_named_expression_mutation(
    tmp_path: Path,
    snippet: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(snippet),
        "walrus",
    )


def test_sandbox_rejects_walrus_in_success_test(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "        if ret2 == 0:",
        "        if (ret2 := 0) == 0:",
    )
    _assert_grant_rejected(tmp_path, source, "walrus_branch")


def test_sandbox_rejects_loop_target_binding(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            "        for ea in [evil]:\n"
            "            pass\n"
        ),
        "loop_target",
    )


def test_sandbox_rejects_context_manager_binding(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            "        with open('x') as ctypes:\n"
            "            pass\n"
        ),
        "with_target",
    )


_GET_INFO_ARGS = [
    "handle",
    "SE_WINDOW_OBJECT",
    "DACL_SECURITY_INFORMATION",
    "None",
    "None",
    "ctypes.byref(p_dacl)",
    "None",
    "ctypes.byref(p_sec_desc)",
]

_WRONG_GET_INFO_ARGS = [
    "evil_handle",
    "SE_KERNEL_OBJECT",
    "OWNER_SECURITY_INFORMATION",
    "p_owner",
    "p_group",
    "ctypes.byref(p_other)",
    "p_sacl",
    "ctypes.byref(p_other)",
]


@pytest.mark.parametrize(
    "index",
    list(range(len(_GET_INFO_ARGS))),
)
def test_sandbox_rejects_each_changed_getsecurity_argument(
    tmp_path: Path,
    index: int,
) -> None:
    changed = list(_GET_INFO_ARGS)
    changed[index] = _WRONG_GET_INFO_ARGS[index]
    source = _documented_grant_source().replace(
        _GET_INFO_LINE,
        "        ret = _advapi32.GetSecurityInfo("
        + ", ".join(changed)
        + ")\n",
    )
    _assert_grant_rejected(
        tmp_path,
        source,
        f"get_info_arg_{index}",
    )


def test_sandbox_rejects_wrong_second_localfree_argument(
    tmp_path: Path,
) -> None:
    source = _documented_grant_source().replace(
        "        _kernel32.LocalFree(p_sec_desc)\n",
        "        _kernel32.LocalFree(p_new_dacl)\n",
    )
    _assert_grant_rejected(tmp_path, source, "second_free_arg")


@pytest.mark.parametrize(
    "old,new",
    [
        ("        if ret != 0:\n", "        if ret == 0:\n"),
        (
            "        if ret != 0:\n            return False\n",
            "        if ret != 0:\n            return True\n",
        ),
    ],
)
def test_sandbox_rejects_changed_failure_branch(
    tmp_path: Path,
    old: str,
    new: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source().replace(old, new),
        "failure_branch",
    )


def test_sandbox_rejects_changed_success_branch(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "        if ret2 == 0:",
        "        if ret2 != 0:",
    )
    _assert_grant_rejected(tmp_path, source, "success_branch")


@pytest.mark.parametrize(
    "old,new",
    [
        ("        return ret2 == 0\n", "        return True\n"),
        ("        return ret2 == 0\n", "        return ret2 != 0\n"),
    ],
)
def test_sandbox_rejects_changed_return_behavior(
    tmp_path: Path,
    old: str,
    new: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source().replace(old, new),
        "return_behavior",
    )


def test_sandbox_rejects_allocation_after_entries_call(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "        p_new_dacl = ctypes.c_void_p()\n"
        "        ret2 = _advapi32.SetEntriesInAclW(1, ctypes.byref(ea), p_dacl, ctypes.byref(p_new_dacl))\n",
        "        ret2 = _advapi32.SetEntriesInAclW(1, ctypes.byref(ea), p_dacl, ctypes.byref(p_new_dacl))\n"
        "        p_new_dacl = ctypes.c_void_p()\n",
    )
    _assert_grant_rejected(tmp_path, source, "allocation_order")


def test_sandbox_rejects_signature_change(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "    def _grant_to_object(handle):",
        "    def _grant_to_object(handle, extra):",
    )
    _assert_grant_rejected(tmp_path, source, "signature_change")


def test_sandbox_rejects_decorated_grant(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "    def _grant_to_object(handle):",
        "    @evil\n"
        "    def _grant_to_object(handle):",
    )
    _assert_grant_rejected(tmp_path, source, "decorated_grant")


def test_sandbox_rejects_duplicate_grant_function(tmp_path: Path) -> None:
    source = _documented_grant_source().replace(
        "def _ensure():",
        "def _grant_to_object(handle):\n"
        "    pass\n\n"
        "def _ensure():",
    )
    _assert_grant_rejected(tmp_path, source, "duplicate_grant")

@pytest.mark.parametrize(
    "prefix",
    [
        "def _advapi32():\n    return evil\n",
        "def EXPLICIT_ACCESS_W():\n    return evil\n",
        "class ctypes:\n    pass\n",
        "class GENERIC_ALL:\n    pass\n",
    ],
)
def test_sandbox_rejects_module_function_or_class_shadowing(
    tmp_path: Path,
    prefix: str,
) -> None:
    _assert_rejected_module_prefix(
        tmp_path,
        prefix,
        "module_shadow",
    )


@pytest.mark.parametrize(
    "prefix",
    [
        "ctypes.byref = evil\n",
        "ctypes.c_void_p = evil\n",
        "_advapi32.SetSecurityInfo = evil\n",
        "_kernel32.LocalFree = evil\n",
        "del ctypes.byref\n",
        "setattr(ctypes, 'byref', evil)\n",
        "globals()['ctypes'] = evil\n",
    ],
)
def test_sandbox_rejects_protected_attribute_monkeypatching(
    tmp_path: Path,
    prefix: str,
) -> None:
    _assert_rejected_module_prefix(
        tmp_path,
        prefix,
        "attribute_patch",
    )


def test_sandbox_rejects_attribute_monkeypatch_in_sibling_scope(
    tmp_path: Path,
) -> None:
    source = _documented_grant_source(
        "\n"
        "def helper():\n"
        "    ctypes.byref = evil\n"
    )
    _assert_grant_rejected(tmp_path, source, "sibling_attribute_patch")

def test_sandbox_rejects_wrong_first_localfree_argument(
    tmp_path: Path,
) -> None:
    source = _documented_grant_source().replace(
        "            _kernel32.LocalFree(p_new_dacl)\n",
        "            _kernel32.LocalFree(p_sec_desc)\n",
    )
    _assert_grant_rejected(tmp_path, source, "first_free_arg")

def test_sandbox_rejects_any_extra_statement(tmp_path: Path) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("        unused = 1\n"),
        "extra_statement",
    )

# ---------------------------------------------------------------------------
# Phase 1.3.3: class-body and module-initialisation validation
# ---------------------------------------------------------------------------

_TRUSTEE_FIELDS = [
    ("pMultipleTrustee", "ctypes.c_void_p"),
    ("MultipleTrusteeOperation", "wintypes.DWORD"),
    ("TrusteeForm", "wintypes.DWORD"),
    ("TrusteeType", "wintypes.DWORD"),
    ("ptstrName", "wintypes.LPWSTR"),
]

_EXPLICIT_FIELDS = [
    ("grfAccessPermissions", "wintypes.DWORD"),
    ("grfAccessMode", "wintypes.DWORD"),
    ("grfInheritance", "wintypes.DWORD"),
    ("Trustee", "TRUSTEE_W"),
]


def _structure_class_source(
    name: str,
    fields: list[tuple[str, str]],
    extra_body: str = "",
) -> str:
    lines = [f"class {name}(ctypes.Structure):\n"]
    if extra_body:
        lines.append(extra_body)
    lines.append("    _fields_ = [\n")
    for field_name, field_type in fields:
        lines.append(f'        ("{field_name}", {field_type}),\n')
    lines.append("    ]\n")
    return "".join(lines)


def _structures_source(
    *,
    explicit_fields: list[tuple[str, str]] | None = None,
    trustee_fields: list[tuple[str, str]] | None = None,
    extra_body: str = "",
    extra_class: str = "",
) -> str:
    source = (
        _structure_class_source(
            "TRUSTEE_W",
            trustee_fields if trustee_fields is not None else _TRUSTEE_FIELDS,
        )
        + "\n"
        + _structure_class_source(
            "EXPLICIT_ACCESS_W",
            explicit_fields if explicit_fields is not None else _EXPLICIT_FIELDS,
            extra_body,
        )
    )
    if extra_class:
        source += "\n" + extra_class
    return source


def test_documented_structure_classes_remain_accepted(tmp_path: Path) -> None:
    source = _documented_grant_source(module_prefix=_structures_source())
    sample = tmp_path / "positive_structures.py"
    sample.write_text(source, encoding="utf-8")
    expected = next(
        i for i, line in enumerate(source.splitlines(), 1)
        if "_advapi32.SetSecurityInfo" in line
    )
    assert _security_call_lines(sample) == {expected}


@pytest.mark.parametrize(
    "extra_body",
    [
        "    helper()\n",
        "    exec('x = 1')\n",
        "    s = setattr\n    s(ctypes, 'byref', evil)\n",
        "    class Nested:\n        pass\n",
        "    def helper(self):\n        pass\n",
        "    c = ctypes\n    c.byref = evil\n",
    ],
)
def test_sandbox_rejects_executable_structure_class_body(
    tmp_path: Path,
    extra_body: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            module_prefix=_structures_source(extra_body=extra_body),
        ),
        "structure_body",
    )


def test_sandbox_rejects_reordered_explicit_fields(tmp_path: Path) -> None:
    fields = list(_EXPLICIT_FIELDS)
    fields[0], fields[1] = fields[1], fields[0]
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            module_prefix=_structures_source(explicit_fields=fields),
        ),
        "field_order",
    )


def test_sandbox_rejects_changed_explicit_field_type(tmp_path: Path) -> None:
    fields = list(_EXPLICIT_FIELDS)
    fields[1] = (fields[1][0], "ctypes.c_void_p")
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            module_prefix=_structures_source(explicit_fields=fields),
        ),
        "field_type",
    )


def test_sandbox_rejects_extra_explicit_field(tmp_path: Path) -> None:
    fields = list(_EXPLICIT_FIELDS)
    fields.append(("Extra", "wintypes.DWORD"))
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            module_prefix=_structures_source(explicit_fields=fields),
        ),
        "extra_field",
    )


def test_sandbox_rejects_reordered_trustee_fields(tmp_path: Path) -> None:
    fields = list(_TRUSTEE_FIELDS)
    fields[0], fields[1] = fields[1], fields[0]
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            module_prefix=_structures_source(trustee_fields=fields),
        ),
        "trustee_order",
    )


@pytest.mark.parametrize(
    "extra_class",
    [
        "class Evil:\n    evil()\n",
        "class Evil:\n    exec('x = 1')\n",
        "class Evil:\n    pass\n",
    ],
)
def test_sandbox_rejects_extra_module_class(
    tmp_path: Path,
    extra_class: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(
            module_prefix=_structures_source(extra_class=extra_class),
        ),
        "extra_class",
    )


@pytest.mark.parametrize(
    "prefix",
    [
        '_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True) if sys.platform == "linux" else None\n',
        '_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True) if sys.platform == get_platform() else None\n',
        '_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True) if sys.platform == "win32" else 0\n',
        '_advapi32 = ctypes.WinDLL("advapi32", 1, use_last_error=True) if sys.platform == "win32" else None\n',
        '_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True, other=1) if sys.platform == "win32" else None\n',
        '_advapi32 = ctypes.WinDLL("advapi32", use_last_error=False) if sys.platform == "win32" else None\n',
        '_advapi32 = evil.WinDLL("advapi32", use_last_error=True) if sys.platform == "win32" else None\n',
        '_advapi32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None\n',
        '_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)\n',
        '_advapi32 = ctypes.WinDLL("advapi32") if sys.platform == "win32" else None\n',
    ],
)
def test_sandbox_rejects_changed_dll_initialization(
    tmp_path: Path,
    prefix: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(module_prefix=prefix),
        "dll_init",
    )


@pytest.mark.parametrize(
    "prefix",
    [
        "c = ctypes\nc.byref = evil\n",
        "a = _advapi32\na.SetSecurityInfo = evil\n",
    ],
)
def test_sandbox_rejects_module_alias_monkeypatching(
    tmp_path: Path,
    prefix: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(module_prefix=prefix),
        "module_alias_patch",
    )


@pytest.mark.parametrize(
    "helper",
    [
        "def helper():\n    c = ctypes\n    c.byref = evil\n",
        "def helper():\n    a = _advapi32\n    a.SetSecurityInfo = evil\n",
    ],
)
def test_sandbox_rejects_sibling_alias_monkeypatching(
    tmp_path: Path,
    helper: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source("\n" + helper),
        "sibling_alias_patch",
    )


@pytest.mark.parametrize(
    "prefix",
    [
        "x = evil()\n",
        "_winsta_desktop_granted = evil()\n",
        "x = (ctypes,)\n",
    ],
)
def test_sandbox_rejects_executable_module_assignment(
    tmp_path: Path,
    prefix: str,
) -> None:
    _assert_grant_rejected(
        tmp_path,
        _documented_grant_source(module_prefix=prefix),
        "module_expression",
    )

# ---------------------------------------------------------------------------
# Phase 1.3.4: module declaration integrity
# ---------------------------------------------------------------------------

def _sandbox_tree() -> ast.Module:
    return ast.parse(SANDBOX.read_text(encoding="utf-8"))


def _mutated_sandbox_source(mutate) -> str:
    tree = _sandbox_tree()
    mutate(tree)
    return ast.unparse(tree)


def _assert_full_module_rejected(
    tmp_path: Path,
    mutate,
    name: str,
) -> None:
    sample = tmp_path / f"{name}.py"
    sample.write_text(_mutated_sandbox_source(mutate), encoding="utf-8")
    assert _security_call_lines(sample, full_module=True) == set()


def _module_import(tree: ast.Module, name: str) -> ast.Import:
    for node in tree.body:
        if isinstance(node, ast.Import):
            if any(alias.name == name for alias in node.names):
                return node
    raise AssertionError(f"import {name!r} not found")


def _module_from_import(tree: ast.Module, module: str) -> ast.ImportFrom:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            return node
    raise AssertionError(f"from-import {module!r} not found")


def _module_class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name!r} not found")


def _module_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def _manager_method(cls: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"method {name!r} not found")


def _evil_call() -> ast.Call:
    return ast.Call(
        func=ast.Name(id="evil", ctx=ast.Load()),
        args=[],
        keywords=[],
    )


def test_full_sandbox_module_remains_accepted() -> None:
    text = SANDBOX.read_text(encoding="utf-8")
    expected = next(
        i for i, line in enumerate(text.splitlines(), 1)
        if "_advapi32.SetSecurityInfo" in line
    )
    assert _security_call_lines(SANDBOX, full_module=True) == {expected}


def test_sandbox_rejects_arbitrary_import(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        tree.body.insert(1, ast.parse("import json").body[0])

    _assert_full_module_rejected(tmp_path, mutate, "arbitrary_import")


def test_sandbox_rejects_star_import(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        tree.body.insert(1, ast.parse("from os import *").body[0])

    _assert_full_module_rejected(tmp_path, mutate, "star_import")


def test_sandbox_rejects_unexpected_import_alias(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        _module_import(tree, "ctypes").names[0].asname = "c"

    _assert_full_module_rejected(tmp_path, mutate, "import_alias")


def test_sandbox_rejects_duplicate_import(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        duplicate = copy.deepcopy(_module_import(tree, "ctypes"))
        tree.body.insert(3, duplicate)

    _assert_full_module_rejected(tmp_path, mutate, "duplicate_import")


def test_sandbox_rejects_changed_import_source(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        _module_from_import(tree, "pathlib").module = "pathlib2"

    _assert_full_module_rejected(tmp_path, mutate, "changed_import_source")


def test_sandbox_rejects_additional_module_function(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        tree.body.append(ast.parse("def helper():\n    pass").body[0])

    _assert_full_module_rejected(tmp_path, mutate, "extra_function")


def test_sandbox_rejects_duplicate_helper(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        helper = _module_function(tree, "_ensure_windowstation_desktop_access")
        tree.body.append(copy.deepcopy(helper))

    _assert_full_module_rejected(tmp_path, mutate, "duplicate_helper")


def test_sandbox_rejects_decorated_helper(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        helper = _module_function(tree, "_ensure_windowstation_desktop_access")
        helper.decorator_list.append(ast.Name(id="evil", ctx=ast.Load()))

    _assert_full_module_rejected(tmp_path, mutate, "decorated_helper")


def test_sandbox_rejects_helper_decorator_call(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        helper = _module_function(tree, "_ensure_windowstation_desktop_access")
        helper.decorator_list.append(_evil_call())

    _assert_full_module_rejected(tmp_path, mutate, "helper_decorator_call")


def test_sandbox_rejects_executable_helper_default(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        helper = _module_function(tree, "_ensure_windowstation_desktop_access")
        helper.args.args.append(
            ast.arg(arg="value", annotation=None, type_comment=None)
        )
        helper.args.defaults.append(_evil_call())

    _assert_full_module_rejected(tmp_path, mutate, "helper_default")


def test_sandbox_rejects_async_helper(tmp_path: Path) -> None:
    source = SANDBOX.read_text(encoding="utf-8").replace(
        "def _ensure_windowstation_desktop_access() -> bool:",
        "async def _ensure_windowstation_desktop_access() -> bool:",
        1,
    )
    sample = tmp_path / "async_helper.py"
    sample.write_text(source, encoding="utf-8")
    assert _security_call_lines(sample, full_module=True) == set()


def test_sandbox_rejects_additional_manager_class(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        tree.body.append(
            ast.parse(
                "class ExtraManager(BaseSandboxManager):\n    pass"
            ).body[0]
        )

    _assert_full_module_rejected(tmp_path, mutate, "extra_manager")


def test_sandbox_rejects_duplicate_initialize(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        cls = _module_class(tree, "WindowsSandboxManager")
        method = _manager_method(cls, "initialize")
        cls.body.insert(cls.body.index(method) + 1, copy.deepcopy(method))

    _assert_full_module_rejected(tmp_path, mutate, "duplicate_initialize")


def test_sandbox_rejects_additional_manager_method(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        cls = _module_class(tree, "WindowsSandboxManager")
        cls.body.append(ast.parse("def extra(self):\n    pass").body[0])

    _assert_full_module_rejected(tmp_path, mutate, "extra_method")


def test_sandbox_rejects_executable_method_decorator(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        cls = _module_class(tree, "WindowsSandboxManager")
        _manager_method(cls, "terminate").decorator_list.append(_evil_call())

    _assert_full_module_rejected(tmp_path, mutate, "method_decorator")


def test_sandbox_rejects_executable_method_default(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        cls = _module_class(tree, "WindowsSandboxManager")
        _manager_method(cls, "__init__").args.defaults = [_evil_call()]

    _assert_full_module_rejected(tmp_path, mutate, "method_default")


def test_sandbox_rejects_manager_class_assignment(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        cls = _module_class(tree, "WindowsSandboxManager")
        cls.body.insert(1, ast.parse("extra = 1").body[0])

    _assert_full_module_rejected(tmp_path, mutate, "manager_assignment")


def test_sandbox_rejects_manager_nested_class(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        cls = _module_class(tree, "WindowsSandboxManager")
        cls.body.insert(1, ast.parse("class Nested:\n    pass").body[0])

    _assert_full_module_rejected(tmp_path, mutate, "manager_nested_class")


def test_sandbox_rejects_missing_structure(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        tree.body.remove(_module_class(tree, "IO_COUNTERS"))

    _assert_full_module_rejected(tmp_path, mutate, "missing_structure")


def test_sandbox_rejects_duplicate_structure(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        tree.body.append(copy.deepcopy(_module_class(tree, "IO_COUNTERS")))

    _assert_full_module_rejected(tmp_path, mutate, "duplicate_structure")


def test_sandbox_rejects_changed_structure_order(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        first = _module_class(tree, "IO_COUNTERS")
        second = _module_class(tree, "JOBOBJECT_BASIC_LIMIT_INFORMATION")
        first_index = tree.body.index(first)
        second_index = tree.body.index(second)
        tree.body[first_index], tree.body[second_index] = second, first

    _assert_full_module_rejected(tmp_path, mutate, "structure_order")


def test_sandbox_rejects_changed_structure_fields(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        cls = _module_class(tree, "EXPLICIT_ACCESS_W")
        fields = cls.body[0].value.elts
        fields[0], fields[1] = fields[1], fields[0]

    _assert_full_module_rejected(tmp_path, mutate, "structure_fields")


def test_sandbox_rejects_additional_structure_subclass(
    tmp_path: Path,
) -> None:
    def mutate(tree: ast.Module) -> None:
        tree.body.append(
            ast.parse(
                "class Extra(ctypes.Structure):\n"
                "    _fields_ = [('x', ctypes.c_int)]"
            ).body[0]
        )

    _assert_full_module_rejected(tmp_path, mutate, "extra_structure")


def test_sandbox_rejects_changed_structure_base(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        _module_class(tree, "IO_COUNTERS").bases = [
            ast.Name(id="object", ctx=ast.Load())
        ]

    _assert_full_module_rejected(tmp_path, mutate, "structure_base")


def test_sandbox_rejects_structure_class_expression(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        _module_class(tree, "EXPLICIT_ACCESS_W").body.append(
            ast.parse("evil()").body[0]
        )

    _assert_full_module_rejected(tmp_path, mutate, "structure_expression")


def test_sandbox_rejects_structure_class_method(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        _module_class(tree, "EXPLICIT_ACCESS_W").body.append(
            ast.parse("def extra(self):\n    pass").body[0]
        )

    _assert_full_module_rejected(tmp_path, mutate, "structure_method")

def test_sandbox_rejects_changed_import_level(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        _module_from_import(tree, "ctypes").level = 1

    _assert_full_module_rejected(tmp_path, mutate, "import_level")


def test_sandbox_rejects_unapproved_from_import(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        tree.body.insert(1, ast.parse("from os import path").body[0])

    _assert_full_module_rejected(tmp_path, mutate, "unapproved_from_import")


def test_sandbox_rejects_changed_helper_signature(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        helper = _module_function(tree, "_ensure_windowstation_desktop_access")
        helper.args.args.append(
            ast.arg(arg="value", annotation=None, type_comment=None)
        )

    _assert_full_module_rejected(tmp_path, mutate, "helper_signature")


def test_sandbox_rejects_duplicate_manager_class(tmp_path: Path) -> None:
    def mutate(tree: ast.Module) -> None:
        manager = _module_class(tree, "WindowsSandboxManager")
        tree.body.append(copy.deepcopy(manager))

    _assert_full_module_rejected(tmp_path, mutate, "duplicate_manager")
