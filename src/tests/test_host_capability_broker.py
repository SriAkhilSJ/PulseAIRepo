"""Provider-free contracts for the native Code OSS capability broker."""
from __future__ import annotations

import threading

import pytest

from src.runtime.host_capabilities import HostCapabilityBroker, HostCapabilityError


def _descriptors():
    return [
        {"id": "diagnostics.markers", "availability": "available", "risk": "read", "provider": "markerService"},
        {"id": "search.workspace", "availability": "blocked", "risk": "read", "provider": "searchService"},
        {"id": "terminal.native", "availability": "available", "risk": "execute", "provider": "terminalService"},
    ]


def test_discovery_only_accepts_the_read_only_allowlist():
    broker = HostCapabilityBroker()
    assert broker.update("s", "/workspace", _descriptors()) == 2
    found = broker.discover("s")
    assert [item["id"] for item in found] == ["diagnostics.markers", "search.workspace"]
    assert all(item["risk"] == "read" for item in found)
    assert broker.discover("s", "marker") == [found[0]]


def test_update_rejects_session_workspace_switch():
    broker = HostCapabilityBroker()
    broker.update("s", "/one", _descriptors())
    with pytest.raises(HostCapabilityError, match="workspace changed"):
        broker.update("s", "/two", _descriptors())


def test_request_round_trip_is_bounded_and_correlated():
    from src.runtime.turn_control import turn_controls
    turn_controls.reset("s")
    turn_controls.begin("s")
    broker = HostCapabilityBroker()
    broker.update("s", "/workspace", _descriptors())
    emitted = []

    def emit(frame):
        emitted.append(frame)
        threading.Timer(0.01, lambda: broker.resolve(frame["request_id"], {
            "session_id": "s", "workspace": "/workspace",
            "status": "ok", "result": [{"message": "broken"}], "duration_ms": 7,
        })).start()

    broker.set_emitter(emit)
    receipt = broker.request(
        session_id="s", workspace="/workspace",
        capability_id="diagnostics.markers", arguments={}, timeout=1,
    )
    assert receipt["result"] == [{"message": "broken"}]
    assert receipt["duration_ms"] == 7
    assert emitted[0]["type"] == "host_tool_request"
    assert emitted[0]["capability_id"] == "diagnostics.markers"
    turn_controls.end("s")
    turn_controls.reset("s")


def test_inflight_host_request_is_released_by_session_cancel():
    from src.runtime.turn_control import turn_controls
    turn_controls.reset("cancel-host")
    turn_controls.begin("cancel-host")
    broker = HostCapabilityBroker()
    broker.update("cancel-host", "/workspace", _descriptors())
    emitted = threading.Event()
    broker.set_emitter(lambda _frame: emitted.set())
    errors = []

    def request():
        try:
            broker.request(
                session_id="cancel-host", workspace="/workspace",
                capability_id="diagnostics.markers", arguments={}, timeout=10,
            )
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=request)
    worker.start()
    assert emitted.wait(1)
    assert turn_controls.cancel("cancel-host") is True
    worker.join(1)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert "cancelled by user" in str(errors[0])
    turn_controls.reset("cancel-host")


def test_request_denies_unavailable_mutating_and_wrong_workspace_capabilities():
    broker = HostCapabilityBroker()
    broker.update("s", "/workspace", _descriptors())
    with pytest.raises(HostCapabilityError, match="blocked"):
        broker.request(session_id="s", workspace="/workspace", capability_id="search.workspace", arguments={})
    with pytest.raises(HostCapabilityError, match="not published"):
        broker.request(session_id="s", workspace="/workspace", capability_id="terminal.native", arguments={})
    with pytest.raises(HostCapabilityError, match="workspace"):
        broker.request(session_id="s", workspace="/other", capability_id="diagnostics.markers", arguments={})
    broker.set_emitter(lambda _frame: None)
    with pytest.raises(HostCapabilityError, match="arguments exceeded"):
        broker.request(
            session_id="s", workspace="/workspace",
            capability_id="diagnostics.markers", arguments={"query": "x" * 20_000},
        )
