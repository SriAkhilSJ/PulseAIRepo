from __future__ import annotations

import time

import pytest

from src.agents.subagent_lifecycle import SubagentLifecycleService


def test_child_cannot_broaden_parent_capabilities():
    service = SubagentLifecycleService(max_workers=1)
    with pytest.raises(ValueError, match="broaden"):
        service.launch(
            parent_session_id="p", goal="review",
            parent_capabilities=("workspace_read",),
            allowed_capabilities=("workspace_read", "execution"),
        )


def test_managed_launch_status_wait_result(monkeypatch):
    class FakeCoordinator:
        def spawn(self, **kwargs):
            return "child"
        def get_result(self, _agent_id):
            return "review complete"
    monkeypatch.setattr("src.agents.sub_agent.subagent_coordinator", FakeCoordinator())
    service = SubagentLifecycleService(max_workers=1)
    handle = service.launch(
        parent_session_id="p", goal="review auth",
        parent_capabilities=("workspace_read",),
        allowed_capabilities=("workspace_read",), mode="review",
    )
    result = service.wait(handle, timeout=2)
    assert result["state"] == "succeeded"
    assert result["result"] == "review complete"
    assert result["ready"] is True


def test_handle_capability_prevents_forgery():
    from dataclasses import replace
    service = SubagentLifecycleService(max_workers=1)
    handle = service.launch(parent_session_id="p", goal="review", mode="review")
    forged = replace(handle, capability_token="0" * 64)
    assert service.status(forged)["state"] == "unknown"
