# src/tests/test_toolsets.py
"""
Behavior-contract tests for the toolset waist (P0-A, Hermes Law #2).

These test INVARIANTS of resolve_toolset_names() — not frozen counts or
source-text snapshots (Hermes bans change-detector tests). The resolver is a
pure function of (task, config, env), so it is unit-testable with zero LLM /
embedding / MCP dependencies.
"""
import os

import pytest

from src.tools.toolsets import (
    resolve_toolset_names,
    all_known_tool_names,
    looks_like_ui_task,
    looks_like_execution_task,
)


# --------------------------------------------------------------------------- #
# Invariant: the narrow waist ships on every turn, regardless of task.       #
# --------------------------------------------------------------------------- #
CORE = {
    "think", "verify", "ask_user",
    "read_file", "list_files", "search_code",
    "write_file", "edit_file",
    "run_terminal", "execute_code",
}


@pytest.mark.parametrize(
    "task",
    [
        "build a react chat app",            # UI + execution
        "fix the bug in auth.py",            # execution, non-UI
        "explain how the parser works",      # explain, non-execution
        "",                                  # no task yet (first turn)
        "hello",                             # pure chat
    ],
)
def test_core_tools_always_present(task):
    resolved = set(resolve_toolset_names(task))
    assert CORE.issubset(resolved), (
        f"core tools missing for task {task!r}: {CORE - resolved}"
    )


# --------------------------------------------------------------------------- #
# Invariant: browser tools (the dominant per-call cost) are GATED — present   #
# only for UI tasks that need them to prove rendering.                        #
#                                                                              #
# The canonical 8 browser_* names are patched in (not imported from           #
# browser_mcp) so the test exercises the resolver's GATING logic without      #
# depending on the optional puppeteer MCP stack being installed. In the real  #
# runtime, chat_graph only loads if browser_mcp imports, so these names       #
# always exist there.                                                          #
# --------------------------------------------------------------------------- #
_BROWSER_NAMES = frozenset({
    "browser_navigate", "browser_snapshot", "browser_screenshot",
    "browser_click", "browser_type", "browser_select",
    "browser_hover", "browser_evaluate",
})


@pytest.fixture
def with_browser(monkeypatch):
    """Simulate the real runtime where browser_mcp is importable."""
    monkeypatch.setattr(
        "src.tools.toolsets._browser_tool_names",
        lambda: tuple(sorted(_BROWSER_NAMES)),
    )
    return _BROWSER_NAMES


def test_browser_excluded_for_non_ui_coding_task(with_browser):
    resolved = set(resolve_toolset_names("refactor the auth module in src/auth.py"))
    assert not (resolved & with_browser), (
        f"browser tools leaked into a non-UI task: {resolved & with_browser}"
    )


@pytest.mark.parametrize(
    "task",
    [
        "build a react chat app",
        "create a Next.js dashboard component",
        "make a web app with a login page",
    ],
)
def test_browser_included_for_ui_tasks(task, with_browser):
    resolved = set(resolve_toolset_names(task))
    assert resolved & with_browser, (
        f"UI task {task!r} got no browser tools"
    )


# --------------------------------------------------------------------------- #
# Cache-stability contract (Hermes Law #1): within one task the resolved set  #
# is byte-identical turn over turn — same inputs -> same ordered output.      #
# --------------------------------------------------------------------------- #
def test_resolver_is_deterministic_per_task():
    task = "implement a REST endpoint for user signup"
    first = resolve_toolset_names(task)
    second = resolve_toolset_names(task)
    assert first == second, "resolver is non-deterministic — prompt cache cannot hold"


def test_resolver_order_is_stable():
    # Order matters for a byte-stable tools block; it must not shuffle.
    task = "build a web app"
    a = resolve_toolset_names(task)
    b = resolve_toolset_names(task)
    assert a == b and list(a) == list(b)


# --------------------------------------------------------------------------- #
# Invariant: web toolset is on by default (ddgs is free/bundled) but opt-out. #
# --------------------------------------------------------------------------- #
def test_web_on_by_default(monkeypatch):
    monkeypatch.delenv("PULSEAI_WEB_TOOLS", raising=False)
    resolved = set(resolve_toolset_names("fix a bug"))
    assert {"web_search", "web_fetch"}.issubset(resolved)


def test_web_opt_out(monkeypatch):
    monkeypatch.setenv("PULSEAI_WEB_TOOLS", "off")
    resolved = set(resolve_toolset_names("fix a bug"))
    assert not (resolved & {"web_search", "web_fetch"})


# --------------------------------------------------------------------------- #
# Invariant: execution tasks get verification + process tools.                #
# --------------------------------------------------------------------------- #
def test_execution_task_gets_typecheck():
    resolved = set(resolve_toolset_names("implement the feature and build it"))
    assert "typecheck_workspace" in resolved


def test_pure_chat_drops_execution_tools():
    # A pure chat task neither writes code nor runs servers — the execution
    # set (typecheck, process control) should not ride along.
    resolved = set(resolve_toolset_names("hello, what can you do"))
    assert "typecheck_workspace" not in resolved
    assert "start_terminal" not in resolved


# --------------------------------------------------------------------------- #
# Invariant: the resolver only ever returns REAL tools — no phantom names the #
# registry cannot satisfy.                                                    #
# --------------------------------------------------------------------------- #
def test_no_phantom_tools():
    known = set(all_known_tool_names())
    for task in [
        "build a react app", "fix the bug", "explain the code", "",
    ]:
        resolved = set(resolve_toolset_names(task))
        assert resolved.issubset(known), (
            f"resolver returned unknown tool for {task!r}: {resolved - known}"
        )


def test_no_duplicates():
    for task in ["build a web app", "fix bug", ""]:
        resolved = resolve_toolset_names(task)
        assert len(resolved) == len(set(resolved)), (
            f"duplicate tools for {task!r}"
        )


# --------------------------------------------------------------------------- #
# Invariant: the gate is the win — a non-UI task resolves to STRICTLY FEWER    #
# tools than a UI task (the relationship, not a frozen number).               #
# --------------------------------------------------------------------------- #
def test_non_ui_is_strictly_smaller_than_ui(with_browser):
    non_ui = resolve_toolset_names("refactor the database layer")
    ui = resolve_toolset_names("build a react dashboard app")
    assert len(non_ui) < len(ui), (
        "gating failed: non-UI task did not resolve to fewer tools than UI"
    )
