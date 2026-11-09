"""Phase 1/1.1 security containment and guard-hardening tests.

Provider-free. No Electron, no external process execution, no real Windows
security API call, no write outside the repository.
"""
from __future__ import annotations

import ast
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


def _canonical_windll(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return False
    if _target_path(node.targets[0]) != name:
        return False
    value = node.value
    if isinstance(value, ast.IfExp):
        if not (
            isinstance(value.orelse, ast.Constant)
            and value.orelse.value is None
        ):
            return False
        value = value.body
    if not isinstance(value, ast.Call):
        return False
    if _call_qualified_name(value) != "ctypes.WinDLL":
        return False
    if not value.args:
        return False
    if len(value.keywords) > 1:
        return False
    if value.keywords and value.keywords[0].arg != "use_last_error":
        return False
    expected = "kernel32" if name == "_kernel32" else "advapi32"
    first = value.args[0]
    return isinstance(first, ast.Constant) and first.value == expected


def _canonical_explicit_access(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.ClassDef)
        and node.name == "EXPLICIT_ACCESS_W"
        and not node.decorator_list
        and len(node.bases) == 1
        and _target_path(node.bases[0]) == "ctypes.Structure"
    )


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


def _module_shape_ok(module: ast.Module) -> bool:
    """Allow only docstrings, imports, simple assignments and definitions."""
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
            if any(
                isinstance(target, (ast.Attribute, ast.Subscript))
                for target in stmt.targets
            ):
                return False
            continue
        if isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, (ast.Attribute, ast.Subscript)):
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


def _security_call_lines(path: Path) -> set[int]:
    """Allow only the exact documented AppContainer operation.

    This is an exact structural whitelist, not a permissive traversal. The
    function must have the documented signature and its body must be exactly
    the eighteen documented statements. Protected names may not be rebound or
    shadowed at module scope, in an enclosing scope, or inside the function.
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
    if not _local_bindings_ok(tree):
        return set()
    if not _attribute_mutations_ok(tree):
        return set()

    security_call = function.body[15].body[0].value
    return {security_call.lineno}


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
