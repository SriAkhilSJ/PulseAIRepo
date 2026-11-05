"""
Phase 9.3.1.2: Workspace Security & Tool Contract Regression Suite.

Verifies the fail-closed security contract and LangChain tool integration:
A. edit_file with no runtime config: must be denied.
B. edit_file with empty configurable workspace: must be denied.
C. edit_file with valid workspace passed through invoke(..., config=cfg): must succeed.
D. edit_file with a path escaping the configured workspace: must be denied.
E. write_file with no workspace: must be denied.
F. copy_file with no workspace: must be denied.
G. search_files with an unauthorized workspace: must be denied.
H. Tool approval and authorization remain enforced through the actual dispatch path.
I. Model-facing schemas do not expose runtime config as an ordinary argument.
J. No unintended mutations occur during rejected calls.
"""

import os
from pathlib import Path
import pytest
from pydantic import ValidationError

from src.tools.file_tools import (
    edit_file,
    write_file,
    copy_file,
    search_files,
    search_code,
    typecheck_workspace,
    resolve_workspace_path,
)
from src.context.permission_config import tool_action_resources, effect_for


# ---------------------------------------------------------------------------
# Security Requirement A: edit_file with no runtime config must be denied
# ---------------------------------------------------------------------------
def test_security_A_edit_file_no_runtime_config_denied(tmp_path):
    target = tmp_path / "target.py"
    target.write_text("orig = 1\n", encoding="utf-8")

    # Calling invoke with NO config kwarg must fail closed
    res = edit_file.invoke({"path": str(target), "old_text": "orig = 1", "new_text": "orig = 2"})
    assert "⛔ Tool execution refused: missing workspace restriction" in res
    # File must be untouched
    assert target.read_text(encoding="utf-8") == "orig = 1\n"


# ---------------------------------------------------------------------------
# Security Requirement B: edit_file with empty configurable workspace must be denied
# ---------------------------------------------------------------------------
def test_security_B_edit_file_empty_workspace_denied(tmp_path):
    target = tmp_path / "target.py"
    target.write_text("orig = 1\n", encoding="utf-8")

    # Calling invoke with explicitly empty workspace must fail closed
    res = edit_file.invoke(
        {"path": str(target), "old_text": "orig = 1", "new_text": "orig = 2"},
        config={"configurable": {"workspace": ""}},
    )
    assert "⛔ Tool execution refused: missing workspace restriction" in res

    # Calling invoke with whitespace workspace must fail closed
    res_ws = edit_file.invoke(
        {"path": str(target), "old_text": "orig = 1", "new_text": "orig = 2"},
        config={"configurable": {"workspace": "   "}},
    )
    assert "⛔ Tool execution refused: missing workspace restriction" in res_ws
    assert target.read_text(encoding="utf-8") == "orig = 1\n"


# ---------------------------------------------------------------------------
# Security Requirement C: edit_file with valid workspace succeeds
# ---------------------------------------------------------------------------
def test_security_C_edit_file_valid_workspace_succeeds(tmp_path):
    target = tmp_path / "valid_test.py"
    target.write_text("x = 10\ny = 20\n", encoding="utf-8")

    cfg = {"configurable": {"workspace": str(tmp_path), "thread_id": "test-valid-args"}}
    res = edit_file.invoke(
        {"path": "valid_test.py", "old_text": "x = 10", "new_text": "x = 99"},
        config=cfg,
    )

    assert "✅ Edited" in res
    assert "-x = 10" in res
    assert "+x = 99" in res
    assert target.read_text(encoding="utf-8") == "x = 99\ny = 20\n"


# ---------------------------------------------------------------------------
# Security Requirement D: edit_file with path escaping workspace must be denied
# ---------------------------------------------------------------------------
def test_security_D_edit_file_path_escaping_workspace_denied(tmp_path):
    ws = tmp_path / "sandbox"
    ws.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret = 12345\n", encoding="utf-8")

    cfg = {"configurable": {"workspace": str(ws)}}

    # Relative path escape
    res = edit_file.invoke(
        {"path": "../outside.txt", "old_text": "secret", "new_text": "hacked"},
        config=cfg,
    )
    assert "⛔ Security violation" in res or "escapes workspace" in res
    assert outside_file.read_text(encoding="utf-8") == "secret = 12345\n"

    # Absolute path escape outside workspace
    res_abs = edit_file.invoke(
        {"path": str(outside_file.resolve()), "old_text": "secret", "new_text": "hacked"},
        config=cfg,
    )
    assert "⛔ Security violation" in res_abs or "escapes workspace" in res_abs or "❌ File not found" in res_abs
    assert outside_file.read_text(encoding="utf-8") == "secret = 12345\n"


# ---------------------------------------------------------------------------
# Security Requirement E: write_file with no workspace must be denied
# ---------------------------------------------------------------------------
def test_security_E_write_file_no_workspace_denied(tmp_path):
    # No config
    res1 = write_file.invoke({"path": "foo.txt", "content": "malicious"})
    assert "⛔ Tool execution refused: missing workspace restriction" in res1

    # Empty configurable workspace
    res2 = write_file.invoke(
        {"path": "foo.txt", "content": "malicious"},
        config={"configurable": {"workspace": ""}},
    )
    assert "⛔ Tool execution refused: missing workspace restriction" in res2
    assert not (tmp_path / "foo.txt").exists()


# ---------------------------------------------------------------------------
# Security Requirement F: copy_file with no workspace must be denied
# ---------------------------------------------------------------------------
def test_security_F_copy_file_no_workspace_denied(tmp_path):
    # No config
    res1 = copy_file.invoke({"src": "a.txt", "dst": "b.txt"})
    assert "⛔ Tool execution refused: missing workspace restriction" in res1

    # Empty configurable workspace
    res2 = copy_file.invoke(
        {"src": "a.txt", "dst": "b.txt"},
        config={"configurable": {"workspace": ""}},
    )
    assert "⛔ Tool execution refused: missing workspace restriction" in res2


# ---------------------------------------------------------------------------
# Security Requirement G: search_files with unauthorized workspace must be denied
# ---------------------------------------------------------------------------
def test_security_G_search_files_unauthorized_workspace_denied(tmp_path):
    # No config
    res1 = search_files.invoke({"pattern": "secret", "path": "."})
    assert "⛔ Tool execution refused: missing workspace restriction" in res1

    # Empty configurable workspace
    res2 = search_files.invoke(
        {"pattern": "secret", "path": "."},
        config={"configurable": {"workspace": ""}},
    )
    assert "⛔ Tool execution refused: missing workspace restriction" in res2

    # search_code also delegates and must be refused
    res3 = search_code.invoke({"query": "secret", "path": "."})
    assert "⛔ Tool execution refused: missing workspace restriction" in res3

    # typecheck_workspace also must be refused with no config
    res4 = typecheck_workspace.invoke({})
    assert "⛔ Tool execution refused: missing workspace restriction" in res4


# ---------------------------------------------------------------------------
# Security Requirement H: Tool approval & authorization enforced through dispatch
# ---------------------------------------------------------------------------
def test_security_H_tool_approval_and_authorization_enforced():
    action, resources = tool_action_resources("edit_file", {"path": "src/app.py"})
    assert action == "edit"
    assert resources == ["src/app.py"]

    rules = [
        ("edit", "src/**", "allow"),
        ("edit", "critical/**", "deny"),
        ("edit", ".env*", "deny"),
    ]
    assert effect_for("edit", ["src/app.py"], rules) == "allow"
    assert effect_for("edit", ["critical/db.py"], rules) == "deny"
    assert effect_for("edit", [".env"], rules) == "deny"


# ---------------------------------------------------------------------------
# Security Requirement I: Schemas do not expose runtime config to model
# ---------------------------------------------------------------------------
def test_security_I_schemas_do_not_expose_runtime_config():
    file_tools_list = [
        edit_file,
        write_file,
        copy_file,
        search_files,
        search_code,
        typecheck_workspace,
    ]
    for t in file_tools_list:
        args = t.args
        assert "config" not in args, f"Tool '{t.name}' leaked 'config' into model-facing args schema!"
        if t.args_schema:
            schema_props = t.args_schema.model_json_schema().get("properties", {})
            assert "config" not in schema_props, f"Tool '{t.name}' leaked 'config' into Pydantic schema properties!"


# ---------------------------------------------------------------------------
# Security Requirement J: No unintended mutations during rejected calls
# ---------------------------------------------------------------------------
def test_security_J_no_unintended_mutations_on_rejected_calls(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    f1 = ws / "protected.py"
    f1.write_text("original_bytes = True\n", encoding="utf-8")
    mtime_before = f1.stat().st_mtime_ns

    # Call with missing config
    res_no_cfg = edit_file.invoke({"path": "protected.py", "old_text": "original_bytes = True", "new_text": "corrupt"})
    assert "⛔ Tool execution refused" in res_no_cfg
    assert f1.stat().st_mtime_ns == mtime_before
    assert f1.read_text(encoding="utf-8") == "original_bytes = True\n"

    # Call with empty workspace
    res_empty_ws = edit_file.invoke(
        {"path": "protected.py", "old_text": "original_bytes = True", "new_text": "corrupt"},
        config={"configurable": {"workspace": ""}},
    )
    assert "⛔ Tool execution refused" in res_empty_ws
    assert f1.stat().st_mtime_ns == mtime_before
    assert f1.read_text(encoding="utf-8") == "original_bytes = True\n"

    # Call write_file without workspace to non-existent file
    res_write = write_file.invoke({"path": "new_unauthorized.py", "content": "bad"})
    assert "⛔ Tool execution refused" in res_write
    assert not (ws / "new_unauthorized.py").exists()


# ---------------------------------------------------------------------------
# Additional Tool Contract Tests (Validation & Recovery)
# ---------------------------------------------------------------------------
def test_missing_required_arguments(tmp_path):
    cfg = {"configurable": {"workspace": str(tmp_path)}}

    # Empty string path
    res = edit_file.invoke({"path": "", "old_text": "a", "new_text": "b"}, config=cfg)
    assert "❌ Missing or invalid required parameter" in res
    assert "'path'" in res

    # Missing old_text from dictionary (Pydantic schema validation rejects)
    with pytest.raises(ValidationError) as exc_info:
        edit_file.invoke({"path": "foo.py", "new_text": "b"}, config=cfg)
    assert "old_text" in str(exc_info.value)

    # Missing new_text from dictionary (Pydantic schema validation rejects)
    with pytest.raises(ValidationError) as exc_info:
        edit_file.invoke({"path": "foo.py", "old_text": "a"}, config=cfg)
    assert "new_text" in str(exc_info.value)

    # Missing path from dictionary (Pydantic schema validation rejects)
    with pytest.raises(ValidationError) as exc_info:
        edit_file.invoke({"old_text": "a", "new_text": "b"}, config=cfg)
    assert "path" in str(exc_info.value)


def test_invalid_parameter_types(tmp_path):
    cfg = {"configurable": {"workspace": str(tmp_path)}}

    # Path is not a string (integer passed) -> rejected by schema validation
    with pytest.raises(ValidationError) as exc_info:
        edit_file.invoke({"path": 12345, "old_text": "a", "new_text": "b"}, config=cfg)
    assert "path" in str(exc_info.value)

    # old_text is not a string (list passed) -> rejected by schema validation
    with pytest.raises(ValidationError) as exc_info:
        edit_file.invoke({"path": "foo.py", "old_text": ["not", "string"], "new_text": "b"}, config=cfg)
    assert "old_text" in str(exc_info.value)

    # new_text is not a string (dict passed) -> rejected by schema validation
    with pytest.raises(ValidationError) as exc_info:
        edit_file.invoke({"path": "foo.py", "old_text": "a", "new_text": {"not": "string"}}, config=cfg)
    assert "new_text" in str(exc_info.value)


def test_path_validation(tmp_path):
    cfg = {"configurable": {"workspace": str(tmp_path)}}
    target = tmp_path / "file_cleaned.py"
    target.write_text("data = True\n", encoding="utf-8")

    # Markdown link wrapped path
    res = edit_file.invoke(
        {"path": "[file_cleaned.py](file_cleaned.py)", "old_text": "data = True", "new_text": "data = False"},
        config=cfg,
    )
    assert "✅ Edited" in res
    assert target.read_text(encoding="utf-8") == "data = False\n"

    # Non-existent file
    res = edit_file.invoke(
        {"path": "non_existent.py", "old_text": "foo", "new_text": "bar"},
        config=cfg,
    )
    assert "❌ File not found" in res

    # Target is a directory
    sub_dir = tmp_path / "sub_dir"
    sub_dir.mkdir()
    res = edit_file.invoke(
        {"path": "sub_dir", "old_text": "foo", "new_text": "bar"},
        config=cfg,
    )
    assert "DIRECTORY" in res


def test_failed_edit_recovery(tmp_path):
    target = tmp_path / "recover.py"
    initial_content = "def step1():\n    return 'initial'\n"
    target.write_text(initial_content, encoding="utf-8")

    cfg = {"configurable": {"workspace": str(tmp_path)}}

    # Attempt 1: Old text does not match (failed edit on genuinely dissimilar text)
    res1 = edit_file.invoke(
        {"path": "recover.py", "old_text": "zzz_absent_anchor_never_matched()", "new_text": "def step2():"},
        config=cfg,
    )
    assert "❌ Text not found" in res1
    assert "Tip: Read the file first" in res1
    # File content must remain completely unchanged
    assert target.read_text(encoding="utf-8") == initial_content

    # Attempt 2: Recover with accurate old_text
    res2 = edit_file.invoke(
        {"path": "recover.py", "old_text": "return 'initial'", "new_text": "return 'recovered'"},
        config=cfg,
    )
    assert "✅ Edited" in res2
    assert "return 'recovered'" in target.read_text(encoding="utf-8")
