"""Degraded-memory resilience tests.

When the embedding backend is unavailable, chat_graph boots with
memory_manager=None (by design, same degrade pattern as the ContextEngine).
Every graph node / status endpoint must tolerate None — this suite proves it
for the sites a code review flagged (and two worse ones it missed).
"""

import pytest

import src.graphs.chat_graph as cg


@pytest.fixture
def degraded(monkeypatch):
    monkeypatch.setattr(cg, "memory_manager", None)
    return cg


def test_finalize_node_survives_degraded_memory(degraded):
    state = {
        "current_task": "ship feature",
        "steps_completed": ["created file"],
        "failed_steps": [],
        "plan": [{"id": 1, "description": "created file", "status": "completed"}],
        "messages": [],
        "recovery_attempts": 0,
        "replan_count": 0,
        "workspace": ".",
    }
    out = degraded.finalize_node(state)  # would AttributeError before the fix
    assert out, "finalize_node returned nothing"


def test_get_agent_status_survives_degraded_memory(degraded):
    status = degraded.get_agent_status("no-such-thread-xyz")
    assert isinstance(status, dict)


def test_export_analytics_survives_degraded_memory(degraded):
    analytics = degraded.export_session_analytics("no-such-thread-xyz")
    assert isinstance(analytics, dict)
    assert analytics["memories"] == 0
