"""Permanent regression fixtures preserving real historical model failure cases.

Ensures that historical model failures (such as GPT-4o-mini LogPulse Run 1)
remain permanently reproducible as offline test cases without calling external APIs.
"""

from __future__ import annotations

import ast
import io
import os
import py_compile
import tempfile
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_GPT_LOGPULSE_DIR = REPO_ROOT / "bench-results" / "gpt_4o_mini_logpulse_run_1_showcase"


def test_gpt_4o_mini_raw_output_preserves_syntax_error():
    """Verify that the immutable raw GPT-4o-mini deliverable reproduces the syntax/indentation failure."""
    server_file = RAW_GPT_LOGPULSE_DIR / "backend" / "server.py"
    assert server_file.exists(), f"Raw archive missing: {server_file}"

    # Verify that py_compile catches the indentation/syntax error
    with pytest.raises(py_compile.PyCompileError) as exc_info:
        py_compile.compile(str(server_file), doraise=True)
    assert "IndentationError" in str(exc_info.value) or "SyntaxError" in str(exc_info.value)


def test_gpt_4o_mini_raw_output_preserves_third_party_violation():
    """Verify that the raw deliverable contains forbidden third-party imports (flask, flask_sqlalchemy)."""
    server_file = RAW_GPT_LOGPULSE_DIR / "backend" / "server.py"
    code = server_file.read_text(encoding="utf-8")
    assert "import flask" in code or "from flask import" in code
    assert "SQLAlchemy" in code


def test_completion_gate_condemns_unrunnable_syntax_deliverable(tmp_path):
    """Verify that CrusorAI completion gate refuses completed=True on syntax errors."""
    from src.graphs.chat_graph import finalize_node

    broken_server = tmp_path / "backend" / "server.py"
    broken_server.parent.mkdir(parents=True, exist_ok=True)
    broken_server.write_text("def run():\nreturn 1\n")  # IndentationError

    state = {
        "current_task": "Build server and verify it",
        "latest_instruction": "Build server and verify it",
        "workspace": str(tmp_path),
        "messages": [
            HumanMessage(content="Build server and verify it"),
            AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "backend/server.py"}, "id": "w1"}]),
            ToolMessage(content="File written: backend/server.py", tool_call_id="w1", name="write_file"),
            AIMessage(content="", tool_calls=[{"name": "terminal", "args": {"command": "python backend/server.py"}, "id": "t1"}]),
            ToolMessage(content="IndentationError: expected an indented block\nExit code: 1", tool_call_id="t1", name="terminal"),
            AIMessage(content="Application files created. Complete!"),
        ],
        "steps_completed": ["Wrote file: backend/server.py"],
        "failed_steps": ["Command failed: python backend/server.py\nIndentationError"],
        "plan": [],
    }

    out = finalize_node(state, {"configurable": {}})
    assert out["task_completed"] is False
    assert out["task_status"] in ("failed", "unverified")
    assert out["application_verification_status"] == "failed"
    assert out["required_checks_passed"] is False
