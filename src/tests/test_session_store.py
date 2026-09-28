"""CrusorSessionStore — durable session rows (Hermes desktop pipeline port)."""
from __future__ import annotations


from src.runtime.session_store import (
    CrusorSessionStore,
    derive_title_from_text,
    sanitize_title,
)


def test_sanitize_title_collapses_and_caps():
    assert sanitize_title("  hello   world\nnew ") == "hello world new"
    assert sanitize_title(None) == ""
    long_title = "x" * 500
    assert len(sanitize_title(long_title)) <= 200


def test_derive_title_from_first_message():
    assert derive_title_from_text("  Fix   the login   bug ") == "Fix the login bug"
    assert derive_title_from_text("") == ""
    assert derive_title_from_text("x" * 200).endswith("…")


def test_create_and_get_roundtrip(tmp_path):
    store = CrusorSessionStore(tmp_path / "sessions.db")
    try:
        row = store.create_session("s1", str(tmp_path), title="Hello", model="m1")
        assert row["id"] == "s1"
        assert row["title"] == "Hello"
        assert row["lineage_root_id"] == "s1"
        fetched = store.get_session("s1")
        assert fetched is not None and fetched["workspace"] == str(tmp_path)
    finally:
        store.close()


def test_upsert_never_overwrites_set_fields(tmp_path):
    store = CrusorSessionStore(tmp_path / "sessions.db")
    try:
        store.create_session("s1", "/ws", title="First", model="m1")
        row = store.create_session("s1", "/other", title="Second", model="m2")
        assert row["workspace"] == "/ws"
        assert row["title"] == "First"
        assert row["model"] == "m1"
    finally:
        store.close()


def test_invalid_id_rejected(tmp_path):
    store = CrusorSessionStore(tmp_path / "sessions.db")
    try:
        for bad in ("", "  ", "a/b", "a\nb", "../x"):
            try:
                store.create_session(bad, "/ws")
            except ValueError:
                continue
            raise AssertionError(f"expected ValueError for {bad!r}")
    finally:
        store.close()


def test_list_order_and_archived_filter(tmp_path):
    store = CrusorSessionStore(tmp_path / "sessions.db")
    try:
        store.create_session("old", "/ws", title="old")
        store.create_session("new", "/ws", title="new")
        store.touch_activity("old")
        # recent order: touched row first
        rows = store.list_sessions_rich(order="recent")
        assert [r["id"] for r in rows[:2]] == ["old", "new"] or rows[0]["id"] == "old"
        store.set_archived("old", True)
        assert all(r["id"] != "old" for r in store.list_sessions_rich(archived="exclude"))
        assert any(r["id"] == "old" for r in store.list_sessions_rich(archived="only"))
        assert any(r["id"] == "old" for r in store.list_sessions_rich(archived="include"))
    finally:
        store.close()


def test_pinned_backfill_past_window(tmp_path):
    store = CrusorSessionStore(tmp_path / "sessions.db")
    try:
        for i in range(5):
            store.create_session(f"s{i}", "/ws", title=f"t{i}")
            store.touch_activity(f"s{i}")
        store.set_pinned("s0", True)
        # Window of 2 would exclude s0 by recency; the pin back-fills it.
        rows = store.list_sessions_rich(limit=2)
        ids = [r["id"] for r in rows]
        assert "s0" in ids
        assert len(rows) >= 3
    finally:
        store.close()


def test_search_and_min_messages(tmp_path):
    store = CrusorSessionStore(tmp_path / "sessions.db")
    try:
        store.create_session("a", "/ws", title="login bug")
        store.create_session("b", "/ws", title="signup flow")
        store.touch_activity("a", message_count=5)
        assert [r["id"] for r in store.list_sessions_rich(search_query="login")] == ["a"]
        assert [r["id"] for r in store.list_sessions_rich(min_messages=3)] == ["a"]
    finally:
        store.close()


def test_fork_lineage_and_tip(tmp_path):
    store = CrusorSessionStore(tmp_path / "sessions.db")
    try:
        store.create_session("parent", "/ws", title="p")
        store.create_session("child", "/ws", title="p fork", parent_session_id="parent")
        child = store.get_session("child")
        assert child is not None and child["lineage_root_id"] == "parent"
        assert store.resolve_tip("parent") in {"parent", "child"}
        store.touch_activity("child")
        assert store.resolve_tip("parent") == "child"
        assert store.session_matches_stored_id(child, "parent")
    finally:
        store.close()


def test_flags_and_unread(tmp_path):
    store = CrusorSessionStore(tmp_path / "sessions.db")
    try:
        store.create_session("s", "/ws")
        store.set_pinned("s", True)
        store.set_hidden("s", True)
        store.set_read("s", read=False)
        row = store.get_session("s")
        assert row is not None and row["pinned"] is True
        assert row["hidden"] is True and row["unread"] is True
        store.set_read("s", read=True)
        assert store.get_session("s")["unread"] is False
    finally:
        store.close()


def test_delete_removes_row(tmp_path):
    store = CrusorSessionStore(tmp_path / "sessions.db")
    try:
        store.create_session("s", "/ws")
        assert store.delete_session("s") is True
        assert store.get_session("s") is None
        assert store.delete_session("s") is False
    finally:
        store.close()
