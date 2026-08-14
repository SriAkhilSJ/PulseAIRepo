"""
session_search -- search PAST conversations with zero LLM cost
==============================================================

Single-shape tool, three modes inferred from args (no mode parameter --
hermes session_search_tool.py:1-46 shape, D16/§29):

    DISCOVERY  pass ``query``                          -> FTS5 over all past
    SCROLL     pass ``session_id`` + ``around_message_id``  sessions, top
    BROWSE     pass nothing                            sessions w/ bookends

OVERVIEW (``session_id`` only) returns a session's bookends + stats.

Everything here is SQLite + string formatting: no model calls, so recall
of "how did we fix X last week?" is free and lands in milliseconds.
"""

from datetime import datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.context.session_index import SessionIndex

_DISCOVERY_SESSIONS = 5
_BROWSE_SESSIONS = 10
_MSG_PREVIEW = 400
_RESULT_BUDGET = 8_000
_WINDOW_MAX = 20


def _plural(n) -> str:
    return f"{n} message{'s' if n != 1 else ''}"

_index = SessionIndex()  # module-level: watermark sync makes reuse cheap


def _fmt_ts(ts: str) -> str:
    """ISO checkpoint timestamp -> "August 01, 2026 at 10:00 AM"."""
    if not ts:
        return "unknown date"
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime(
            "%B %d, %Y at %I:%M %p"
        )
    except ValueError:
        return ts[:16]


def _preview(text: str, cap: int = _MSG_PREVIEW) -> str:
    text = " ".join(text.split())
    return text if len(text) <= cap else text[:cap] + "…"


def _clip(result: str) -> str:
    if len(result) <= _RESULT_BUDGET:
        return result
    return result[:_RESULT_BUDGET] + "\n… [result clipped; narrow the query]"


def _role_tag(role: str) -> str:
    return "U" if role == "user" else "A"


def _format_msgs(msgs: list[dict]) -> str:
    return " | ".join(f"{_role_tag(m['role'])}: {_preview(m['content'], 120)}" for m in msgs)


def _discovery(query: str, exclude_thread: str) -> str:
    hits = _index.fts_hits(query)
    if not hits:
        return f"No past sessions matched '{query}'."

    # First hit per thread wins (BM25 order), then split interactive vs
    # sub-agent. Lesson #19434: interactive matches ALWAYS win when both
    # match; sub-agent sessions surface only when nothing interactive did.
    order: list[str] = []
    best_hit: dict[str, dict] = {}
    for hit in hits:
        tid = hit["thread_id"]
        if tid == exclude_thread or tid in best_hit:
            continue
        best_hit[tid] = hit
        order.append(tid)
    metas = _index.sessions_for(order)

    interactive = [t for t in order if metas.get(t, {}).get("source") != "sub"]
    demoted = [t for t in order if metas.get(t, {}).get("source") == "sub"]
    chosen = (interactive or demoted)[:_DISCOVERY_SESSIONS]
    if not chosen:
        return f"No past sessions matched '{query}'."

    cards = []
    for n, tid in enumerate(chosen, 1):
        meta = metas[tid]
        hit = best_hit[tid]
        head, tail = _index.bookends(tid, 3)
        where = _index.message_by_id(hit["message_id"])
        center = where[1] if where else 0
        around = _index.window(tid, center, 2)
        label = " *(sub-agent run)*" if meta["source"] == "sub" else ""
        card = (
            f"[{n}] “{meta['title']}”{label}\n"
            f"    session {tid} — {_fmt_ts(meta['started_ts'])}, "
            f"{_plural(meta['msg_count'])}\n"
            f"    match: …{hit['snippet']}…\n"
            f"    around match: {_format_msgs(around)}\n"
            f"    session start: {_format_msgs(head)}"
        )
        # Bookend tail only when it shows messages the head didn't.
        head_ids = {m["idx"] for m in head}
        tail_new = [m for m in tail if m["idx"] not in head_ids]
        if tail_new:
            card += f"\n    session end: {_format_msgs(tail_new)}"
        card += f'\n    scroll: session_id="{tid}", around_message_id={center}'
        cards.append(card)

    note = ""
    if not interactive and demoted:
        note = "Only sub-agent runs matched (interactive sessions had no hits):\n\n"
    return _clip(note + f"Matches for '{query}' in past sessions:\n\n" + "\n\n".join(cards))


def _scroll(session_id: str, around_message_id: int, window: int) -> str:
    window = max(1, min(window, _WINDOW_MAX))
    msgs = _index.window(session_id, around_message_id, window)
    if not msgs:
        return (
            f"No messages found for session '{session_id}' around "
            f"message {around_message_id}. Check the ids from a discovery card."
        )
    lo, hi = msgs[0]["idx"], msgs[-1]["idx"]
    meta = _index.sessions_for([session_id]).get(session_id, {})
    total = meta.get("msg_count", "?")
    lines = [
        f"Session {session_id} — messages {lo}..{hi} of ~{total}:",
        "",
    ]
    for m in msgs:
        lines.append(f"#{m['idx']} {_role_tag(m['role'])}: {_preview(m['content'])}")
    hints = []
    if lo > 0:
        hints.append(f"older: around_message_id={max(0, lo - window)}")
    if isinstance(total, int) and hi < total - 1:
        hints.append(f"newer: around_message_id={hi + window}")
    if hints:
        lines.append(f"\n(scroll {' | '.join(hints)})")
    return _clip("\n".join(lines))


def _overview(session_id: str) -> str:
    meta = _index.sessions_for([session_id]).get(session_id)
    if meta is None:
        return f"No session found with id '{session_id}'."
    head, tail = _index.bookends(session_id, 3)
    out = (
        f"Session {session_id}\n"
        f"“{meta['title']}” — {_fmt_ts(meta['started_ts'])}, "
        f"{_plural(meta['msg_count'])} ({meta['source']})\n\n"
        f"start:\n{_format_msgs(head)}\n\nend:\n{_format_msgs(tail)}"
    )
    center = tail[-1]["idx"] if tail else 0
    return _clip(out + f'\n\n(read the middle: around_message_id={center})')


def _browse(exclude_thread: str) -> str:
    sessions = _index.recent_sessions(_BROWSE_SESSIONS, exclude_thread)
    if not sessions:
        return (
            "No past sessions yet. Sessions appear here automatically "
            "as conversations happen."
        )
    lines = [f"{len(sessions)} most recent past sessions:", ""]
    for n, s in enumerate(sessions, 1):
        label = " *(sub-agent)*" if s["source"] == "sub" else ""
        lines.append(
            f"[{n}] “{s['title']}”{label}\n"
            f"    {s['thread_id']} — {_fmt_ts(s['started_ts'])}, "
            f"{_plural(s['msg_count'])}"
        )
    return _clip("\n".join(lines))


@tool
def session_search(
    query: str = "",
    session_id: str = "",
    around_message_id: int = -1,
    window: int = 6,
    config: RunnableConfig = None,
) -> str:
    """
    Search PAST conversations (other sessions) with zero LLM cost —
    pure full-text search.

    USE when the user references earlier work ("how did we fix...",
    "continue what we did last week") or you need facts from a prior
    session not in the current context. NOT for this session (already in
    context) or for code/files (use search_code/read_file).

    MODES (auto from args): (1) DISCOVERY — pass query: top past sessions
    with matching snippets; (2) SCROLL — pass session_id +
    around_message_id from a discovery card: messages around that anchor;
    (3) BROWSE — pass nothing: most recent sessions. session_id alone
    gives that session's overview (bookends + stats).
    """
    _index.sync()  # watermark-cheap; fresh recall every call
    current_thread = str((config or {}).get("configurable", {}).get("thread_id", ""))

    if query.strip():
        return _discovery(query.strip(), current_thread)
    if session_id and around_message_id >= 0:
        return _scroll(session_id, around_message_id, window)
    if session_id:
        return _overview(session_id)
    return _browse(current_thread)
