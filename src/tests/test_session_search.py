"""Pins for session_search (D16, zero-LLM recall of past sessions).

Fixtures write REAL LangGraph SqliteSaver checkpoints (msgpack path
included) -- the index is tested against the storage it will meet in
production, not a mock of it.
"""

from __future__ import annotations

import inspect
import sqlite3

import pytest

import src.tools.session_search_tool as st
from src.context.session_index import SessionIndex


def _seed_checkpoint_db(path, threads: dict[str, list], day: int = 1):
    """Write each thread's final checkpoint via a REAL SqliteSaver."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(str(path))
    saver = SqliteSaver(conn)
    saver.setup()
    for tid, msgs in threads.items():
        cp = {
            "v": 1,
            "ts": f"2026-08-0{day}T10:00:00+00:00",
            "id": f"{day}-{tid}",
            "channel_values": {"messages": msgs},
            "channel_versions": {},
            "versions_seen": {},
        }
        saver.put(
            {"configurable": {"thread_id": tid, "checkpoint_ns": "", "checkpoint_id": None}},
            cp,
            {"source": "loop", "step": 1},
            {},
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def index(tmp_path):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    ckpt = tmp_path / "sessions.db"
    _seed_checkpoint_db(ckpt, {
        "alpha-login": [
            SystemMessage(content="SENTINEL-PERSONA you are a coding agent"),
            HumanMessage(content="how do we fix the login timeout bug?"),
            AIMessage(content="The login timeout is in auth.py line 42."),
            ToolMessage(content="SENTINEL-TOOLDUMP grep results ...", tool_call_id="t1"),
            HumanMessage(content="[CONTEXT SUMMARY]: zorptoken machine handoff"),
            AIMessage(content=[{"type": "text", "text": "also flushed the login cache afterwards"}]),
            AIMessage(content="Remember to refresh the token cache too."),
        ],
        "beta-dash": [
            HumanMessage(content="add a revenue chart to the dashboard"),
            AIMessage(content="Chart added with quarterly data."),
        ],
        "sub-searcher": [
            HumanMessage(content="subtask: investigate login flows"),
        ],
    }, day=3)
    idx = SessionIndex(str(ckpt), str(tmp_path / "index.db"))
    return idx


@pytest.fixture()
def call(index, monkeypatch):
    monkeypatch.setattr(st, "_index", index)

    def _invoke(**kwargs):
        kwargs.setdefault("config", {"configurable": {"workspace": ".", "thread_id": "current-thread"}})
        return st.session_search.invoke(kwargs, config=kwargs.pop("config"))

    return _invoke


# ------------------------------------------------------------- discovery
def test_discovery_card_shape(call):
    out = call(query="login timeout")
    assert "alpha-login" in out and "login timeout bug" in out
    assert "match:" in out and "session start:" in out and "session end:" in out
    assert 'scroll: session_id="alpha-login"' in out
    assert "beta-dash" not in out


def test_current_thread_excluded_from_discovery(index, monkeypatch):
    monkeypatch.setattr(st, "_index", index)
    out = st.session_search.invoke(
        {"query": "login timeout"},
        config={"configurable": {"workspace": ".", "thread_id": "alpha-login"}},
    )
    assert "No past sessions matched" in out


def test_subagent_demoted_when_interactive_matches(call):
    out = call(query="login")
    assert "alpha-login" in out
    assert "sub-searcher" not in out


def test_subagent_shown_only_when_only_match(call):
    out = call(query="subtask investigate")
    assert "sub-searcher" in out
    assert "sub-agent" in out and "Only sub-agent runs matched" in out


def test_compaction_payloads_never_indexed(call):
    assert "No past sessions matched" in call(query="zorptoken")


def test_system_and_tool_messages_not_indexed(call):
    assert "No past sessions matched" in call(query="SENTINEL-PERSONA")
    assert "No past sessions matched" in call(query="SENTINEL-TOOLDUMP")


def test_list_content_messages_are_flattened(call):
    assert "alpha-login" in call(query="flushed cache")


def test_query_wins_over_session_args_precedence(call):
    out = call(query="dashboard", session_id="alpha-login", around_message_id=0)
    assert out.startswith("Matches for 'dashboard'")


# ---------------------------------------------------------------- scroll
def test_scroll_windows_and_page_hints(call):
    out = call(session_id="alpha-login", around_message_id=2, window=1)
    assert "#1 " in out and "#2 " in out and "#3 " in out
    assert "#0 " not in out and "#4 " not in out
    assert "older: around_message_id=0" in out
    assert "newer:" not in out  # anchor 2 + radius 1 reaches the last message

    out = call(session_id="alpha-login", around_message_id=0, window=1)
    assert "#0 " in out and "#1 " in out and "#2 " not in out
    assert "newer: around_message_id=2" in out


def test_scroll_bad_anchor_is_friendly(call):
    assert "No messages found" in call(session_id="alpha-login", around_message_id=99)


# -------------------------------------------------------- browse/overview
def test_browse_recent_first_current_excluded(index, monkeypatch):
    monkeypatch.setattr(st, "_index", index)
    out = st.session_search.invoke(
        {}, config={"configurable": {"workspace": ".", "thread_id": "beta-dash"}}
    )
    assert "alpha-login" in out and "sub-searcher" in out
    assert "beta-dash" not in out
    assert "revenue chart" not in out or "beta" not in out.split("revenue chart")[0]


def test_overview_mode(call):
    out = call(session_id="beta-dash")
    assert "revenue chart" in out and "2 messages" in out
    assert "read the middle" in out


# --------------------------------------------------------------- hygiene
def test_long_messages_capped_in_scroll(call, index, tmp_path):
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.sqlite import SqliteSaver
    c = sqlite3.connect(str(tmp_path / "sessions.db"))
    saver = SqliteSaver(c)
    saver.put(
        {"configurable": {"thread_id": "gamma-long", "checkpoint_ns": "", "checkpoint_id": None}},
        {"v": 1, "ts": "2026-08-05T10:00:00+00:00", "id": "5-gamma",
         "channel_values": {"messages": [AIMessage(content="aha " * 2000)]},
         "channel_versions": {}, "versions_seen": {}},
        {"source": "loop", "step": 1}, {},
    )
    c.commit(); c.close()
    out = call(session_id="gamma-long", around_message_id=0, window=0)
    assert "…" in out and len(out) < 1_200


def test_incremental_sync_sees_new_checkpoint(call, index, tmp_path):
    call(query="login")  # first sync
    from langchain_core.messages import HumanMessage
    c = sqlite3.connect(str(tmp_path / "sessions.db"))
    from langgraph.checkpoint.sqlite import SqliteSaver
    saver = SqliteSaver(c)
    saver.put(
        {"configurable": {"thread_id": "alpha-login", "checkpoint_ns": "", "checkpoint_id": "3-alpha-login"}},
        {"v": 1, "ts": "2026-08-04T10:00:00+00:00", "id": "4-alpha-login",
         "channel_values": {"messages": [
             HumanMessage(content="the login timeout regressed again, reopening"),
         ]},
         "channel_versions": {}, "versions_seen": {}},
        {"source": "loop", "step": 2}, {},
    )
    c.commit(); c.close()
    assert "alpha-login" in call(query="regressed reopening")


def test_watermark_makes_unchanged_sync_free(index):
    assert index.sync()["reingested"] == 3
    assert index.sync()["reingested"] == 0  # stable watermark: no work


def test_missing_checkpoint_db_is_friendly(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_index", SessionIndex(
        str(tmp_path / "nope.db"), str(tmp_path / "idx.db")
    ))
    out = st.session_search.invoke(
        {}, config={"configurable": {"workspace": ".", "thread_id": "x"}}
    )
    assert "No past sessions yet" in out


def test_zero_llm_pure_search_source_pin():
    """The whole point of D16: recall must never spend a model call. If
    someone later adds 'LLM summaries' to the search path, this pin makes
    them argue with the ledger (hermes lesson #19434)."""
    import src.context.session_index as si
    for module in (si, st):
        src = inspect.getsource(module)
        assert "get_llm" not in src
        assert "llm.factory" not in src
        assert ".invoke_messages" not in src


def test_registry_twenty_tools():
    """Tool registry count. Renamed in spirit (§45): now 21 — D33 added
    delegate_to_subagent_batch; the name stays so history diffs loudly."""
    from src.graphs.chat_graph import tools
    assert len([t for t in tools]) == 21
    assert "session_search" in [t.name for t in tools]
    assert "delegate_to_subagent_batch" in [t.name for t in tools]
