"""Per-turn card identity: journal -> session_messages -> renderer hydration.

Deterministic and provider-free. Covers the bridge half of the contract:

* every projected message is stamped with the turn whose prompt produced it
  (journal ``turn.started`` request hash, with a safe legacy ordinal fallback);
* cards are deduplicated by ``(session, turn, card id)`` — never by card id
  alone — so two turns with the same card id cannot overwrite each other;
* replay of one identity updates in place and preserves order.

The renderer half (CrusorCardStore) is covered by ``scripts/test_crusorai_cards.mjs``
and the real Electron acceptance.
"""
from __future__ import annotations

import hashlib
import inspect

from src.bridge.__main__ import BridgeServer


def _message(role: str, content: str, **extra) -> dict:
    entry = {"role": role, "content": content}
    entry.update(extra)
    return entry


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _card(turn_id: str, card_id: str, label: str, *, card_type: str = "activity", session: str = "s-1") -> dict:
    return {
        "schema_version": 1,
        "card_type": card_type,
        "card_id": card_id,
        "session_id": session,
        "turn_id": turn_id,
        "data": {"label": label, "status": "running"},
    }


def _card_event(turn_id: str, card: dict, *, session: str = "s-1", event_type: str = "agent_card") -> dict:
    return {
        "type": event_type,
        "session_id": session,
        "turn_id": turn_id,
        "payload": {"card": card},
    }


# ---------------------------------------------------------------------------
# Message -> turn identity
# ---------------------------------------------------------------------------

def test_message_turn_ids_follow_request_hashes() -> None:
    projected = [
        _message("user", "prompt one"),
        _message("assistant", "answer one"),
        _message("tool", "result one"),
        _message("user", "prompt two"),
        _message("assistant", "answer two"),
    ]
    rows = [(_digest("prompt one"), "turn-1"), (_digest("prompt two"), "turn-2")]

    BridgeServer._assign_transcript_turn_ids(projected, rows)

    assert [entry.get("turn_id") for entry in projected] == [
        "turn-1", "turn-1", "turn-1", "turn-2", "turn-2",
    ]


def test_unmatched_user_message_inherits_the_open_turn() -> None:
    projected = [
        _message("user", "prompt one"),
        _message("assistant", "answer one"),
        _message("user", "a steer inside the same turn"),
        _message("assistant", "answer two"),
    ]
    rows = [(_digest("prompt one"), "turn-1")]

    BridgeServer._assign_transcript_turn_ids(projected, rows)

    assert [entry.get("turn_id") for entry in projected] == ["turn-1"] * 4


def test_identical_prompts_map_to_distinct_turns_in_order() -> None:
    projected = [
        _message("user", "same prompt"),
        _message("assistant", "first"),
        _message("user", "same prompt"),
        _message("assistant", "second"),
    ]
    rows = [(_digest("same prompt"), "turn-1"), (_digest("same prompt"), "turn-2")]

    BridgeServer._assign_transcript_turn_ids(projected, rows)

    assert [entry.get("turn_id") for entry in projected] == [
        "turn-1", "turn-1", "turn-2", "turn-2",
    ]


def test_legacy_ordinal_fallback_only_when_counts_match() -> None:
    projected = [
        _message("user", "one"), _message("assistant", "a"),
        _message("user", "two"), _message("assistant", "b"),
    ]
    rows = [("unmatched-a", "turn-1"), ("unmatched-b", "turn-2")]

    BridgeServer._assign_transcript_turn_ids(projected, rows)
    assert [entry.get("turn_id") for entry in projected] == [
        "turn-1", "turn-1", "turn-2", "turn-2",
    ]

    longer = [
        _message("user", "one"), _message("assistant", "a"),
        _message("user", "two"), _message("assistant", "b"),
        _message("user", "three"), _message("assistant", "c"),
    ]
    BridgeServer._assign_transcript_turn_ids(longer, rows)
    assert all("turn_id" not in entry for entry in longer)


def test_no_turn_rows_leaves_messages_unstamped() -> None:
    projected = [_message("user", "one"), _message("assistant", "a")]

    BridgeServer._assign_transcript_turn_ids(projected, [])

    assert all("turn_id" not in entry for entry in projected)


def test_turn_rows_read_only_turn_started_request_hashes() -> None:
    events = [
        {"type": "turn.started", "turn_id": "turn-1", "payload": {"request": {"sha256": "aaa"}}},
        {"type": "agent_card", "turn_id": "turn-1", "payload": {}},
        {"type": "turn.started", "turn_id": "turn-2", "payload": {"request": {}}},
        {"type": "turn.started", "turn_id": "turn-3", "payload": {"request": {"sha256": ""}}},
    ]

    assert BridgeServer._turn_request_rows(events) == [
        ("aaa", "turn-1"), ("", "turn-2"), ("", "turn-3"),
    ]


def test_journal_pagination_reads_every_page() -> None:
    class _Journal:
        def __init__(self) -> None:
            self.after: list[int] = []

        def list_events(self, session_id: str, *, after_seq: int = 0, limit: int = 2000) -> list[dict]:
            self.after.append(after_seq)
            if after_seq == 0:
                return [{"seq": 1}, {"seq": 2}]
            if after_seq == 2:
                return [{"seq": 3}]
            return []

    journal = _Journal()
    events = BridgeServer._journal_events(journal, "s-1", page=2)

    assert [event["seq"] for event in events] == [1, 2, 3]
    assert journal.after == [0, 2]


# ---------------------------------------------------------------------------
# Card -> (session, turn, card id)
# ---------------------------------------------------------------------------

def test_cards_are_keyed_by_full_identity_not_card_id_alone() -> None:
    events = [
        _card_event("turn-1", _card("turn-1", "shared:activity", "turn one")),
        _card_event("turn-2", _card("turn-2", "shared:activity", "turn two")),
    ]

    cards = BridgeServer._latest_agent_cards(events, "s-1")

    assert [(card["turn_id"], card["card_id"], card["data"]["label"]) for card in cards] == [
        ("turn-1", "shared:activity", "turn one"),
        ("turn-2", "shared:activity", "turn two"),
    ]


def test_card_replay_updates_in_place_and_preserves_order() -> None:
    first = _card_event("turn-1", _card("turn-1", "shared:activity", "starting"))
    second = _card_event("turn-2", _card("turn-2", "shared:activity", "second turn"))
    update = _card_event("turn-1", _card("turn-1", "shared:activity", "finished"))

    cards = BridgeServer._latest_agent_cards([first, second, update], "s-1")

    assert [(card["turn_id"], card["data"]["label"]) for card in cards] == [
        ("turn-1", "finished"),
        ("turn-2", "second turn"),
    ]


def test_cards_from_another_session_are_not_returned() -> None:
    events = [
        _card_event("turn-1", _card("turn-1", "shared:activity", "mine", session="s-1")),
        _card_event("turn-1", _card("turn-1", "shared:activity", "foreign", session="s-2"), session="s-2"),
    ]

    cards = BridgeServer._latest_agent_cards(events, "s-1")

    assert [(card["session_id"], card["data"]["label"]) for card in cards] == [("s-1", "mine")]


def test_duplicate_replay_never_duplicates_cards() -> None:
    event = _card_event("turn-1", _card("turn-1", "shared:activity", "one"))

    cards = BridgeServer._latest_agent_cards([event, dict(event), dict(event)], "s-1")

    assert len(cards) == 1
    assert cards[0]["card_id"] == "shared:activity"


def test_session_messages_stamps_cards_and_messages_with_turns(monkeypatch) -> None:
    """The handler returns per-turn cards and turn-stamped messages together."""

    class _Store:
        def resolve_tip(self, sid: str) -> str:
            return sid

    class _Journal:
        def list_events(self, session_id: str, *, after_seq: int = 0, limit: int = 500) -> list[dict]:
            assert session_id == "s-1"
            assert limit == 2000
            return [
                {"type": "turn.started", "turn_id": "turn-1",
                 "payload": {"request": {"sha256": _digest("prompt one")}}},
                {"type": "turn.started", "turn_id": "turn-2",
                 "payload": {"request": {"sha256": _digest("prompt two")}}},
                _card_event("turn-1", _card("turn-1", "turn-1:activity", "one")),
                _card_event("turn-2", _card("turn-2", "turn-2:activity", "two")),
            ]

    messages = [
        _message("user", "prompt one"),
        _message("assistant", "answer one"),
        _message("user", "prompt two"),
        _message("assistant", "answer two"),
    ]

    server = object.__new__(BridgeServer)
    emitted: list[dict] = []
    server.emit = emitted.append  # type: ignore[method-assign]
    server._durable_store = lambda: _Store()  # type: ignore[method-assign]
    server._delegate_tip = lambda sid, tip: tip  # type: ignore[method-assign]

    def _transcript(sid, *, limit, offset, order, turn_rows=None):  # noqa: ANN001
        returned = [dict(entry) for entry in messages]
        BridgeServer._assign_transcript_turn_ids(returned, turn_rows or [])
        return returned, {
            "limit": limit, "offset": offset, "order": order,
            "returned": 4, "total": 4, "has_more": False,
        }

    server._transcript_messages = _transcript  # type: ignore[method-assign]

    import src.runtime.factory as runtime_factory
    monkeypatch.setattr(runtime_factory, "get_runtime_services", lambda: type("S", (), {"journal": _Journal()})())

    handled = BridgeServer._handle_session_meta(
        server, "session_messages", "s-1", {"limit": 120, "offset": 0, "order": "latest"}, "ws-1",
    )

    assert handled is True
    frame = emitted[-1]
    assert frame["type"] == "session_messages"
    assert [entry.get("turn_id") for entry in frame["messages"]] == [
        "turn-1", "turn-1", "turn-2", "turn-2",
    ]
    assert [(card["turn_id"], card["card_id"]) for card in frame["cards"]] == [
        ("turn-1", "turn-1:activity"),
        ("turn-2", "turn-2:activity"),
    ]


def test_session_messages_source_uses_full_identity_helper() -> None:
    source = inspect.getsource(BridgeServer._handle_session_meta)

    assert "_latest_agent_cards(" in source
    assert "_journal_events(" in source
    assert "latest[card[\"card_id\"]]" not in source
