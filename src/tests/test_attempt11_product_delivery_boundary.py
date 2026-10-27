"""Provider-free regressions for Attempt 11's product-delivery boundary."""
from pathlib import Path
import sys

from langchain_core.messages import AIMessage, ToolMessage

from src.context.compaction import compact_file_mutation_arguments
from src.context.workspace_integrity import audit_workspace
from src.graphs import budget
from src.graphs.gates import (
    _unresolved_failed_verification_checks,
    _verification_receipt_status,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ATTEMPT11_WORKSPACE = REPO_ROOT / "bench-results" / "test5-11-desktop" / "workspace"
ATTEMPT12_WORKSPACE = REPO_ROOT / "bench-results" / "test5-12-desktop" / "workspace"


def test_attempt12_fixture_reports_missing_html_script_dependency():
    findings = {(issue.kind, issue.path, issue.reference) for issue in audit_workspace(ATTEMPT12_WORKSPACE)}
    assert ("missing-html-reference", "index.html", "./src/main.js") in findings


def test_html_integrity_handles_local_root_query_srcset_and_external_refs(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "ok.css").write_text("body {}", encoding="utf-8")
    (tmp_path / "ok.png").write_bytes(b"png")
    (tmp_path / "index.html").write_text(
        '<link rel="stylesheet" href="/assets/ok.css?v=1">'
        '<script src="src/missing.js#boot"></script>'
        '<img src="https://example.com/remote.png" '
        'srcset="ok.png 1x, missing@2x.png 2x">',
        encoding="utf-8",
    )
    findings = {(issue.kind, issue.reference) for issue in audit_workspace(tmp_path)}
    assert findings == {
        ("missing-html-reference", "src/missing.js#boot"),
        ("missing-html-reference", "missing@2x.png"),
    }


def test_attempt11_fixture_reports_missing_vendor_and_shader_constant(monkeypatch):
    # R2 regression: launching a checked-in runner as ``python scripts/x.py``
    # puts scripts/, not the repository root, at sys.path[0].
    from scripts.validate_attempt11_product_delivery_windows import ensure_repo_import_path
    root_text = str(REPO_ROOT)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != root_text])
    ensure_repo_import_path(REPO_ROOT)
    assert sys.path[0] == root_text

    findings = {(issue.kind, issue.path, issue.reference) for issue in audit_workspace(ATTEMPT11_WORKSPACE)}
    assert ("missing-local-import", "js/main.js", "../vendor/three/three.module.min.js") in findings
    assert ("missing-local-import", "js/main.js", "../vendor/three/controls/OrbitControls.js") in findings
    assert ("undefined-shader-constant", "js/shaders.js", "MAX_STEPS_LOOP") in findings


def test_integrity_audit_distinguishes_declared_builtin_and_missing_refs(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"name":"demo","dependencies":{"react":"latest"}}', encoding="utf-8"
    )
    (tmp_path / "ok.js").write_text("export default 1", encoding="utf-8")
    (tmp_path / "main.js").write_text(
        "import React from 'react';\n"
        "import fs from 'node:fs';\n"
        "import './ok.js';\n"
        "import './missing.js';\n"
        "import map from 'lodash/map';\n",
        encoding="utf-8",
    )
    findings = {(issue.kind, issue.reference) for issue in audit_workspace(tmp_path)}
    assert findings == {
        ("missing-local-import", "./missing.js"),
        ("undeclared-package", "lodash"),
    }


def test_passing_ui_receipt_cannot_hide_attempt11_unresolved_dependencies():
    state = {
        "workspace": str(ATTEMPT11_WORKSPACE),
        "current_task": "Build a browser website and provide a screenshot",
        "steps_completed": ["Wrote file: js/main.js", "Wrote file: js/shaders.js"],
        "messages": [
            AIMessage(content="", tool_calls=[{
                "id": "verify-1", "name": "verify_ui_workspace", "args": {}
            }]),
            ToolMessage(
                content="✅ UI VERIFICATION PASSED (synthetic regression receipt)",
                name="verify_ui_workspace",
                tool_call_id="verify-1",
            ),
        ],
    }
    receipt = _verification_receipt_status(state)
    assert receipt["static"] is True
    assert receipt["navigate"] is True
    assert receipt["integrity"] is False
    assert "integrity" in receipt["missing"]
    assert receipt["passed"] is False

    # Reproduce the old premature-finalization boundary: even a final response
    # after a nominal UI receipt must remain non-complete while these source
    # holes exist.
    from src.graphs.chat_graph import finalize_node
    state["plan"] = []
    state["failed_steps"] = []
    update = finalize_node(state, {"configurable": {}})
    # Hermes parity: finalize is silent on unverified — structured verdict only
    assert update["task_completed"] is False
    assert update["task_status"] == "unverified"
    assert update["messages"] == []


def test_landed_write_payloads_are_compacted_without_mutating_history():
    body1 = "export const first = 1;\n" * 500
    body2 = "export const second = 2;\n" * 500
    first = AIMessage(content="", tool_calls=[{
        "id": "write-1", "name": "write_file", "args": {"path": "src/a.ts", "content": body1}
    }])
    second = AIMessage(content="", tool_calls=[{
        "id": "write-2", "name": "write_file", "args": {"path": "src/b.ts", "content": body2}
    }])
    history = [
        first,
        ToolMessage(content="Wrote file: src/a.ts", name="write_file", tool_call_id="write-1"),
        second,
        ToolMessage(content="Wrote file: src/b.ts", name="write_file", tool_call_id="write-2"),
    ]

    compacted = compact_file_mutation_arguments(history)

    assert compacted[0].tool_calls[0]["args"]["path"] == "src/a.ts"
    assert "Persisted file payload omitted" in compacted[0].tool_calls[0]["args"]["content"]
    assert compacted[2].tool_calls[0]["args"]["content"] == body2, "newest repair context stays verbatim"
    assert first.tool_calls[0]["args"]["content"] == body1, "checkpoint history is immutable"
    assert [m.tool_call_id for m in compacted if isinstance(m, ToolMessage)] == ["write-1", "write-2"]


def test_mutation_payload_compaction_has_independent_kill_switch(monkeypatch):
    body = "recoverable source" * 100
    call = AIMessage(content="", tool_calls=[{
        "id": "write-old", "name": "write_file", "args": {"path": "x.ts", "content": body}
    }])
    history = [
        call,
        ToolMessage(content="Wrote file: x.ts", name="write_file", tool_call_id="write-old"),
        AIMessage(content="", tool_calls=[{
            "id": "write-new", "name": "write_file", "args": {"path": "y.ts", "content": body}
        }]),
        ToolMessage(content="Wrote file: y.ts", name="write_file", tool_call_id="write-new"),
    ]
    monkeypatch.setenv("CRUSORAI_MUTATION_PAYLOAD_COMPACTION", "off")
    assert compact_file_mutation_arguments(history) is history
    assert call.tool_calls[0]["args"]["content"] == body


def test_failed_write_payload_is_never_compacted():
    body = "important recovery content" * 100
    call = AIMessage(content="", tool_calls=[{
        "id": "bad-write", "name": "write_file", "args": {"path": "x.ts", "content": body}
    }])
    history = [
        call,
        ToolMessage(content="Error: disk full", name="write_file", tool_call_id="bad-write"),
    ]
    assert compact_file_mutation_arguments(history)[0].tool_calls[0]["args"]["content"] == body


def test_verification_reserve_precedes_token_and_iteration_exhaustion(monkeypatch):
    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "120000")
    monkeypatch.setenv("AGENT_VERIFICATION_TOKEN_RESERVE", "30000")
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "12")
    monkeypatch.setenv("AGENT_VERIFICATION_ITERATION_RESERVE", "4")

    assert budget._verification_reserve_reached({
        "iteration_used": 7,
        "turn_token_usage": {"total_tokens": 89999},
    }) is False
    assert budget._verification_reserve_reached({
        "iteration_used": 8,
        "turn_token_usage": {"total_tokens": 89999},
    }) is True
    assert budget._budget_exhausted({
        "iteration_used": 8,
        "turn_token_usage": {"total_tokens": 89999},
    }) is False
    assert budget._verification_reserve_reached({
        "iteration_used": 7,
        "turn_token_usage": {"total_tokens": 90000},
    }) is True


def test_reserve_phase_narrows_to_dependency_repair_and_verification(monkeypatch, tmp_path):
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "120000")
    monkeypatch.setenv("AGENT_VERIFICATION_TOKEN_RESERVE", "30000")
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "30")
    monkeypatch.setenv("AGENT_VERIFICATION_ITERATION_RESERVE", "6")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const x = 1", encoding="utf-8")
    state = {
        "workspace": str(tmp_path),
        "current_task": "Build and verify a browser app",
        "steps_completed": ["Wrote file: src/app.ts"],
        "iteration_used": 10,
        "turn_token_usage": {"total_tokens": 90000},
        "messages": [
            AIMessage(content="", tool_calls=[{
                "id": "landed", "name": "write_file",
                "args": {"path": "src/app.ts", "content": "export const x = 1"},
            }]),
            ToolMessage(
                content="Wrote file: src/app.ts", name="write_file",
                tool_call_id="landed",
            ),
        ],
        "execution_trace": [{"tool": "write_file", "status": "success"}],
        "plan": [],
    }
    config = {"configurable": {"workspace": str(tmp_path)}}

    names = {tool.name for tool in chat_graph._resolve_bound_tools(state, config)}

    assert config["configurable"]["execution_phase"] == "verification_first_check"
    assert {"run_terminal", "typecheck_workspace"} <= names
    assert "read_file" not in names
    assert "edit_file" not in names
    assert "web_search" not in names
    assert "scaffold_nextjs" not in names
    assert "VERIFICATION FIRST-CHECK PHASE" in config["configurable"]["phase_guidance"]

    # A concrete failed check creates durable verification debt. The next
    # decision must inspect/mutate; rerunning checks unchanged is unavailable.
    failure_text = "❌ typecheck_workspace: src/app.ts(1,1) error TS1000"
    state["messages"].extend([
        AIMessage(content="", tool_calls=[{
            "id": "check", "name": "typecheck_workspace", "args": {},
        }]),
        ToolMessage(
            content=failure_text,
            name="typecheck_workspace", tool_call_id="check", status="error",
        ),
    ])
    state["execution_trace"].append({
        "tool": "typecheck_workspace", "args": {},
        "status": "failed", "result": failure_text,
    })
    repair_config = {"configurable": {"workspace": str(tmp_path)}}
    repair_names = {
        tool.name for tool in chat_graph._resolve_bound_tools(state, repair_config)
    }
    assert repair_config["configurable"]["execution_phase"] == "verification_repair_required"
    assert {"read_file", "edit_file", "write_file"} <= repair_names
    assert "run_terminal" not in repair_names
    assert "typecheck_workspace" not in repair_names
    assert "list_files" not in repair_names
    assert "FAILED VERIFICATION REPAIR PHASE" in repair_config["configurable"]["phase_guidance"]

    # One landed repair flips the structural phase to an exact recheck. Source
    # mutation is no longer offered until the failed check is rerun.
    state["messages"].extend([
        AIMessage(content="", tool_calls=[{
            "id": "repair", "name": "edit_file",
            "args": {"path": "src/app.ts", "old_text": "1", "new_text": "2"},
        }]),
        ToolMessage(
            content="Edited file: src/app.ts", name="edit_file",
            tool_call_id="repair",
        ),
    ])
    state["execution_trace"].append({
        "tool": "edit_file", "args": {"path": "src/app.ts"},
        "status": "success", "result": "Edited file: src/app.ts",
    })
    recheck_config = {"configurable": {"workspace": str(tmp_path)}}
    recheck_names = {
        tool.name for tool in chat_graph._resolve_bound_tools(state, recheck_config)
    }
    assert recheck_config["configurable"]["execution_phase"] == "verification_recheck_required"
    assert {"run_terminal", "typecheck_workspace"} <= recheck_names
    assert "edit_file" not in recheck_names
    assert "read_file" not in recheck_names
    assert "EXACT VERIFICATION RECHECK PHASE" in recheck_config["configurable"]["phase_guidance"]


def test_different_passing_check_cannot_erase_failed_check_debt(tmp_path):
    failed_command = "python -m unittest discover -s tests -p 'test_*.py' -v"
    weaker_command = "python -m unittest tests.test_health -v"
    (tmp_path / "server.py").write_text("print('service')\n", encoding="utf-8")
    state = {
        "workspace": str(tmp_path),
        "current_task": "Build and test a Python service",
        "steps_completed": ["Wrote file: server.py", "Edited file: server.py"],
        "messages": [
            AIMessage(content="", tool_calls=[{
                "id": "full-fail", "name": "terminal",
                "args": {"command": failed_command},
            }]),
            ToolMessage(
                content="sqlite3.OperationalError: no such table: records\nExit code: 1",
                name="terminal", tool_call_id="full-fail", status="error",
            ),
            AIMessage(content="", tool_calls=[{
                "id": "fix", "name": "edit_file",
                "args": {"path": "server.py", "old_text": "service", "new_text": "fixed"},
            }]),
            ToolMessage(
                content="Edited file: server.py", name="edit_file",
                tool_call_id="fix",
            ),
            AIMessage(content="", tool_calls=[{
                "id": "weak-pass", "name": "terminal",
                "args": {"command": weaker_command},
            }]),
            ToolMessage(
                content="Ran 1 test\nOK\nExit code: 0",
                name="terminal", tool_call_id="weak-pass",
            ),
        ],
        "execution_trace": [
            {
                "tool": "terminal", "args": {"command": failed_command},
                "status": "failed",
                "result": "sqlite3.OperationalError: no such table: records\nExit code: 1",
            },
            {
                "tool": "edit_file", "args": {"path": "server.py"},
                "status": "success", "result": "Edited file: server.py",
            },
            {
                "tool": "terminal", "args": {"command": weaker_command},
                "status": "success", "result": "Ran 1 test\nOK\nExit code: 0",
            },
        ],
    }

    debt = _unresolved_failed_verification_checks(state)

    assert len(debt) == 1
    assert debt[0]["tool"] == "terminal"
    assert debt[0]["repair_landed"] is True
    receipt = _verification_receipt_status(state)
    assert receipt["static"] is True, "the weaker check did run cleanly"
    assert receipt["failed_checks"] is False
    assert "failed_checks" in receipt["missing"]
    assert receipt["passed"] is False

    state["messages"].extend([
        AIMessage(content="", tool_calls=[{
            "id": "full-pass", "name": "terminal",
            "args": {"command": failed_command},
        }]),
        ToolMessage(
            content="Ran 5 tests\nOK\nExit code: 0",
            name="terminal", tool_call_id="full-pass",
        ),
    ])
    state["execution_trace"].append({
        "tool": "terminal", "args": {"command": failed_command},
        "status": "success", "result": "Ran 5 tests\nOK\nExit code: 0",
    })
    assert _unresolved_failed_verification_checks(state) == []
    assert _verification_receipt_status(state)["passed"] is True


def test_environment_failure_does_not_create_source_repair_debt():
    state = {
        "execution_trace": [{
            "tool": "terminal",
            "args": {"command": "python -m unittest discover"},
            "status": "failed",
            "result": "python: command not found\nExit code: 127",
        }],
    }
    assert _unresolved_failed_verification_checks(state) == []


def test_autonomous_missing_root_deliverable_precedes_verification(tmp_path, monkeypatch):
    """A named file ledger is an obligation, not optional prompt prose."""
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "12")
    monkeypatch.setenv("AGENT_VERIFICATION_ITERATION_RESERVE", "4")
    task = """Build a complete web application.

    Deliver exactly these files at the workspace root:
    - server.py
    - index.html
    """
    (tmp_path / "server.py").write_text("print('ready')\n", encoding="utf-8")
    state = {
        "workspace": str(tmp_path),
        "current_task": task,
        "latest_instruction": task,
        "steps_completed": ["Wrote file: server.py"],
        "iteration_used": 8,
        "turn_token_usage": {"total_tokens": 1000},
        "messages": [
            AIMessage(content="", tool_calls=[{
                "id": "landed", "name": "write_file",
                "args": {"path": "server.py", "content": "print('ready')\n"},
            }]),
            ToolMessage(
                content="Wrote file: server.py", name="write_file",
                tool_call_id="landed",
            ),
        ],
        "execution_trace": [{"tool": "write_file", "status": "success"}],
        "plan": [],
    }
    config = {"configurable": {
        "workspace": str(tmp_path),
        "approval_policy": "workspace_session",
    }}

    names = {tool.name for tool in chat_graph._resolve_bound_tools(state, config)}

    assert config["configurable"]["execution_phase"] == "missing_delivery"
    assert {"write_file", "read_file"} <= names
    assert "terminal" not in names and "run_terminal" not in names
    assert "index.html" in config["configurable"]["phase_guidance"]
    guidance = config["configurable"]["phase_guidance"].lower()
    assert "batch" in guidance and "same response" in guidance

    (tmp_path / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    complete_config = {"configurable": {
        "workspace": str(tmp_path),
        "approval_policy": "workspace_session",
    }}
    complete_names = {
        tool.name for tool in chat_graph._resolve_bound_tools(state, complete_config)
    }
    assert complete_config["configurable"]["execution_phase"] == "verification_first_check"
    assert "terminal" in complete_names or "run_terminal" in complete_names


def test_missing_named_app_directory_keeps_terminal_generator_available(tmp_path):
    """File reconciliation must not deadlock project-directory generators."""
    import src.graphs.chat_graph as chat_graph

    (tmp_path / "README.md").write_text("workspace input\n", encoding="utf-8")
    task = "Create a Flutter app called flutterdemo"
    state = {
        "workspace": str(tmp_path),
        "current_task": task,
        "latest_instruction": task,
        "steps_completed": [],
        "iteration_used": 0,
        "turn_token_usage": {"total_tokens": 0},
        "messages": [],
        "execution_trace": [],
        "plan": [],
    }
    config = {"configurable": {
        "workspace": str(tmp_path),
        "approval_policy": "workspace_session",
    }}

    names = {tool.name for tool in chat_graph._resolve_bound_tools(state, config)}

    assert config["configurable"]["execution_phase"] == "general"
    assert "terminal" in names or "run_terminal" in names
