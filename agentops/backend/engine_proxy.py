"""Optional LIVE proxy to the engine's own dashboard server (Flask, :8080).

Activated only when CRUSORAI_OPS_ENGINE_URL is set. Subscribes to the engine SSE
stream and mirrors the approval lifecycle in-memory; forwards operator decisions
to the engine's fail-closed /api/approve endpoint (never bypasses its semantics:
timeout = deny, cross-session resolve rejected).

Engine SSE wire format: `data: {type, payload, ...}` lines (src/dashboard_server.py).
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

ENGINE_URL = os.environ.get("CRUSORAI_OPS_ENGINE_URL", "").strip().rstrip("/")
ENGINE_TOKEN = os.environ.get("CRUSORAI_OPS_ENGINE_TOKEN", "").strip()

_pending: dict[str, dict[str, Any]] = {}
_history_ring: list[dict[str, Any]] = []
connected = False


def live_pending() -> list[dict[str, Any]]:
    return list(_pending.values())


def live_connected() -> bool:
    return connected


def _post(path: str, payload: dict) -> tuple[int, dict]:
    url = f"{ENGINE_URL}{path}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {ENGINE_TOKEN}"} if ENGINE_TOKEN else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body or "{}")
            except Exception:
                return resp.status, {}
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:200]}
    except Exception as e:  # unreachable engine
        return 502, {"error": str(e)}


def resolve(tool_id: str, approved: bool, always_allow: bool, thread_id: str | None) -> tuple[int, dict]:
    return _post("/api/approve", {
        "tool_id": tool_id, "approved": approved, "always_allow": always_allow,
        **({"thread_id": thread_id} if thread_id else {}),
    })


def context_status(thread_id: str) -> tuple[int, dict]:
    url = f"{ENGINE_URL}/api/context/status?thread_id={urllib.parse.quote(thread_id)}"
    req = urllib.request.Request(url, headers={**({"Authorization": f"Bearer {ENGINE_TOKEN}"} if ENGINE_TOKEN else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:200]}
    except Exception as e:
        return 502, {"error": str(e)}


async def _sse_loop() -> None:
    global connected
    import urllib.parse

    host_port = ENGINE_URL.replace("http://", "").replace("https://", "")
    host, _, port_s = host_port.partition(":")
    port = int(port_s or 80)
    backoff = 1.0
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.write(
                (f"GET /api/stream HTTP/1.1\r\nHost: {host_port}\r\nAccept: text/event-stream\r\n"
                 + (f"Authorization: Bearer {ENGINE_TOKEN}\r\n" if ENGINE_TOKEN else "")
                 + "\r\n").encode()
            )
            await writer.drain()
            # skip headers
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            connected = True
            backoff = 1.0
            buf = b""
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n\n" in buf:
                    raw, buf = buf.split(b"\n\n", 1)
                    for ln in raw.split(b"\n"):
                        if ln.startswith(b"data:"):
                            _handle(ln[5:].strip())
        except Exception:
            connected = False
        finally:
            try:
                writer.close()
            except Exception:
                pass
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 15.0)


def _handle(raw: bytes) -> None:
    try:
        ev = json.loads(raw.decode())
    except Exception:
        return
    etype = ev.get("type", "")
    payload = ev.get("payload") or {}
    if etype == "tool.approval.request":
        tid = payload.get("tool_id") or ev.get("event_id") or ""
        _pending[tid] = {
            "tool_id": tid,
            "session_id": ev.get("thread_id") or payload.get("thread_id") or "",
            "requested_at": ev.get("created_at") or ev.get("timestamp") or 0,
            "tool_name": payload.get("tool_name", "?"),
            "args": payload.get("args") or payload.get("tool_args"),
            "source": "engine-live",
        }
    elif etype == "tool.approval.done":
        tid = payload.get("tool_id", "")
        _pending.pop(tid, None)
        _history_ring.append({
            "tool_id": tid, "approved": bool(payload.get("approved")),
            "resolved_at": ev.get("created_at") or 0, "source": "engine-live",
            "tool_name": payload.get("tool_name", "?"),
        })
        del _history_ring[:-500]


def start() -> None:
    if ENGINE_URL:
        asyncio.get_event_loop().create_task(_sse_loop())
