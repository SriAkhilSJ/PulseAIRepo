"""Hermes desktop session pipeline over the Crusor stdio bridge.

Covers the full lifecycle through real bridge subprocesses (echo runner, so
zero provider traffic): lazy draft create -> first prompt persists the row ->
rich list -> rename / pin / archive -> paged messages -> fork lineage ->
resume tip -> delete. The durable store is redirected to a tmp file per test
via CRUSORAI_SESSIONS_DB so the real ~/.crusorai is untouched.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest

from src.bridge.protocol import PROTOCOL_VERSION


def send(proc, frame, timeout_s: float = 30.0):
    proc.stdin.write(json.dumps(frame) + "\n")
    proc.stdin.flush()
    deadline = time.monotonic() + timeout_s
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"no reply to {frame.get('type')}")
        line = proc.stdout.readline()
        assert line, "bridge closed stdout"
        reply = json.loads(line)
        if reply.get("type") not in {"workspace.bound", "llm.request"}:
            return reply


def drain_until(proc, types: set[str], timeout_s: float = 30.0):
    """Read frames until one of `types` arrives; return it."""
    deadline = time.monotonic() + timeout_s
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"never saw {types}")
        reply = json.loads(proc.stdout.readline())
        if reply.get("type") in types:
            return reply


@pytest.fixture
def pipeline_bridge(tmp_path):
    sessions_db = tmp_path / "sessions.db"
    env = dict(os.environ)
    env["CRUSORAI_BRIDGE_RUNNER"] = "echo"
    env["CRUSORAI_SESSIONS_DB"] = str(sessions_db)
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.bridge"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    try:
        assert send(proc, {"type": "hello", "protocol": PROTOCOL_VERSION})["type"] == "hello"
        yield proc, str(tmp_path), str(sessions_db)
    finally:
        try:
            proc.kill()
        except Exception:
            pass


def _row_ids(sessions_db: str) -> set[str]:
    conn = sqlite3.connect(sessions_db)
    try:
        rows = conn.execute("SELECT id FROM crusor_sessions").fetchall()
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()
    return {r[0] for r in rows}


def test_lazy_draft_create_persists_on_first_prompt(pipeline_bridge):
    proc, ws, sessions_db = pipeline_bridge
    created = send(proc, {"type": "session_create", "session_id": "draft-1", "workspace": ws})
    assert created["type"] == "session_info"
    assert created["session_id"] == "draft-1"
    assert created["stored_session_id"] == "draft-1"
    assert created["lazy"] is True
    # Hermes "no Untitled litter": an empty draft leaves no durable row.
    assert "draft-1" not in _row_ids(sessions_db)

    send(proc, {"type": "prompt", "session_id": "draft-1", "workspace": ws,
                "text": "Fix the login bug please"})
    done = drain_until(proc, {"turn_done", "turn_failed"})
    assert done["type"] == "turn_done"

    listed = send(proc, {"type": "session_list"})
    assert listed["type"] == "session_info"
    rows = {s.get("session_id") or s.get("id"): s for s in listed["sessions"]}
    assert "draft-1" in rows
    assert rows["draft-1"]["title"] == "Fix the login bug please"
    assert rows["draft-1"].get("lazy") is not True
    assert "draft-1" in _row_ids(sessions_db)


def test_seeded_create_persists_immediately(pipeline_bridge):
    proc, ws, sessions_db = pipeline_bridge
    created = send(proc, {
        "type": "session_create", "session_id": "seed-1", "workspace": ws,
        "title": "Seeded chat", "messages": [{"role": "user", "content": "hi"}],
    })
    assert created["lazy"] is False
    assert created["session"]["title"] == "Seeded chat"
    assert "seed-1" in _row_ids(sessions_db)


def test_rename_pin_archive_and_search(pipeline_bridge):
    proc, ws, _sessions_db = pipeline_bridge
    send(proc, {"type": "session_create", "session_id": "m-1", "workspace": ws})
    send(proc, {"type": "prompt", "session_id": "m-1", "workspace": ws, "text": "hello world"})
    assert drain_until(proc, {"turn_done", "turn_failed"})["type"] == "turn_done"

    renamed = send(proc, {"type": "session_rename", "session_id": "m-1", "title": "  My Title  "})
    assert renamed["renamed"] is True and renamed["title"] == "My Title"

    pinned = send(proc, {"type": "session_pin", "session_id": "m-1", "pinned": True})
    assert pinned["pinned"] is True and pinned["pin_updated"] is True

    found = send(proc, {"type": "session_list", "query": "My Title"})
    assert any((s.get("session_id") or s.get("id")) == "m-1" for s in found["sessions"])

    archived = send(proc, {"type": "session_archive", "session_id": "m-1", "archived": True})
    assert archived["archived"] is True
    excluded = send(proc, {"type": "session_list", "archived": "exclude"})
    assert all((s.get("session_id") or s.get("id")) != "m-1" for s in excluded["sessions"])
    only = send(proc, {"type": "session_list", "archived": "only"})
    assert any((s.get("session_id") or s.get("id")) == "m-1" for s in only["sessions"])


def test_session_messages_paging_shape(pipeline_bridge):
    proc, ws, _sessions_db = pipeline_bridge
    send(proc, {"type": "session_create", "session_id": "t-1", "workspace": ws})
    send(proc, {"type": "prompt", "session_id": "t-1", "workspace": ws, "text": "hi"})
    assert drain_until(proc, {"turn_done", "turn_failed"})["type"] == "turn_done"
    # Echo runner writes no checkpoints: the page is honestly empty but shaped.
    page = send(proc, {"type": "session_messages", "session_id": "t-1",
                       "limit": 120, "offset": 0, "order": "latest"})
    assert page["type"] == "session_messages"
    assert page["session_id"] == "t-1"
    assert page["messages"] == []
    assert page["pagination"]["order"] == "latest"
    assert page["pagination"]["limit"] == 120


def test_fork_links_lineage_and_resume_resolves_tip(pipeline_bridge):
    proc, ws, sessions_db = pipeline_bridge
    send(proc, {"type": "session_create", "session_id": "p-1", "workspace": ws})
    send(proc, {"type": "prompt", "session_id": "p-1", "workspace": ws, "text": "parent work"})
    assert drain_until(proc, {"turn_done", "turn_failed"})["type"] == "turn_done"

    forked = send(proc, {"type": "session_fork", "session_id": "p-1", "workspace": ws})
    assert forked["type"] == "session_info" and forked["forked_from"] == "p-1"
    child = forked["session_id"]
    assert child != "p-1"

    conn = sqlite3.connect(sessions_db)
    try:
        row = conn.execute(
            "SELECT parent_session_id, lineage_root_id, title FROM crusor_sessions WHERE id = ?",
            (child,)).fetchone()
    finally:
        conn.close()
    assert row is not None and row[0] == "p-1" and row[1] == "p-1"
    assert "fork" in (row[2] or "")

    resumed = send(proc, {"type": "session_resume", "session_id": "p-1", "workspace": ws})
    assert resumed["resumed"] is True
    assert resumed["resolved_session_id"] in {"p-1", child}


def test_delete_removes_row_and_emits_event(pipeline_bridge):
    proc, ws, sessions_db = pipeline_bridge
    send(proc, {"type": "session_create", "session_id": "d-1", "workspace": ws})
    send(proc, {"type": "prompt", "session_id": "d-1", "workspace": ws, "text": "bye"})
    assert drain_until(proc, {"turn_done", "turn_failed"})["type"] == "turn_done"
    assert "d-1" in _row_ids(sessions_db)

    deleted = send(proc, {"type": "session_delete", "session_id": "d-1"})
    assert deleted["type"] == "session_deleted"
    assert deleted["deleted"] is True
    assert "d-1" not in _row_ids(sessions_db)

    listed = send(proc, {"type": "session_list"})
    assert all((s.get("session_id") or s.get("id")) != "d-1" for s in listed["sessions"])


def test_session_meta_requires_id_and_no_phantom(pipeline_bridge):
    proc, _ws, _sessions_db = pipeline_bridge
    err = send(proc, {"type": "session_rename", "title": "x"})
    assert err["type"] == "error"
    # Unknown ids fail closed (no phantom in-memory entry minted).
    listed = send(proc, {"type": "session_list"})
    assert all((s.get("session_id") or s.get("id")) != "" for s in listed["sessions"])
