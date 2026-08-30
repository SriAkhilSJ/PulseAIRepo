"""Rotation-stable logical cache scope for prompt_cache_key derivation.

Context-compression rotation (legacy ``compression.in_place: false`` mode)
mints a new physical ``session_id`` mid-conversation to segment the
transcript. The prompt-cache scope introduced by #79161 was derived from that
physical id, so every rotation moved the conversation into a fresh cache
bucket even though it is logically the same conversation continuing
(issue #79017).

``resolve_prompt_cache_scope()`` maps the physical session id to the ROOT of
its *compression lineage* — the pre-rotation session id — using
``SessionDB.get_compression_lineage()``, whose fork-aware semantics
(hardened in #79193) give exactly the scope boundaries the cache key needs.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)
_MEMO_ATTR = "_prompt_cache_scope_memo"


def _lineage_root(session_id: str, session_db: Any) -> Optional[str]:
    if session_db is None:
        return None
    try:
        lineage = session_db.get_compression_lineage(session_id)
    except Exception:
        logger.debug("prompt-cache scope lineage walk failed", exc_info=True)
        return None
    if isinstance(lineage, (list, tuple)) and lineage:
        root = lineage[0]
        if isinstance(root, str) and root:
            return root
    return None


def _get_session_id(agent: Any) -> str:
    for attr in ("session_id", "thread_id", "threadId", "id", "_thread_id", "_active_thread_id", "_prompt_cache_scope"):
        try:
            v = getattr(agent, attr, None)
            if isinstance(v, str) and v:
                return v
            if v is not None and str(v).strip():
                return str(v).strip()
        except Exception:
            continue
    if isinstance(agent, dict):
        for k in ("session_id", "thread_id", "id"):
            v = agent.get(k)
            if isinstance(v, str) and v:
                return v
    return ""


def _get_session_db(agent: Any) -> Any:
    for attr in ("_session_db", "session_db", "_store", "session_store", "db", "_db"):
        try:
            db = getattr(agent, attr, None)
            if db is not None:
                return db
        except Exception:
            continue
    if isinstance(agent, dict):
        for k in ("_session_db", "session_db", "db"):
            if agent.get(k) is not None:
                return agent[k]
    return None


def resolve_prompt_cache_scope(agent: Any) -> str:
    sid = _get_session_id(agent)
    if not sid:
        if isinstance(agent, str) and agent:
            sid = agent
        else:
            return ""
    db = _get_session_db(agent)
    key = (sid, db is not None)
    memo = getattr(agent, _MEMO_ATTR, None) if not isinstance(agent, dict) else None
    if isinstance(memo, tuple) and len(memo) == 2 and memo[0] == key:
        return memo[1]
    root = _lineage_root(sid, db) if db is not None else None
    scope = root or sid
    if (root is not None or db is None or getattr(agent, "_persist_disabled", False) if not isinstance(agent, dict) else False):
        try:
            if not isinstance(agent, dict):
                setattr(agent, _MEMO_ATTR, (key, scope))
        except Exception:
            pass
    return scope


def resolve_prompt_cache_scope_safe(agent: Any) -> Optional[str]:
    try:
        return resolve_prompt_cache_scope(agent) or None
    except Exception:
        logger.debug("prompt-cache scope resolution failed", exc_info=True)
        return None
