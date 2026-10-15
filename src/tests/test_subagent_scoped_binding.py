"""Sub-agent children bind a strictly-scoped tool waist (cost, 2026-10-15).

field cost investigation: every model call (parent + each child) re-sent
all ~68 registered tool schemas. The capability waist existed
(tools.toolsets.resolve_runtime_tool_names) and the profile resolver
already honored scope_capabilities_strict, but the binder ignored both,
and child scopes collapsed to () because the delegate's mode map named
TOOLS while KNOWN_CAPABILITIES names coarse capabilities. These pins keep
the whole chain honest: mode -> coarse caps -> strict binder -> waist.
"""

from __future__ import annotations

from src.graphs import chat_graph
from src.agents.runtime_profile import KNOWN_CAPABILITIES
from src.agents.subagent_permissions import default_capabilities_for_mode


def _state():
    return {
        "current_task": "delegate work",
        "plan": [],
        "execution_trace": [],
        "iteration_used": 0,
    }


def _config(tmp_path, scope=None):
    cfg = {"workspace": str(tmp_path)}
    if scope is not None:
        cfg["scope_capabilities"] = list(scope)
        cfg["scope_capabilities_strict"] = True
    return {"configurable": cfg}


def test_mode_scopes_speak_coarse_capabilities():
    for mode in ("research", "code", "test", "review", "general", ""):
        caps = default_capabilities_for_mode(mode)
        assert caps, mode
        assert set(caps) <= KNOWN_CAPABILITIES, (mode, caps)
    research = default_capabilities_for_mode("research")
    assert "research" in research and "workspace_read" in research
    assert "workspace_write" not in research
    code = default_capabilities_for_mode("code")
    assert {"workspace_read", "workspace_write", "execution"} <= set(code)


def test_child_binds_strict_waist_not_full_registry(tmp_path):
    names = [t.name for t in chat_graph._resolve_bound_tools(
        _state(), _config(tmp_path, ("research", "workspace_read")))]
    # Waist holds: research + read surface present...
    assert "web_search" in names and "read_file" in names
    # ...everything outside the scope is unbound (no schema bill for it)
    assert "write_file" not in names
    assert "edit_file" not in names
    assert "terminal" not in names
    assert len(names) <= 30, names  # ~61% fewer than the 67-tool full bind


def test_code_child_binds_write_and_execution(tmp_path):
    names = [t.name for t in chat_graph._resolve_bound_tools(
        _state(), _config(tmp_path, default_capabilities_for_mode("code")))]
    assert "write_file" in names and "read_file" in names
    assert "web_search" not in names  # research is not in the code scope


def test_parent_bind_unchanged_without_strict_scope(tmp_path):
    names = [t.name for t in chat_graph._resolve_bound_tools(
        _state(), _config(tmp_path))]
    # The parent still gets the broad surface (waist-by-task is a
    # separate, later lever); strict scoping is child-only.
    assert len(names) > 40, len(names)
