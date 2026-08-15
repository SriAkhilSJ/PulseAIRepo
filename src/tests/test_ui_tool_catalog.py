"""Keep the browser/workbench tool renderer catalog aligned with Pulse runtime tools."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLSETS = ROOT / "src" / "tools" / "toolsets.py"
BROWSER = ROOT / "src" / "tools" / "browser_mcp.py"
CATALOG = ROOT / "ui" / "src" / "runtime" / "toolCatalog.ts"


def _literal_toolset_names() -> set[str]:
    tree = ast.parse(TOOLSETS.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        value = node.value
        if not isinstance(target, ast.Name) or not target.id.endswith("_TOOLS"):
            continue
        if isinstance(value, (ast.Tuple, ast.List)):
            names.update(
                item.value for item in value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return names


def _browser_tool_names() -> set[str]:
    tree = ast.parse(BROWSER.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            func = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(func, ast.Name) and func.id == "tool":
                names.add(node.name)
    return names


def _catalog_names() -> set[str]:
    text = CATALOG.read_text(encoding="utf-8")
    return set(re.findall(r"^\s{2}([a-z][a-z0-9_]*): tool\(", text, re.M))


def test_ui_catalog_covers_every_runtime_tool_name():
    expected = _literal_toolset_names() | _browser_tool_names()
    actual = _catalog_names()
    assert actual == expected, f"missing={sorted(expected-actual)} extra={sorted(actual-expected)}"


def test_terminal_family_has_real_pulse_process_tools():
    text = CATALOG.read_text(encoding="utf-8")
    assert 'run_terminal: tool("Terminal", "terminal"' in text
    assert 'start_terminal: tool("Start process", "process"' in text
    assert 'read_terminal_output: tool("Read process output", "process"' in text
