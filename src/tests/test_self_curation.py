"""D38 self-curation background loop: digest, parse, gating.

Tests the pure units (digest builder, JSON parser, interval gate, in-flight
guard) without any live LLM call; the review thread itself is daemon +
bounded + never raises by construction.
"""

import threading

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.context import self_curation as sc


def _conv():
    return [
        SystemMessage(content="persona"),
        HumanMessage(content="I prefer type hints everywhere please"),
        AIMessage(content="Got it, will use type hints"),
        HumanMessage(content="not related"),
        ToolMessage(content="big output " * 500, tool_call_id="c1"),
        HumanMessage(content="keep it terse"),
    ]


def test_digest_drops_system_and_tool_messages():
    out = sc._digest(_conv())
    assert "persona" not in out
    assert "big output" not in out
    assert "USER: I prefer type hints everywhere please" in out
    assert "ASSISTANT: Got it, will use type hints" in out
    assert "USER: keep it terse" in out


def test_digest_caps_length():
    msgs = [
        HumanMessage(content="x" * 6000),
        AIMessage(content="y" * 6000),
    ]
    out = sc._digest(msgs)
    assert len(out) <= sc._MAX_REVIEW_CHARS


def test_parse_preferences_json_object():
    raw = '{"preferences": ["prefers type hints", "wants terse replies"]}'
    assert sc._parse_preferences(raw) == ["prefers type hints", "wants terse replies"]


def test_parse_preferences_bare_list_and_fences():
    raw = '```json\n["one", "two"]\n```'
    assert sc._parse_preferences(raw) == ["one", "two"]


def test_parse_preferences_empty_and_garbage():
    assert sc._parse_preferences("") == []
    assert sc._parse_preferences('{"preferences": []}') == []
    assert sc._parse_preferences("not json at all") == []
    assert sc._parse_preferences("lines\n-   a bullet item here\n- b") == [
        "a bullet item here",
        "b",
    ]


def test_parse_preferences_bounded_and_deduped(monkeypatch):
    monkeypatch.setattr(sc, "_MAX_REVIEW_PREFS", 2)
    raw = '{"preferences": ["A", "A", "B", "C"]}'
    assert sc._parse_preferences(raw) == ["A", "B"]


def test_interval_gate(monkeypatch):
    monkeypatch.setenv("MEMORY_NUDGE_INTERVAL", "3")
    # Force a snapshot-free path: messages given -> no checkpointer access.
    calls = []

    def fake_spawn(tid, msgs):
        calls.append((tid, msgs))

    monkeypatch.setattr(sc, "_spawn", fake_spawn)
    monkeypatch.setattr(sc, "_in_flight", {})
    monkeypatch.setattr(sc, "_turn_counts", {})

    msgs = [HumanMessage(content="hi")]
    with threading.Lock():
        sc.maybe_spawn_memory_review("t", msgs)
        assert not calls, "turn 1 of 3 must not fire"
        sc.maybe_spawn_memory_review("t", msgs)
        assert not calls, "turn 2 of 3 must not fire"
        sc.maybe_spawn_memory_review("t", msgs)
        assert len(calls) == 1, "turn 3 of 3 must fire"


def test_interval_zero_disables(monkeypatch):
    monkeypatch.setenv("MEMORY_NUDGE_INTERVAL", "0")
    fired = []

    def fake_spawn(tid, msgs):
        fired.append(tid)

    monkeypatch.setattr(sc, "_spawn", fake_spawn)
    sc.maybe_spawn_memory_review("t", [HumanMessage(content="hi")], force=True)
    assert not fired


def test_in_flight_guard_blocks_second_fire(monkeypatch):
    monkeypatch.setenv("MEMORY_NUDGE_INTERVAL", "1")
    monkeypatch.setattr(sc, "_turn_counts", {})
    fired = []

    def fake_spawn(tid, msgs):
        fired.append(tid)

    monkeypatch.setattr(sc, "_spawn", fake_spawn)
    sc.maybe_spawn_memory_review("t", [HumanMessage(content="a")], force=True)
    sc.maybe_spawn_memory_review("t", [HumanMessage(content="b")], force=True)
    assert len(fired) == 1, "second fire while in-flight must be blocked"

    # After the thread clears its marker (simulate by clearing), it may fire.
    with sc._in_flight_lock:
        sc._in_flight.pop("t", None)
    sc.maybe_spawn_memory_review("t", [HumanMessage(content="c")], force=True)
    assert len(fired) == 2


def test_digest_and_parse_never_raise_on_garbage():
    assert sc._digest(None) == ""
    assert sc._digest("nope") == ""
    assert sc._parse_preferences(None) == []
    assert sc._parse_preferences({"x": 1}) == []