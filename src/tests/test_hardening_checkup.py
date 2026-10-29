"""Tests for CrusorAI 2.0 Hardening: Syntax Pre-flight, Arg Coercion, and Ambiguity Recovery.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from langchain_core.tools import StructuredTool

from src.tools.file_tools import write_file, edit_file, _python_syntax_receipt, _json_syntax_receipt
from src.graphs.parallel_tools import coerce_tool_arg_aliases, _ARG_ALIASES


def test_python_syntax_receipt_rejects_broken_new_file():
    broken_code = 'PRIMARY KEY (client_id, timestamp)")")'
    err = _python_syntax_receipt("", broken_code)
    assert err is not None
    assert "Write rejected" in err or "Edit rejected" in err
    assert "valid Python" in err


def test_python_syntax_receipt_allows_clean_python():
    clean_code = "def add(a, b):\n    return a + b\n"
    err = _python_syntax_receipt("", clean_code)
    assert err is None


def test_json_syntax_receipt_rejects_broken_new_file():
    broken_json = '{"name": "test", "val": }'
    err = _json_syntax_receipt("", broken_json)
    assert err is not None
    assert "rejected" in err
    assert "valid JSON" in err


def test_json_syntax_receipt_allows_clean_json():
    clean_json = '{"name": "test", "val": 42}'
    err = _json_syntax_receipt("", clean_json)
    assert err is None


def test_write_file_rejects_broken_python_on_disk(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    cfg = {"configurable": {"workspace": str(ws), "thread_id": "t1"}}

    # Attempt to write a brand new Python file with broken syntax (the exact GatePulse failure)
    res = write_file.invoke(
        {"path": "backend/server.py", "content": 'def broken():\n    return ")")'},
        config=cfg,
    )
    assert "rejected" in res
    assert "valid Python" in res
    assert not (ws / "backend" / "server.py").exists(), "Broken file must not exist on disk"


def test_write_file_succeeds_on_valid_python(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    cfg = {"configurable": {"workspace": str(ws), "thread_id": "t1"}}

    res = write_file.invoke(
        {"path": "backend/server.py", "content": 'def ok():\n    return "ok"\n'},
        config=cfg,
    )
    assert "File written" in res
    assert (ws / "backend" / "server.py").exists()


def test_coerce_tool_arg_aliases_strips_punctuation_and_maps_aliases():
    def fake_edit(path: str, old_text: str, new_text: str) -> str:
        """Fake edit tool."""
        return "ok"

    tool = StructuredTool.from_function(fake_edit, name="edit_file", description="Fake edit tool")

    # Model emitted kwargs syntax: old_text=, new_text=, and path:
    raw_args = {
        "path:": "backend/server.py",
        "old_text=": "foo",
        "new_text=": "bar",
    }
    coerced = coerce_tool_arg_aliases(tool, raw_args)
    assert coerced["path"] == "backend/server.py"
    assert coerced["old_text"] == "foo"
    assert coerced["new_text"] == "bar"


def test_coerce_tool_arg_aliases_bidirectional_mapping():
    def fake_edit(path: str, old_text: str, new_text: str) -> str:
        """Fake edit tool."""
        return "ok"

    tool = StructuredTool.from_function(fake_edit, name="edit_file", description="Fake edit tool")

    # Model emitted old_string and new_string instead of old_text and new_text
    raw_args = {
        "file_path": "backend/server.py",
        "old_string": "def old():",
        "new_string": "def new():",
    }
    coerced = coerce_tool_arg_aliases(tool, raw_args)
    assert coerced["path"] == "backend/server.py"
    assert coerced["old_text"] == "def old():"
    assert coerced["new_text"] == "def new():"


def test_edit_file_ambiguity_returns_actionable_tip(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    cfg = {"configurable": {"workspace": str(ws), "thread_id": "t1"}}

    # Create a file with duplicate lines
    file_path = ws / "test.txt"
    file_path.write_text("repeat_line\nrepeat_line\n", encoding="utf-8")

    res = edit_file.invoke(
        {"path": "test.txt", "old_text": "repeat_line", "new_text": "new_line"},
        config=cfg,
    )
    assert "Text not found" in res or "ambiguous" in res.lower()
    assert "Tip:" in res
    assert "surrounding context" in res or "write_file" in res
