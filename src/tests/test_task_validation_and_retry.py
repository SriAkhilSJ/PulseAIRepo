"""
Tests for Deterministic Task Completion Validation and Retry Controller.
"""

import pytest
from src.graphs.task_validation import validate_database_lookup, validate_single_file_modification
from src.runtime.retry_controller import ToolRetryController


# ---------------------------------------------------------------------------
# Database Code Lookup Validation Tests
# ---------------------------------------------------------------------------
def test_database_lookup_passes_with_complete_evidence():
    complete_response = """
    ## Database Configuration Location
    The configuration is stored in `.env` (with `.env.example` as template).
    
    ## Database URL Resolution
    The application reads the connection parameters via `DATABASE_URL` using `os.getenv('DATABASE_URL')`.
    
    ## Connection Engine Instantiation
    The SQLAlchemy connection engine is instantiated using `create_engine(DATABASE_URL)`.
    """
    res = validate_database_lookup(complete_response, modified_files=[])
    assert res.passed is True
    assert res.has_exact_file_path is True
    assert res.has_url_resolution is True
    assert res.has_engine_instantiation is True
    assert len(res.failure_reasons) == 0


@pytest.mark.parametrize("config_path", [
    "src/config/db.py",
    "src/config/settings.py",
    "src/config/database.py",
    "config/db.py",
    "config/settings.py",
    "config/database.py",
    ".env.production",
    "src/agents/financial_store.py",
])
def test_database_lookup_passes_with_alternative_config_paths(config_path: str):
    response = f"""
    The database settings are located at `{config_path}`.
    It reads `DATABASE_URL` from the environment via `os.getenv("DATABASE_URL")`.
    The connection engine is created using `create_engine(DATABASE_URL)`.
    """
    res = validate_database_lookup(response, modified_files=[])
    assert res.passed is True, f"Failed for path {config_path}: {res.failure_reasons}"
    assert res.has_exact_file_path is True
    assert res.has_url_resolution is True
    assert res.has_engine_instantiation is True


def test_database_lookup_fails_when_path_omitted():
    incomplete = """
    The database URL is resolved via os.getenv('DATABASE_URL') and connected using create_engine().
    """
    res = validate_database_lookup(incomplete, modified_files=[])
    assert res.passed is False
    assert res.has_exact_file_path is False
    assert "Missing exact database configuration file path" in res.failure_reasons[0]


def test_database_lookup_fails_when_url_resolution_omitted():
    incomplete = """
    The database file is .env and connected using create_engine().
    """
    res = validate_database_lookup(incomplete, modified_files=[])
    assert res.passed is False
    assert res.has_url_resolution is False
    assert any("URL resolution" in r for r in res.failure_reasons)


def test_database_lookup_fails_when_engine_instantiation_omitted():
    incomplete = """
    The database configuration is in .env and resolved via DATABASE_URL.
    """
    res = validate_database_lookup(incomplete, modified_files=[])
    assert res.passed is False
    assert res.has_engine_instantiation is False
    assert any("engine" in r for r in res.failure_reasons)


def test_database_lookup_fails_on_unintended_file_modification():
    complete = """
    Config is in .env, resolved via DATABASE_URL, engine via create_engine.
    """
    res = validate_database_lookup(complete, modified_files=["src/core/main.py"])
    assert res.passed is False
    assert "src/core/main.py" in res.unintended_modifications


# ---------------------------------------------------------------------------
# Tool Retry Controller Tests
# ---------------------------------------------------------------------------
def test_retry_controller_detects_and_aborts_duplicate_invalid_retries():
    ctrl = ToolRetryController(max_consecutive_identical_failures=1)

    args = {"path": "server.py", "old_text": "foo", "new_text": "bar"}

    # First attempt: records error
    ctrl.record_attempt(turn=1, tool_name="edit_file", args=args, status="error", error="Text not found")
    assert ctrl.circuit_broken is False

    # Second attempt with IDENTICAL arguments: should trigger circuit breaker abort
    abort, reason = ctrl.should_abort_duplicate("edit_file", args)
    assert abort is True
    assert "Circuit breaker tripped" in reason
    assert "edit_file" in reason


def test_retry_controller_allows_different_arguments_after_failure():
    ctrl = ToolRetryController(max_consecutive_identical_failures=1)

    # First attempt failed
    args1 = {"path": "server.py", "old_text": "foo", "new_text": "bar"}
    ctrl.record_attempt(turn=1, tool_name="edit_file", args=args1, status="error", error="Text not found")

    # Second attempt with corrected arguments: allowed!
    args2 = {"path": "server.py", "old_text": "real_code", "new_text": "bar"}
    abort, reason = ctrl.should_abort_duplicate("edit_file", args2)
    assert abort is False
    assert reason is None


def test_retry_controller_schema_repair_guidance():
    ctrl = ToolRetryController()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": "Surgical replacement in file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Target file path"},
                        "old_text": {"type": "string", "description": "Existing code"},
                        "new_text": {"type": "string", "description": "Replacement code"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
        }
    ]

    guidance = ctrl.format_schema_repair_guidance("edit_file", tools, "Missing argument 'old_text'")
    assert "Schema Specification for 'edit_file'" in guidance
    assert "['path', 'old_text', 'new_text']" in guidance
    assert "Do NOT repeat the exact same invalid call" in guidance
