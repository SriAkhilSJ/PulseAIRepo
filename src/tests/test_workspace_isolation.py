"""Internal runtime metadata must not pollute the user project."""
from __future__ import annotations

import os
from pathlib import Path

from src.graphs.chat_graph import stream_agent


def test_one_markdown_task_leaves_no_internal_dirs(tmp_path: Path, monkeypatch) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "README.md").write_text("# project\n", encoding="utf-8")
    app_data = tmp_path / "appdata"
    monkeypatch.setenv("CRUSORAI_ORCHESTRATOR_MOCK", "1")
    monkeypatch.setenv("MEMORY_NUDGE_INTERVAL", "0")
    monkeypatch.setenv("CRUSORAI_APP_DATA_ROOT", str(app_data))
    thread = "isolation-test"
    result = stream_agent(
        "Create exactly one file named hello.md containing a short greeting. "
        "Do not create source-code files, tests or any other artifacts.",
        thread_id=thread,
        workspace=str(ws),
        execution_mode="agent",
        approval_channel=True,
        approval_policy="workspace_session",
        turn_id="turn-isolation",
        canonical_runtime=True,
    )
    assert result.completed is True
    assert (ws / "hello.md").exists()
    names = {p.name for p in ws.iterdir()}
    assert ".crusorai" not in names
    assert "diagnostics" not in names
    assert (app_data / "orchestration").exists()
