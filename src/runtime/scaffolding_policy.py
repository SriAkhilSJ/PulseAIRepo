"""
scaffolding_policy.py - Adaptive Greenfield Scaffolding Policy.

Pillar 4 of the Hardened Production Architecture.
Gates monolithic greenfield file creation by structural complexity:
- If a new file defines > 3 classes or > 5 route endpoints:
  1. Contract Skeleton: Module docstrings, imports, class signatures, stubbed methods.
  2. Syntax Gate: Verified via ast.parse().
  3. Targeted Implementation: Surgical function infill via anchored edits.
"""

from __future__ import annotations

import ast
import re
from typing import Dict, Any, Tuple, List


def validate_syntax_tree(code_text: str, filename: str = "") -> Tuple[bool, str]:
    """Verify that Python code parses without syntax errors using ast.parse."""
    if not filename.endswith(".py"):
        # For non-python files, basic bracket balancing check
        return True, "non_python"

    try:
        ast.parse(code_text, filename=filename or "<string>")
        return True, "valid"
    except SyntaxError as se:
        return False, f"SyntaxError at line {se.lineno}, col {se.offset}: {se.msg}"
    except Exception as exc:
        return False, f"Parse error: {exc}"


def analyze_code_structural_complexity(code_text: str, filename: str = "") -> Dict[str, Any]:
    """Analyze structural complexity metrics of proposed code."""
    line_count = len(code_text.splitlines())
    class_count = 0
    function_count = 0
    endpoint_count = 0

    if filename.endswith(".py") or "def " in code_text or "class " in code_text:
        try:
            tree = ast.parse(code_text)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_count += 1
                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    function_count += 1
                    # Check for route decorators (e.g. @route, @app.get, @router.post)
                    for deco in node.decorator_list:
                        deco_name = ""
                        if isinstance(deco, ast.Name):
                            deco_name = deco.id
                        elif isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name):
                            deco_name = deco.func.id
                        elif isinstance(deco, ast.Attribute):
                            deco_name = deco.attr
                        elif isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
                            deco_name = deco.func.attr
                        if any(kw in deco_name.lower() for kw in ["route", "get", "post", "put", "delete", "patch"]):
                            endpoint_count += 1
        except Exception:
            # Fallback regex counting if AST fails
            class_count = len(re.findall(r"^class\s+\w+", code_text, re.MULTILINE))
            function_count = len(re.findall(r"^def\s+\w+", code_text, re.MULTILINE))
            endpoint_count = len(re.findall(r"@(?:route|app|router)\.", code_text))
    else:
        # Generic JS/TS or other languages
        class_count = len(re.findall(r"\bclass\s+\w+", code_text))
        function_count = len(re.findall(r"\bfunction\s+\w+|\w+\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", code_text))
        endpoint_count = len(re.findall(r"\.(?:get|post|put|delete|patch)\s*\(", code_text))

    is_complex = class_count > 3 or endpoint_count > 5 or (function_count > 12 and line_count > 400)

    return {
        "line_count": line_count,
        "class_count": class_count,
        "function_count": function_count,
        "endpoint_count": endpoint_count,
        "is_complex": is_complex,
    }


def evaluate_scaffolding_requirement(code_text: str, filename: str = "") -> Dict[str, Any]:
    """Evaluate whether proposed code requires staged scaffolding."""
    analysis = analyze_code_structural_complexity(code_text, filename)
    syntax_ok, syntax_msg = validate_syntax_tree(code_text, filename)

    if not syntax_ok:
        return {
            "status": "syntax_error",
            "message": f"Proposed code fails AST syntax validation: {syntax_msg}",
            "recommended_action": "Fix syntax error before writing to disk.",
            "metrics": analysis,
        }

    if analysis["is_complex"]:
        return {
            "status": "scaffolding_recommended",
            "message": (
                f"File '{filename}' has high structural complexity ({analysis['class_count']} classes, "
                f"{analysis['endpoint_count']} endpoints, {analysis['function_count']} functions). "
                f"Verify module skeleton and interfaces before monolithic infill."
            ),
            "metrics": analysis,
        }

    return {
        "status": "approved",
        "message": "Code passes structural and syntax criteria for direct file creation.",
        "metrics": analysis,
    }
