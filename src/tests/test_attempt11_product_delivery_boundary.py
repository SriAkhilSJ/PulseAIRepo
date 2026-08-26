"""Provider-free regressions for Attempt 11's product-delivery boundary."""
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

from src.context.compaction import compact_file_mutation_arguments
from src.context.workspace_integrity import audit_workspace
from src.graphs import budget
from src.graphs.gates import _verification_receipt_status


REPO_ROOT = Path(__file__).resolve().parents[2]
ATTEMPT11_WORKSPACE = REPO_ROOT / "bench-results" / "test5-11-desktop" / "workspace"


def test_attempt11_fixture_reports_missing_vendor_and_shader_constant():
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
    assert update["task_completed"] is False
    assert update["task_status"] == "unverified"
    assert "Ended unverified" in update["messages"][0].content


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
    monkeypatch.setenv("PULSEAI_MUTATION_PAYLOAD_COMPACTION", "off")
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

    assert config["configurable"]["execution_phase"] == "verification_reserve"
    assert {"read_file", "edit_file", "run_terminal", "typecheck_workspace"} <= names
    assert "web_search" not in names
    assert "scaffold_nextjs" not in names
    assert "VERIFICATION RESERVE PHASE" in config["configurable"]["phase_guidance"]
