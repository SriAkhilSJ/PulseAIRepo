"""General IDE deliverable evidence contracts (non-code artifacts)."""
from langchain_core.messages import AIMessage

from src.graphs.gates import (
    _deliverable_targets,
    _deliverables_missing_on_disk,
    finish_gate_node,
    should_continue,
)


def state_for(task: str, workspace) -> dict:
    return {
        "messages": [AIMessage(content="Done")],
        "current_task": task,
        "workspace": str(workspace),
        "steps_completed": [],
        "failed_steps": [],
        "finish_nudges": 0,
        "verify_nudges": 0,
        "iteration_used": 0,
    }


def test_general_artifact_extensions_are_detected():
    task = "Create report.pdf, analysis.xlsx, slides.pptx and chart.png"
    assert _deliverable_targets(task) == [
        "report.pdf", "analysis.xlsx", "slides.pptx", "chart.png"
    ]


def test_missing_bare_pdf_is_a_real_deliverable(tmp_path):
    state = state_for("Create the final research report as report.pdf", tmp_path)
    assert _deliverables_missing_on_disk(state, str(tmp_path)) == ["report.pdf"]
    assert should_continue(state) == "finish_gate"


def test_missing_general_artifact_gets_format_neutral_nudge(tmp_path):
    state = state_for("Create the final research report as report.pdf", tmp_path)
    result = finish_gate_node(state)
    text = result["messages"][0].content
    assert "general IDE agent" in text
    assert "typecheck_workspace" not in text
    assert "copy/compose" not in text


def test_existing_artifact_is_delivery_evidence_even_if_created_by_script(tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4\nnot-empty")
    state = state_for("Create the final research report as report.pdf", tmp_path)
    assert _deliverables_missing_on_disk(state, str(tmp_path)) == []
    assert should_continue(state) == "finalize"


def test_nextjs_prose_is_not_mistaken_for_bare_output(tmp_path):
    state = state_for("Build a chat app with Next.js", tmp_path)
    assert _deliverables_missing_on_disk(state, str(tmp_path)) == []
