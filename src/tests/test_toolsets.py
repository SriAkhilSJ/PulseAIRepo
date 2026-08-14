"""Behavior contracts for Scope runtime profiles and the tool waist."""
import pytest

from src.agents.runtime_profile import (
    CAP_BROWSER,
    CAP_EXECUTION,
    CAP_RESEARCH,
    CAP_VERIFICATION,
    CAP_WORKSPACE_READ,
    CAP_WORKSPACE_WRITE,
    resolve_runtime_profile,
)
from src.tools.toolsets import (
    all_known_tool_names,
    resolve_toolset_names,
)

CORE = {"think", "verify", "ask_user", "session_search"}
MUTATION = {"write_file", "edit_file", "copy_file"}
PROCESS = {"run_terminal", "execute_code", "start_terminal"}
WEB = {"web_search", "web_fetch"}
_BROWSER_NAMES = frozenset({
    "browser_navigate", "browser_snapshot", "browser_screenshot",
    "browser_click", "browser_type", "browser_select",
    "browser_hover", "browser_evaluate",
})


@pytest.fixture
def with_browser(monkeypatch):
    monkeypatch.setattr(
        "src.tools.toolsets._browser_tool_names",
        lambda: tuple(sorted(_BROWSER_NAMES)),
    )
    return _BROWSER_NAMES


@pytest.mark.parametrize("task", ["hello", "research current AI IDEs", "fix auth.py", ""])
def test_neutral_core_is_always_present(task):
    assert CORE.issubset(set(resolve_toolset_names(task)))


def test_general_chat_has_no_side_effect_tools():
    resolved = set(resolve_toolset_names("hello, how are you?"))
    assert not (resolved & MUTATION)
    assert not (resolved & PROCESS)
    assert not (resolved & WEB)


def test_research_is_not_silently_treated_as_coding(monkeypatch):
    monkeypatch.delenv("PULSEAI_WEB_TOOLS", raising=False)
    profile = resolve_runtime_profile("Research the latest AI IDE agent architectures and compare sources")
    resolved = set(resolve_toolset_names("Research the latest AI IDE agent architectures and compare sources"))
    assert profile.has(CAP_RESEARCH)
    assert WEB.issubset(resolved)
    assert not (resolved & MUTATION)
    assert "typecheck_workspace" not in resolved


def test_web_operator_opt_out_wins(monkeypatch):
    monkeypatch.setenv("PULSEAI_WEB_TOOLS", "off")
    resolved = set(resolve_toolset_names("research current framework versions online"))
    assert not (resolved & WEB)


def test_workspace_explanation_is_read_only():
    profile = resolve_runtime_profile("Read this project and explain how it works")
    resolved = set(resolve_toolset_names("Read this project and explain how it works"))
    assert profile.has(CAP_WORKSPACE_READ)
    assert {"read_file", "list_files", "search_code"}.issubset(resolved)
    assert not (resolved & MUTATION)


def test_non_code_artifact_creation_gets_workspace_and_execution():
    task = "Create a market analysis report as a PDF file"
    profile = resolve_runtime_profile(task)
    resolved = set(resolve_toolset_names(task))
    assert profile.name == "research_artifact"
    assert profile.has(CAP_WORKSPACE_WRITE)
    assert profile.has(CAP_EXECUTION)
    assert profile.has(CAP_RESEARCH)
    assert {"write_file", "execute_code", "web_search"}.issubset(resolved)
    assert "typecheck_workspace" not in resolved


def test_coding_profile_gets_verification_without_browser():
    task = "Fix the authentication bug in src/auth.py and run the tests"
    profile = resolve_runtime_profile(task)
    resolved = set(resolve_toolset_names(task))
    assert profile.name == "coding"
    assert profile.has(CAP_WORKSPACE_READ)
    assert profile.has(CAP_WORKSPACE_WRITE)
    assert profile.has(CAP_EXECUTION)
    assert profile.has(CAP_VERIFICATION)
    assert "typecheck_workspace" in resolved
    assert not (resolved & _BROWSER_NAMES)


def test_ui_engineering_is_a_compound_profile(with_browser):
    task = "Build and verify a React dashboard component in the browser"
    profile = resolve_runtime_profile(task)
    resolved = set(resolve_toolset_names(task))
    assert profile.name == "ui_engineering"
    assert profile.has(CAP_BROWSER)
    assert profile.has(CAP_VERIFICATION)
    assert resolved & with_browser
    assert {"write_file", "run_terminal", "typecheck_workspace", "scaffold_nextjs"}.issubset(resolved)


def test_browser_navigation_does_not_imply_code_mutation(with_browser):
    task = "Navigate the website and take a screenshot"
    profile = resolve_runtime_profile(task)
    resolved = set(resolve_toolset_names(task))
    assert profile.has(CAP_BROWSER)
    assert resolved & with_browser
    assert not (resolved & MUTATION)
    assert "typecheck_workspace" not in resolved


def test_explicit_client_capability_extension_is_supported():
    config = {"configurable": {"scope_capabilities": ["research", "workspace_write"]}}
    profile = resolve_runtime_profile("hello", config)
    resolved = set(resolve_toolset_names("hello", config))
    assert profile.capabilities == (CAP_WORKSPACE_WRITE, CAP_RESEARCH)
    assert {"write_file", "web_search"}.issubset(resolved)
    assert "run_terminal" not in resolved


def test_unknown_client_capability_is_ignored():
    config = {"configurable": {"scope_capabilities": ["root_shell", "research"]}}
    profile = resolve_runtime_profile("hello", config)
    assert profile.capabilities == (CAP_RESEARCH,)


def test_strict_child_scope_cannot_be_broadened_by_task_text():
    config = {"configurable": {
        "scope_capabilities": ["workspace_read"],
        "scope_capabilities_strict": True,
    }}
    profile = resolve_runtime_profile("write code, run terminal, browse website", config)
    resolved = set(resolve_toolset_names("write code, run terminal, browse website", config))
    assert profile.capabilities == (CAP_WORKSPACE_READ,)
    assert {"read_file", "search_code"}.issubset(resolved)
    assert not (resolved & {"write_file", "run_terminal", "browser_navigate"})


def test_profile_and_tool_order_are_deterministic():
    task = "Create a researched PDF report comparing AI IDE agents"
    config = {"configurable": {"scope_capabilities": ["browser"]}}
    assert resolve_runtime_profile(task, config) == resolve_runtime_profile(task, config)
    assert resolve_toolset_names(task, config) == resolve_toolset_names(task, config)


def test_resolver_returns_no_duplicates_or_phantoms(with_browser):
    known = set(all_known_tool_names())
    for task in (
        "hello",
        "research current news",
        "create a spreadsheet report",
        "fix the Python bug",
        "build a React app",
    ):
        resolved = resolve_toolset_names(task)
        assert len(resolved) == len(set(resolved))
        assert set(resolved).issubset(known)


def test_profiles_have_strictly_different_footprints(with_browser):
    chat = resolve_toolset_names("hello")
    research = resolve_toolset_names("research current AI IDEs")
    coding = resolve_toolset_names("fix the Python bug and test it")
    ui = resolve_toolset_names("build and verify a React web app")
    assert len(chat) < len(research)
    assert len(chat) < len(coding) < len(ui)
