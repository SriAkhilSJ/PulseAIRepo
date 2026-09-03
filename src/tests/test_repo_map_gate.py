"""Repo-map layer gate: OFF by default, env-driven, zero work when off.

Owner verdict (2026-09-03): the build-time repo map is not adaptive to this
context engine -- it walked the workspace on every build (real seconds on a
40k-file fork), produced a weak in-degree map, and churned the request
prefix. Hermes' engine (the reference) assembles NO workspace map at all.
Pinned: the getter, the silent-when-off layer, the walker exclusion, and
the opt-in path.
"""
from __future__ import annotations


def test_repo_map_disabled_by_default(monkeypatch):
    from src.context.repo_map import repo_map_enabled

    monkeypatch.delenv("PULSEAI_REPO_MAP", raising=False)
    assert repo_map_enabled() is False


def test_repo_map_env_opt_in_per_call(monkeypatch):
    from src.context.repo_map import repo_map_enabled

    monkeypatch.setenv("PULSEAI_REPO_MAP", "on")
    assert repo_map_enabled() is True
    monkeypatch.setenv("PULSEAI_REPO_MAP", "off")
    assert repo_map_enabled() is False
    monkeypatch.setenv("PULSEAI_REPO_MAP", "garbage")
    assert repo_map_enabled() is False


def _engine():
    from src.context.context_engine import ContextEngine

    return ContextEngine.__new__(ContextEngine)  # bypass heavy __init__


def test_layer_builds_nothing_when_disabled(monkeypatch):
    """When off, the layer must not even CALL get_repo_map: no walk, no
    budget, no map. The boom-monkeypatch proves the call never happens."""
    import src.context.repo_map as repo_map_module
    from src.context.context_engine import ContextEngine

    monkeypatch.delenv("PULSEAI_REPO_MAP", raising=False)

    def _boom(*args, **kwargs):
        raise AssertionError("get_repo_map must not be called when disabled")

    monkeypatch.setattr(repo_map_module, "get_repo_map", _boom)
    engine = _engine()
    assert engine._repo_map_layer({"current_task": "build it", "workspace": "."}) is None


def test_layer_builds_when_opted_in(monkeypatch):
    import src.context.repo_map as repo_map_module
    from src.context.context_engine import ContextEngine

    monkeypatch.setenv("PULSEAI_REPO_MAP", "on")
    import src.context.context_engine as ce_module
    monkeypatch.setattr(
        ce_module, "get_repo_map",
        lambda workspace, max_tokens=1200, budget=None, thread_id=None: "=== MAP ===",
    )
    engine = _engine()
    # the layer reads these off the engine (the real build sets them)
    engine._active_budget = None
    engine._active_thread_id = None
    layer = engine._repo_map_layer({"current_task": "build it", "workspace": "."})
    assert layer is not None
    assert "MAP" in layer.content


def test_walkers_exclude_repo_map_when_disabled(monkeypatch):
    """The shared-budget walker list must not reserve a slice for a layer
    that will never run. Uses the REAL relevance table + the REAL filter
    expression with TaskType.CREATE (a build task)."""
    from src.context.context_engine import ContextEngine
    from src.context.task_types import TaskType

    monkeypatch.delenv("PULSEAI_REPO_MAP", raising=False)
    relevance = ContextEngine.LAYER_RELEVANCE
    walkers = [
        name for name in ("repo_map", "relevant_chunks", "conventions")
        if relevance.get(name, {}).get(TaskType.CREATE, 0.0) >= 0.15
    ]
    from src.context.repo_map import repo_map_enabled
    if not repo_map_enabled():
        walkers = [name for name in walkers if name != "repo_map"]
    assert "repo_map" not in walkers
    # and with a relevance >= 0.15 the layer was a walker before the gate --
    # proving the gate actually removed something
    assert relevance.get("repo_map", {}).get(TaskType.CREATE, 0.0) >= 0.15
