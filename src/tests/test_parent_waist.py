"""Parent tool-waist contracts (founder core-cost round, 2026-10-17).

The interactive parent used to bind all ~68 registered schemas on
every model call while the prompt engine gated its guidance on the
capability waist. The binder now resolves the same runtime profile
from the same task text, floors it with the build agent's everyday
kit, and lets the profile add exotic families (browser, targets /
devices, web / media, delegation) only when the task signals them.

The contracts that matter are the 2026-09-07 field failures: a
keyword gate must never REMOVE everyday tools mid-turn ("Run the
build..." stripped browser tools and todo_list). So: the floor is
unconditional, only exotic families are gated, children keep their
strict scope untouched, and CRUSORAI_PARENT_WAIST=off restores the
full registry bind exactly.
"""
from __future__ import annotations

import json

import pytest

EVERYDAY = {
    "think", "verify", "session_search", "todo_list", "clarify",
    "skills_list",
    "read_file", "list_files", "search_files", "search_code",
    "write_file", "edit_file", "copy_file",
    "run_terminal", "terminal", "execute_code",
    "plan_update", "display_crusor_task",
}
BROWSER = {"browser_navigate", "browser_snapshot", "browser_click"}
DEVICES = {"device_action", "device_screenshot", "detect_targets", "build_target"}
DELEGATION = {"delegate_to_subagent", "delegate_to_subagent_batch"}


def _state(task: str = "", plan=None) -> dict:
    return {
        "messages": [],
        "current_task": task,
        "latest_instruction": task,
        "plan": plan or [],
        "execution_trace": [],
        "iteration_used": 0,
    }


def _config(tmp_path, **overrides) -> dict:
    configurable = {
        "thread_id": "desktop-parent-1",
        "workspace": str(tmp_path),
        "approval_policy": "ask",
    }
    configurable.update(overrides)
    return {"configurable": configurable}


def _bound_names(state, config) -> list[str]:
    from src.graphs.chat_graph import _resolve_bound_tools

    return [tool.name for tool in _resolve_bound_tools(state, config)]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("CRUSORAI_PARENT_WAIST", raising=False)
    monkeypatch.delenv("CRUSORAI_MAX_TOOLS", raising=False)
    monkeypatch.delenv("CRUSORAI_WEB_TOOLS", raising=False)


@pytest.fixture
def with_browser_cli(monkeypatch):
    """The binder strips browser tools when the agent-browser CLI is
    absent (availability, hermes check_fn) — fake it present."""
    monkeypatch.setattr(
        "src.tools.browser_tools.find_agent_browser", lambda: "/bin/true"
    )


@pytest.mark.parametrize("task", ["hello", "fix it", "", "sounds good, continue"])
def test_everyday_kit_is_never_gated(tmp_path, task):
    names = set(_bound_names(_state(task), _config(tmp_path)))
    assert EVERYDAY.issubset(names), f"task {task!r} lost everyday tools"
    # ...and the exotic families stay off without a signal.
    assert not (names & BROWSER)
    assert not (names & DEVICES)
    assert not (names & DELEGATION)
    assert "web_search" not in names
    assert "scaffold_flutter" not in names


def test_2026_09_07_regression_build_word_cannot_strip_browser(
    tmp_path, with_browser_cli
):
    """The field failure: 'Run the build...' amputated the browser
    tools and todo_list mid-turn. Additive capabilities + an
    unconditional floor make that class impossible."""
    names = set(_bound_names(
        _state("Run the build, then test the browser flow and screenshot it"),
        _config(tmp_path),
    ))
    assert BROWSER.issubset(names)
    assert "todo_list" in names
    assert "write_file" in names


def test_coding_task_gets_the_floor_and_nothing_exotic(tmp_path):
    names = set(_bound_names(
        _state("Fix the authentication bug in src/auth.py and run the tests"),
        _config(tmp_path),
    ))
    assert EVERYDAY.issubset(names)
    assert not (names & BROWSER)
    assert not (names & DEVICES)
    assert not (names & DELEGATION)
    assert "web_search" not in names
    assert "scaffold_nextjs" not in names


def test_research_task_adds_web_only(tmp_path):
    names = set(_bound_names(
        _state("Research the latest vector databases and compare sources"),
        _config(tmp_path),
    ))
    assert {"web_search", "web_fetch", "web_extract"}.issubset(names)
    assert not (names & DEVICES)
    assert not (names & DELEGATION)


def test_media_task_binds_generation(tmp_path):
    names = set(_bound_names(
        _state("Generate an image for the hero section"), _config(tmp_path)
    ))
    assert "generate_image" in names
    assert not (names & DEVICES)


def test_mobile_task_adds_targets_and_devices(tmp_path):
    names = set(_bound_names(
        _state("Build the Flutter app and verify it on the Android emulator"),
        _config(tmp_path),
    ))
    assert DEVICES.issubset(names)
    assert "scaffold_flutter" in names
    assert not (names & BROWSER)


def test_delegation_vocabulary_binds_the_delegate_tools(tmp_path):
    names = set(_bound_names(
        _state("Use a subagent to review the test suite"), _config(tmp_path)
    ))
    assert DELEGATION.issubset(names)


def test_complex_task_binds_delegation(tmp_path):
    names = set(_bound_names(
        _state("Audit the architecture end to end across several modules"),
        _config(tmp_path),
    ))
    assert DELEGATION.issubset(names)


def test_typecheck_rides_the_floor_when_a_project_exists(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    names = set(_bound_names(_state("hello"), _config(tmp_path)))
    assert "typecheck_workspace" in names


def _pin_availability_off(monkeypatch) -> set[str]:
    """Pin the two check_fn availability strips OFF (no browser CLI,
    no typecheck project in the tmp workspace) BEFORE binding, and
    return today's expected un-waisted pool for that environment."""
    monkeypatch.setattr(
        "src.tools.browser_tools.find_agent_browser",
        lambda: (_ for _ in ()).throw(RuntimeError("no CLI")),
    )
    from src.graphs.chat_graph import tools

    registry = {tool.name for tool in tools}
    return registry - {n for n in registry if n.startswith("browser_")} - {
        "typecheck_workspace"
    }


def test_kill_switch_restores_the_full_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_PARENT_WAIST", "off")
    expected = _pin_availability_off(monkeypatch)
    names = _bound_names(_state("fix the bug"), _config(tmp_path))
    assert set(names) == expected
    assert len(names) == len(set(names))


def test_strict_child_scope_is_not_widened_by_the_floor(tmp_path):
    config = _config(
        tmp_path,
        scope_capabilities=["workspace_read"],
        scope_capabilities_strict=True,
    )
    names = set(_bound_names(
        _state("write code, run terminal, browse the website"), config
    ))
    assert "read_file" in names
    assert "write_file" not in names, "the parent floor must never widen a child"
    assert "run_terminal" not in names


def test_subagent_thread_keeps_todays_surface(tmp_path, monkeypatch):
    expected = _pin_availability_off(monkeypatch)
    names = set(_bound_names(
        _state("fix the bug"), _config(tmp_path, thread_id="sub-research-7")
    ))
    assert names == expected


def test_binding_is_deterministic_and_registry_ordered(tmp_path):
    state = _state("fix the login bug and run pytest")
    config = _config(tmp_path)
    first = _bound_names(state, config)
    second = _bound_names(state, config)
    assert first == second
    from src.graphs.chat_graph import tools

    registry_order = [tool.name for tool in tools]
    assert first == [n for n in registry_order if n in set(first)]


def test_waist_only_widens_as_the_turns_text_grows(tmp_path, with_browser_cli):
    before = set(_bound_names(_state("fix the login bug"), _config(tmp_path)))
    after = set(_bound_names(
        _state(
            "fix the login bug",
            plan=[{"description": "then verify the fix in the browser"}],
        ),
        _config(tmp_path),
    ))
    assert before.issubset(after), "a family must never disappear mid-turn"
    assert BROWSER.issubset(after)


def test_floor_schema_bill_is_a_fraction_of_the_full_bind(tmp_path):
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from src.graphs.chat_graph import tools

    def chars(tool_list) -> int:
        return sum(len(json.dumps(convert_to_openai_tool(t))) for t in tool_list)

    full = chars(list(tools))
    from src.graphs.chat_graph import _resolve_bound_tools

    floored = _resolve_bound_tools(_state("fix the bug"), _config(tmp_path))
    assert len(floored) < len(tools)
    assert chars(floored) <= 0.65 * full, (
        "the floored parent bind must stay well under the full "
        "registry's per-call schema bill"
    )
