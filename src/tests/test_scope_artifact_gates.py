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


def test_bullet_listed_root_code_files_are_explicit_deliverables(tmp_path):
    task = """Build a web service with Next.js documentation references.

    Deliver exactly these files at the workspace root:
    - server.py
    - index.html
    - styles.css
    - app.js
    - README.md
    """
    state = state_for(task, tmp_path)

    assert _deliverables_missing_on_disk(state, str(tmp_path)) == [
        "server.py", "index.html", "styles.css", "app.js", "README.md",
    ]

    for name in ("server.py", "index.html", "styles.css", "app.js"):
        (tmp_path / name).write_text("content", encoding="utf-8")

    assert _deliverables_missing_on_disk(state, str(tmp_path)) == ["README.md"]


def test_deliverable_evidence_is_workspace_bound_not_cwd_bound(tmp_path, monkeypatch):
    """A same-named file in the engine's CWD is not delivery evidence.

    Regression pin (2026-10-30): ``_deliverable_candidates`` also probed a
    bare CWD-relative ``Path(target)``, so a workspace that never received
    ``README.md`` reported it present whenever *the directory the engine was
    launched from* contained one. The completion gate must answer from the
    bound workspace alone.
    """
    launch_dir = tmp_path / "launch-dir"
    launch_dir.mkdir()
    (launch_dir / "README.md").write_text("engine CWD decoy", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    monkeypatch.chdir(launch_dir)
    state = state_for(
        "Deliver exactly these files at the workspace root:\n- README.md\n",
        workspace,
    )

    assert _deliverables_missing_on_disk(state, str(workspace)) == ["README.md"]

    (workspace / "README.md").write_text("real deliverable", encoding="utf-8")
    assert _deliverables_missing_on_disk(state, str(workspace)) == []


def test_prose_bullet_is_not_mistaken_for_a_root_file_ledger(tmp_path):
    task = """Build a chat app with Next.js.
    - Use app.js to explain the browser bundle in the documentation.
    """
    state = state_for(task, tmp_path)
    assert _deliverables_missing_on_disk(state, str(tmp_path)) == []


def test_technology_stack_bullet_is_not_a_root_file_ledger(tmp_path):
    task = """Build a chat application.

    Use this technology stack:
    - Next.js
    - TypeScript
    """
    state = state_for(task, tmp_path)
    assert _deliverables_missing_on_disk(state, str(tmp_path)) == []


def test_app_called_name_is_a_directory_deliverable(tmp_path):
    """Field 2026-10-19: 'Create a Flutter app called flutterdemo' — the
    generated project FOLDER is the deliverable. The extension-based
    deliverable regex was blind to it (no dot), so the finish gate never
    objected when the turn ended right after the SDK install with no
    folder ever created."""
    state = state_for("Create a Flutter app called flutterdemo", tmp_path)
    assert _deliverables_missing_on_disk(state, str(tmp_path)) == ["flutterdemo"]
    assert should_continue(state) == "finish_gate"


def test_existing_app_directory_satisfies_the_deliverable(tmp_path):
    (tmp_path / "flutterdemo").mkdir()
    state = state_for("Create a Flutter app called flutterdemo", tmp_path)
    assert _deliverables_missing_on_disk(state, str(tmp_path)) == []


def test_function_called_name_is_not_a_deliverable(tmp_path):
    state = state_for(
        "Write a helper function called computeTax in src/util.ts", tmp_path
    )
    assert "computeTax" not in _deliverables_missing_on_disk(state, str(tmp_path))


def test_missing_deliverable_nudge_names_the_folder(tmp_path):
    """The gate knows WHAT is missing — the nudge must say so. A generic
    'produce the file' did not move a model that believed it already had."""
    state = state_for("Create a Flutter app called flutterdemo", tmp_path)
    result = finish_gate_node(state)
    text = result["messages"][0].content
    assert "flutterdemo" in text
    assert "do not exist on disk yet" in text
    # The nudge records the transcript length so finalize can detect a
    # nudged-but-never-acted ending instead of stamping it completed.
    assert result["nudged_at_msg_count"] == 1
