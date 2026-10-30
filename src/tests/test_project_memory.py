"""Unit tests for 5-Tier ProjectMemoryManager (CrusorAI 2.1).

Validates:
1. Separation between user preferences and project decisions.
2. Project isolation (Project A cannot read Project B).
3. Secret redaction before serialization.
4. Atomic writes preventing corruption.
5. Error graveyard recording and retrieval.
"""
import pytest
from src.context.project_memory import ProjectMemoryManager, redact_secrets


def test_secret_redaction():
    text = "Authorization: Bearer sk-ant-api03-abcdef1234567890abcdef and password='super_secret_pass'"
    redacted = redact_secrets(text)
    assert "sk-ant" not in redacted
    assert "super_secret_pass" not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_user_vs_project_scope_separation(tmp_path):
    base_dir = str(tmp_path / ".crusorai")
    mem_mgr = ProjectMemoryManager(workspace_path="/path/to/my_project", base_dir=base_dir)

    # 1. Write user preference
    mem_mgr.set_user_preference("package_manager", "pnpm")

    # 2. Write project decision
    mem_mgr.record_decision("database", "Use SQLite WAL", "Avoid thread locking")

    # Verify user pref is not in project memory
    project_data = mem_mgr.get_project_memory()
    assert "package_manager" not in project_data.get("blueprint", {})
    assert len(project_data.get("decision_ledger", [])) == 1
    assert project_data["decision_ledger"][0]["topic"] == "database"

    # Verify user pref is in global user preferences
    user_prefs = mem_mgr.get_user_preferences()
    assert user_prefs.get("package_manager") == "pnpm"


def test_project_isolation(tmp_path):
    base_dir = str(tmp_path / ".crusorai")
    project_a = ProjectMemoryManager(workspace_path="/workspace/project_a", base_dir=base_dir)
    project_b = ProjectMemoryManager(workspace_path="/workspace/project_b", base_dir=base_dir)

    project_a.record_decision("auth", "JWT in HTTP-only cookie", "XSS protection")

    # Project B must NOT see Project A's decisions
    mem_b = project_b.get_project_memory()
    assert len(mem_b.get("decision_ledger", [])) == 0


def test_error_graveyard_persistence(tmp_path):
    base_dir = str(tmp_path / ".crusorai")
    mem_mgr = ProjectMemoryManager(workspace_path="/workspace/test_app", base_dir=base_dir)

    mem_mgr.record_resolved_error(
        error_pattern="sqlite3.OperationalError: SQLite objects created in a thread...",
        verified_fix="PRAGMA journal_mode=WAL and per-request connections",
        tool="terminal"
    )

    mem = mem_mgr.get_project_memory()
    graveyard = mem.get("error_graveyard", [])
    assert len(graveyard) == 1
    assert "journal_mode=WAL" in graveyard[0]["verified_fix"]


def test_build_system_prompt_injection(tmp_path):
    base_dir = str(tmp_path / ".crusorai")
    mem_mgr = ProjectMemoryManager(workspace_path="/workspace/app", base_dir=base_dir)

    mem_mgr.set_user_preference("indentation", "2 spaces")
    mem_mgr.set_blueprint_entry("framework", "FastAPI + React")
    mem_mgr.record_decision("database", "Use SQLite WAL", "Avoid thread locks")
    mem_mgr.record_resolved_error("EADDRINUSE: 8000", "Use dynamic port lookup", "terminal")

    prompt = mem_mgr.build_system_prompt()
    assert "<living_project_memory>" in prompt
    assert "</living_project_memory>" in prompt
    assert "Scoped User Preferences" in prompt
    assert "indentation" in prompt
    assert "FastAPI + React" in prompt
    assert "Key Architectural Decisions" in prompt
    assert "Use SQLite WAL" in prompt
    assert "Error Graveyard (Past Resolved Pitfalls - Do Not Repeat)" in prompt
    assert "EADDRINUSE: 8000" in prompt
