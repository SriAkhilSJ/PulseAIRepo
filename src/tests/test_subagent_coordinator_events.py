"""Visibility contract for the coordinator spawn path (founder
2026-10-15: batch Delegate card rows were dead — 'no use').

delegate_to_subagent_batch runs its children through
SubAgentCoordinator.spawn_batch, which historically registered each
child only AFTER it finished and never emitted the subagent.updated
bus event the lifecycle emits. The desktop therefore never learned
batch children existed while they ran, so the batch card had no
child sessions to navigate to. spawn() now announces running ->
succeeded/failed (payload mirroring subagent_lifecycle._emit), and
the lifecycle passes emit_events=False so its children never
double-speak.

invoke_agent is faked everywhere — no LLM, no graph.
"""

from __future__ import annotations

import pytest

from src.agents.sub_agent import SubAgentCoordinator
from src.dashboard.event_bus import event_bus


def _fake_invoke_factory(behavior):
    def fake(message, thread_id="default", provider=None, model=None,
             workspace=".", execution_mode="agent"):
        return behavior(thread_id, message)
    return fake


@pytest.fixture()
def captured(monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(event_bus, "emit",
                        lambda kind, payload: events.append((kind, payload)))
    return events


def _subagent_events(captured):
    return [p for kind, p in captured if kind == "subagent.updated"]


def test_spawn_announces_running_then_succeeded(monkeypatch, captured):
    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(lambda tid, msg: f"done:{tid}"))
    coord = SubAgentCoordinator()
    agent_id = coord.spawn("research", "Research bubble sort complexity",
                           "parent-thread")

    events = _subagent_events(captured)
    assert [e["state"] for e in events] == ["running", "succeeded"]
    first = events[0]
    assert first["subagent_id"] == agent_id
    assert first["child_thread_id"] == agent_id
    assert first["parent_session_id"] == "parent-thread"
    assert first["goal"].startswith("Research bubble sort")
    assert events[1]["result"].startswith("done:")


def test_spawn_batch_announces_every_child(monkeypatch, captured):
    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(lambda tid, msg: f"done:{tid}"))
    coord = SubAgentCoordinator()
    ids = coord.spawn_batch("code", ["Write benchmark script", "Write docs"],
                            "parent-thread")

    events = _subagent_events(captured)
    running = {e["subagent_id"] for e in events if e["state"] == "running"}
    settled = {e["subagent_id"] for e in events if e["state"] == "succeeded"}
    assert running == set(ids)
    assert settled == set(ids)


def test_emit_events_false_stays_silent(monkeypatch, captured):
    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(lambda tid, msg: "done"))
    coord = SubAgentCoordinator()
    coord.spawn("review", "Review the diff", "parent-thread",
                emit_events=False)
    assert _subagent_events(captured) == []


def test_crashed_child_announces_failed(monkeypatch, captured):
    def boom(tid, msg):
        raise RuntimeError("provider down")

    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(boom))
    coord = SubAgentCoordinator()
    coord.spawn("test", "Run the suite", "parent-thread")

    events = _subagent_events(captured)
    assert [e["state"] for e in events] == ["running", "failed"]
    assert "provider down" in (events[1]["error"] or "")


def test_spawn_runs_on_the_callers_thread_id(monkeypatch, captured):
    """Pipeline identity (OpenCode: one session id everywhere): when
    the lifecycle mints the child's session id, the child must RUN on
    that id — its checkpoint is what the desktop reads on open."""
    seen = {}

    def behavior(tid, msg):
        seen["thread_id"] = tid
        return "done"

    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(behavior))
    coord = SubAgentCoordinator()
    agent_id = coord.spawn("code", "Write the benchmark", "parent-thread",
                           agent_id="sub-code-fixed01")
    assert agent_id == "sub-code-fixed01"
    assert seen["thread_id"] == "sub-code-fixed01"
    events = _subagent_events(captured)
    assert {e["subagent_id"] for e in events} == {"sub-code-fixed01"}


def test_spawn_creates_durable_session_row_with_workspace(monkeypatch, captured):
    """Children are first-class session rows (OpenCode parentID):
    with a workspace known, spawn upserts the durable row the
    session list / resume resolve through."""
    created = []

    class FakeSessionStore:
        def get_session(self, sid):
            return None

        def create_session(self, sid, workspace, **kwargs):
            created.append((sid, workspace, kwargs))
            return {"id": sid}

    monkeypatch.setattr("src.runtime.session_store.get_session_store",
                        lambda: FakeSessionStore())
    monkeypatch.setattr("src.runtime.session_titling.shorten_title",
                        lambda text: "Research bubble sort")
    monkeypatch.setattr("src.runtime.session_titling.ensure_unique_title",
                        lambda store, workspace, title: title)
    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(lambda tid, msg: "done"))
    coord = SubAgentCoordinator()
    agent_id = coord.spawn("research", "Research bubble sort complexity",
                           "parent-thread", workspace="/ws/testCRUSOR")
    assert len(created) == 1
    sid, workspace, kwargs = created[0]
    assert sid == agent_id
    assert workspace == "/ws/testCRUSOR"
    assert kwargs["parent_session_id"] == "parent-thread"
    assert kwargs["title"] == "Research bubble sort"


def test_no_durable_row_without_workspace(monkeypatch, captured):
    created = []

    class FakeSessionStore:
        def get_session(self, sid):
            return None

        def create_session(self, sid, workspace, **kwargs):
            created.append(sid)
            return {"id": sid}

    monkeypatch.setattr("src.runtime.session_store.get_session_store",
                        lambda: FakeSessionStore())
    monkeypatch.setattr("src.graphs.chat_graph.invoke_agent",
                        _fake_invoke_factory(lambda tid, msg: "done"))
    coord = SubAgentCoordinator()
    coord.spawn("research", "Research something", "parent-thread")
    assert created == []
