"""Phase 2A - real workspace discovery before engineering planning.

Provider-free. Covers the three read-only tools, their security boundaries and
boundedness, the contract/planner resolution against discovered files, and one
graph-level proof that the canonical LangGraph engineering path runs discovery
before it plans (and that requirement ids never become filenames).

No API calls: the engineering engine runs its deterministic mock mode and the
post-run memory review is disabled.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.orchestration.contract import (
    extract_contract,
    is_requirement_id_target,
    validate_contract_plan,
)
from src.orchestration.planner import EngineeringTaskPlanner
from src.workspace.discovery import (
    TOOL_LIST_FILES,
    TOOL_READ_FILE,
    TOOL_SEARCH,
    WorkspaceDiscovery,
)
from src.workspace.evidence import build_workspace_evidence

OPS = '''"""Core arithmetic operations for the mini_math package."""


def add(a: float, b: float) -> float:
    """Return the sum of ``a`` and ``b``."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return ``a`` minus ``b``."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of ``a`` and ``b``."""
    return a * b
'''

INIT = '''"""mini_math: a small arithmetic package."""

from .ops import add, multiply, subtract

__all__ = ["add", "subtract", "multiply"]

__version__ = "0.1.0"
'''

TESTS = '''import pytest

from mini_math import add, multiply, subtract


def test_add_positive():
    assert add(2, 3) == 5


def test_multiply_positive():
    assert multiply(6, 7) == 42


def test_multiply_floats():
    assert multiply(1.5, 2.0) == pytest.approx(3.0)
'''

README = """# mini_math

A tiny arithmetic package.

```python
from mini_math import add, subtract, multiply

multiply(6, 7)   # 42
```
"""


def _mini_math(tmp_path: Path) -> Path:
    pkg = tmp_path / "mini_math"
    (pkg / "src" / "mini_math").mkdir(parents=True)
    (pkg / "tests").mkdir()
    (pkg / "src" / "mini_math" / "ops.py").write_text(OPS, encoding="utf-8", newline="\n")
    (pkg / "src" / "mini_math" / "__init__.py").write_text(INIT, encoding="utf-8", newline="\n")
    (pkg / "tests" / "test_ops.py").write_text(TESTS, encoding="utf-8", newline="\n")
    (pkg / "README.md").write_text(README, encoding="utf-8", newline="\n")
    (pkg / "pyproject.toml").write_text(
        "[project]\nname = \"mini-math\"\n", encoding="utf-8", newline="\n"
    )
    # Noise that must never reach the model's context.
    for ignored in ("node_modules", "__pycache__", ".git", ".pytest_cache"):
        target = pkg / ignored
        target.mkdir()
        (target / "hidden.py").write_text("SECRET_NOISE = 1\n", encoding="utf-8")
    return pkg


def _discovery(workspace: Path, **kwargs) -> WorkspaceDiscovery:
    return WorkspaceDiscovery(
        workspace,
        task_id="task-t",
        turn_id="turn-t",
        session_id="session-t",
        **kwargs,
    )


def _req(rid: str, description: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=rid,
        title=rid,
        description=description,
        classification="EXPLICIT",
        status=SimpleNamespace(value="ACCEPTED"),
        affected_files=[],
        acceptance_criteria=["Verified"],
    )


def _spec(requirements):
    return SimpleNamespace(
        all_requirements=lambda: list(requirements),
        requirements=list(requirements),
        desired_outcome="Implement the requested engineering change",
        title="qualification",
    )


DIVIDE_PROMPT = (
    "Implement a divide(a, b) function in the existing mini_math package. "
    "Division by zero must raise ZeroDivisionError. Export the function from the "
    "package, add tests covering positive values, negative values, floating-point "
    "values and division by zero in tests/test_ops.py, update README documentation, "
    "and run the complete test suite. Preserve the existing functions."
)

CLAMP_PROMPT = (
    "Implement clamp(value, minimum, maximum) in the existing mini_math package. "
    "Raise ValueError when minimum exceeds maximum. Export it from the package, "
    "add tests in tests/test_ops.py and update the documentation. Keep the existing "
    "divide implementation intact."
)


# --------------------------------------------------------------------------- #
# Test A - listing
# --------------------------------------------------------------------------- #

def test_list_files_discovers_the_real_project(tmp_path: Path) -> None:
    pkg = _mini_math(tmp_path)
    result = _discovery(pkg).list_files(".")

    assert result.ok is True
    paths = {entry["path"] for entry in result.data["entries"]}
    assert {
        "src/mini_math/ops.py",
        "src/mini_math/__init__.py",
        "tests/test_ops.py",
        "README.md",
        "pyproject.toml",
    } <= paths
    assert not any("node_modules" in path or "__pycache__" in path for path in paths)
    assert not any(path.startswith((".git/", ".pytest_cache/")) for path in paths)
    assert result.data["skipped_ignored"] >= 4
    assert result.data["truncated"] is False

    kinds = {entry["path"]: entry["kind"] for entry in result.data["entries"]}
    assert kinds["src/mini_math/ops.py"] == "source"
    assert kinds["tests/test_ops.py"] == "test"
    assert kinds["README.md"] == "documentation"
    assert kinds["pyproject.toml"] == "configuration"

    # Lifecycle identity is complete and stable for auditing.
    call = result.call
    assert call.tool == TOOL_LIST_FILES
    assert call.status == "ok"
    assert call.call_id.startswith("tc_")
    assert call.event_id and call.journal_event_id
    assert call.session_id == "session-t" and call.turn_id == "turn-t"
    assert call.task_id == "task-t"
    assert call.duration_ms >= 0 and call.result_bytes > 0


# --------------------------------------------------------------------------- #
# Test B - reading
# --------------------------------------------------------------------------- #

def test_read_file_returns_the_actual_implementation(tmp_path: Path) -> None:
    pkg = _mini_math(tmp_path)
    result = _discovery(pkg).read_file("src/mini_math/ops.py")

    assert result.ok is True
    assert result.data["content"] == OPS
    assert result.data["encoding"] == "utf-8"
    assert result.data["truncated"] is False
    assert result.data["total_bytes"] == len(OPS.encode("utf-8"))
    assert result.call.tool == TOOL_READ_FILE

    bounded = _discovery(pkg).read_file("src/mini_math/ops.py", max_lines=2)
    assert bounded.ok is True
    assert bounded.data["truncated"] is True
    assert bounded.data["truncated_reason"] == "max_lines"
    assert bounded.data["lines_returned"] == 2


# --------------------------------------------------------------------------- #
# Test C - search
# --------------------------------------------------------------------------- #

def test_search_returns_the_correct_location(tmp_path: Path) -> None:
    pkg = _mini_math(tmp_path)
    result = _discovery(pkg).search("def multiply")

    assert result.ok is True
    assert result.data["count"] >= 1
    match = result.data["matches"][0]
    assert match["path"] == "src/mini_math/ops.py"
    expected_line = OPS.splitlines().index("def multiply(a: float, b: float) -> float:") + 1
    assert match["line"] == expected_line
    assert match["column"] == 1
    assert "multiply" in match["excerpt"]
    assert result.call.tool == TOOL_SEARCH


# --------------------------------------------------------------------------- #
# Test D/E - planning against discovered files
# --------------------------------------------------------------------------- #

def _plan_for(pkg: Path, prompt: str, requirements, requested):
    discovery = _discovery(pkg)
    evidence = build_workspace_evidence(discovery, prompt)
    contract = extract_contract(
        prompt,
        requirements,
        requested,
        task_id="task-t",
        workspace=pkg,
        workspace_evidence=evidence,
    )
    plan = EngineeringTaskPlanner(str(pkg)).build_plan(
        task_id="task-t",
        specification=_spec(requirements),
        contract=contract,
        task_prompt=prompt,
        requested_files=list(requested),
        max_nodes=6,
        workspace_evidence=evidence,
    )
    return evidence, contract, plan


def test_planner_targets_the_real_implementation_and_tests(tmp_path: Path) -> None:
    pkg = _mini_math(tmp_path)
    requirements = [
        _req("REQ-001", "Implement a divide(a, b) function in the mini_math package."),
        _req("REQ-002", "Division by zero must raise ZeroDivisionError."),
        _req("REQ-003", "Export divide from the package."),
        _req("REQ-004", "Add tests for divide in tests/test_ops.py."),
        _req("REQ-005", "Update README documentation for divide."),
    ]
    evidence, contract, plan = _plan_for(pkg, DIVIDE_PROMPT, requirements, ["tests/test_ops.py"])

    targets = {target for node in plan.nodes.values() for target in node.target_files}
    assert "src/mini_math/ops.py" in targets
    assert "tests/test_ops.py" in targets
    assert "src/mini_math/__init__.py" in targets
    assert "README.md" in targets
    assert not [target for target in targets if is_requirement_id_target(target)]
    assert contract.ambiguities == []

    # Discovery evidence reaches the plan node (and thus the generator prompt).
    nodes = [node for node in plan.nodes.values() if node.node_id != "task_verification"]
    assert nodes and all((node.contract or {}).get("workspace_evidence") for node in nodes)
    ops = next(node for node in nodes if node.target_files == ["src/mini_math/ops.py"])
    related = {item["path"] for item in ops.contract["workspace_evidence"]["related"]}
    assert "src/mini_math/__init__.py" in related

    report = validate_contract_plan(
        contract,
        plan,
        max_dispatches=6,
        requested_files=["tests/test_ops.py"],
        workspace_evidence=evidence,
    )
    assert report["ok"] is True


def test_planner_never_invents_requirement_id_files_for_clamp(tmp_path: Path) -> None:
    pkg = _mini_math(tmp_path)
    requirements = [
        _req("REQ-001", "Implement clamp(value, minimum, maximum) in mini_math."),
        _req("REQ-002", "Raise ValueError when minimum exceeds maximum."),
        _req("REQ-003", "Export clamp from the package."),
        _req("REQ-004", "Add clamp tests in tests/test_ops.py."),
        _req("REQ-005", "Document clamp in the README."),
    ]
    evidence, contract, plan = _plan_for(pkg, CLAMP_PROMPT, requirements, ["tests/test_ops.py"])

    targets = {target for node in plan.nodes.values() for target in node.target_files}
    assert not [target for target in targets if is_requirement_id_target(target)]
    assert not [target for target in targets if target.endswith("_module.py")]
    assert "src/mini_math/ops.py" in targets
    assert "tests/test_ops.py" in targets
    assert contract.ambiguities == []
    assert "clamp" in evidence.queries


def test_ambiguous_discovery_blocks_instead_of_fabricating(tmp_path: Path) -> None:
    root = tmp_path / "ambiguous"
    (root / "src" / "a").mkdir(parents=True)
    (root / "src" / "b").mkdir(parents=True)
    (root / "src" / "a" / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    (root / "src" / "b" / "two.py").write_text("def two():\n    return 2\n", encoding="utf-8")

    requirements = [_req("REQ-001", "Implement the feature.")]
    discovery = _discovery(root)
    evidence = build_workspace_evidence(discovery, "Implement the feature.")
    contract = extract_contract(
        "Implement the feature.",
        requirements,
        [],
        task_id="task-t",
        workspace=root,
        workspace_evidence=evidence,
    )

    targets = {
        path for paths in contract.requirement_map.values() for path in paths
    }
    assert not targets, "ambiguous discovery must not invent a target"
    assert any("ambiguous target" in item for item in contract.ambiguities)


# --------------------------------------------------------------------------- #
# Test F - traversal and content protections
# --------------------------------------------------------------------------- #

def test_workspace_traversal_protections(tmp_path: Path) -> None:
    pkg = _mini_math(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("API_KEY = 'nope'\n", encoding="utf-8")
    discovery = _discovery(pkg)

    traversal = discovery.list_files("../outside")
    assert traversal.ok is False
    assert traversal.error_code == "path_rejected"

    absolute = discovery.read_file(str(outside / "secret.py"))
    assert absolute.ok is False
    # Phase 2D: an absolute external path is not a hard "traversal" error; it
    # is blocked until a human grants that exact boundary.
    assert absolute.error_code in {"access_required", "path_rejected"}
    assert absolute.data.get("content") is None

    dotdot = discovery.read_file("src/../../outside/secret.py")
    assert dotdot.ok is False
    assert dotdot.error_code == "path_rejected"

    drive_relative = discovery.read_file("C:secret.py")
    assert drive_relative.ok is False
    assert drive_relative.error_code == "path_rejected"

    nul = discovery.read_file("src/mini_math/ops.py\x00.txt")
    assert nul.ok is False

    # Symlink escape: the link lives inside the workspace, the target does not.
    link = pkg / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - host privilege
        link = None
    if link is not None:
        escaped = discovery.read_file("linked/secret.py")
        assert escaped.ok is False
        assert escaped.error_code == "path_rejected"
        listed = discovery.list_files(".")
        assert "linked/secret.py" not in {item["path"] for item in listed.data["entries"]}

    # Oversized file is refused, not truncated into context.
    huge = pkg / "big.txt"
    huge.write_bytes(b"x" * 4_100_000)
    oversized = discovery.read_file("big.txt")
    assert oversized.ok is False
    assert oversized.error_code == "file_too_large"

    # Binary content is refused.
    binary = pkg / "image.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    refused = discovery.read_file("image.png")
    assert refused.ok is False
    assert refused.error_code == "binary_file"

    # Invalid UTF-8 is reported, never fatal.
    broken = pkg / "latin1.txt"
    broken.write_bytes(b"caf\xe9\n")
    decoded = discovery.read_file("latin1.txt")
    assert decoded.ok is True
    assert decoded.data["encoding"] == "utf-8-replaced"
    assert "caf" in decoded.data["content"]

    # Search bounds results and reports truncation.
    noisy = pkg / "noisy.py"
    noisy.write_text("\n".join(f"value = {index}  # needle" for index in range(100)), encoding="utf-8")
    bounded = discovery.search("needle", max_results=5)
    assert bounded.ok is True
    assert bounded.data["count"] == 5
    assert bounded.data["truncated"] is True
    assert bounded.data["truncated_reason"] == "max_results"


# --------------------------------------------------------------------------- #
# Test G - cancellation and bounds
# --------------------------------------------------------------------------- #

def test_cancellation_and_bounded_results(tmp_path: Path) -> None:
    pkg = _mini_math(tmp_path)

    cancelled = _discovery(pkg, cancellation_checker=lambda: True).list_files(".")
    assert cancelled.ok is False
    assert cancelled.call.status == "cancelled"
    assert cancelled.data.get("truncated_reason") == "cancelled"

    bounded = _discovery(pkg).list_files(".", max_entries=3)
    assert bounded.ok is True
    assert bounded.data["count"] == 3
    assert bounded.data["truncated"] is True
    assert bounded.data["truncated_reason"] == "max_entries"

    deep = _mini_math(tmp_path / "depth")
    nested = deep / "a" / "b" / "c" / "d"
    nested.mkdir(parents=True)
    (nested / "deep.py").write_text("DEEP = 1\n", encoding="utf-8")
    shallow = _discovery(deep).list_files(".", max_depth=1)
    assert "a/b/c/d/deep.py" not in {item["path"] for item in shallow.data["entries"]}

    unknown = _discovery(pkg).call("workspace.delete_everything")
    assert unknown.ok is False
    assert unknown.error_code == "unknown_tool"


# --------------------------------------------------------------------------- #
# Test H - the canonical graph path discovers before planning
# --------------------------------------------------------------------------- #

def test_graph_engineering_path_discovers_before_planning(monkeypatch, tmp_path: Path) -> None:
    from src.graphs.chat_graph import graph, stream_agent

    pkg = _mini_math(tmp_path / "ws")
    appdata = tmp_path / "appdata"
    monkeypatch.setenv("CRUSORAI_ORCHESTRATOR_MOCK", "1")
    monkeypatch.setenv("MEMORY_NUDGE_INTERVAL", "0")
    monkeypatch.setenv("CRUSORAI_APP_DATA_ROOT", str(appdata))

    thread = "phase2a-discovery"
    turn_id = "phase2a-turn"
    result = stream_agent(
        CLAMP_PROMPT,
        thread_id=thread,
        workspace=str(pkg),
        execution_mode="agent",
        approval_channel=True,
        approval_policy="workspace_session",
        turn_id=turn_id,
        canonical_runtime=True,
    )
    assert result.completed is not None

    journal_path = appdata / "orchestration" / f"turn_{turn_id}" / "orchestration_journal.jsonl"
    assert journal_path.exists(), "the engineering turn must write its journal"
    events = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    types = [event["event_type"] for event in events]

    assert "WORKSPACE_DISCOVERED" in types
    tool_events = [event for event in events if event["event_type"] == "WORKSPACE_TOOL_CALL"]
    assert {event["details"]["tool"] for event in tool_events} >= {
        TOOL_LIST_FILES,
        TOOL_READ_FILE,
        TOOL_SEARCH,
    }
    for event in tool_events:
        details = event["details"]
        assert details["tool_call_id"].startswith("tc_")
        assert details["event_id"] and details["journal_event_id"]
        assert details["session_id"] == thread
        assert details["turn_id"] == turn_id
        assert details["status"] in {"ok", "error", "cancelled"}
        assert "duration_ms" in details and "result_bytes" in details
        assert "truncated" in details

    # Discovery strictly precedes planning.
    assert types.index("WORKSPACE_TOOL_CALL") < types.index("CONTRACT_EXTRACTED")
    assert types.index("WORKSPACE_DISCOVERED") < types.index("PLAN_GENERATED")

    contract_event = next(event for event in events if event["event_type"] == "CONTRACT_EXTRACTED")
    components = contract_event["details"]["components"]
    targets = {component["target"] for component in components}
    assert "src/mini_math/ops.py" in targets
    assert not [target for target in targets if re.search(r"req[_-]?\d", target, re.IGNORECASE)]

    discovered = next(event for event in events if event["event_type"] == "WORKSPACE_DISCOVERED")
    assert discovered["details"]["files_listed"] >= 4
    assert "src/mini_math/ops.py" in {
        item["path"] for item in discovered["details"]["selected"]
    }

    state_values = (graph.get_state({"configurable": {"thread_id": thread}}).values or {})
    delivery = state_values.get("engineering_delivery") or {}
    assert delivery.get("workspace_discovery", {}).get("files_listed", 0) >= 4
    assert delivery["workspace_discovery"]["tool_calls"]
