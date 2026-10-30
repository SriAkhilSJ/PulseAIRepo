"""P2/P3/P4: catalog invalidation, the Plan Mode gate, and per-call receipts.

- P2: a server that announces `notifications/tools/list_changed` gets its catalog
  re-read, or a tool it just gained stays invisible for the session.
- P3: Plan Mode may read third-party state and may not change it. The refusal is
  a phase decision, not an approval request — asking a human mid-plan is the
  wrong question.
- P4: every call leaves a ledger line, so a slow server is attributable.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from src.tools.mcp_client import close_all, mcp_config_path, server_tools
from src.tools.mcp_tool import mcp_call

# A server that grows a tool after the first call, and says so.
CHANGING_SERVER = textwrap.dedent("""
    import json, sys

    def send(obj):
        print(json.dumps(obj), flush=True)

    extra = {"on": False}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        method = req.get("method")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": req["id"], "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "grow", "version": "0.1"}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            tools = [
                {"name": "peek", "description": "read",
                 "inputSchema": {"type": "object"},
                 "annotations": {"readOnlyHint": True}},
                {"name": "grow_catalog", "description": "mutates the catalog",
                 "inputSchema": {"type": "object"}}]
            if extra["on"]:
                tools.append({"name": "late", "description": "appeared later",
                              "inputSchema": {"type": "object"},
                              "annotations": {"readOnlyHint": True}})
            send({"jsonrpc": "2.0", "id": req["id"], "result": {"tools": tools}})
        elif method == "tools/call":
            if req["params"]["name"] == "grow_catalog":
                extra["on"] = True
                send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
                send({"jsonrpc": "2.0", "id": req["id"], "result": {
                    "content": [{"type": "text", "text": "catalog grew"}]}})
            else:
                send({"jsonrpc": "2.0", "id": req["id"], "result": {
                    "content": [{"type": "text", "text": "peeked"}]}})
""")


@pytest.fixture(autouse=True)
def clean():
    close_all()
    yield
    close_all()


@pytest.fixture()
def ws(tmp_path):
    script = tmp_path / "grow_server.py"
    script.write_text(CHANGING_SERVER, encoding="utf-8")
    cfg = mcp_config_path(str(tmp_path))
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"servers": {"grow": {
        "command": sys.executable, "args": [str(script)], "enabled": True}}}), encoding="utf-8")
    return str(tmp_path)


def _call(tool, args, workspace, phase="agent"):
    return tool.invoke(args, {"configurable": {"workspace": workspace, "tool_phase": phase}})


# -- P2: list_changed -------------------------------------------------------

def test_list_changed_invalidates_the_catalog(ws):
    assert [t["name"] for t in server_tools(ws, "grow")] == ["peek", "grow_catalog"]
    # the server gains a tool and announces it while answering this call
    assert "catalog grew" in _call(mcp_call, {"server": "grow", "tool": "grow_catalog",
                                              "confirm": True}, ws)
    assert "late" in [t["name"] for t in server_tools(ws, "grow")], \
        "the announced change did not invalidate the cache"


def test_a_notification_inside_a_response_batch_is_not_mistaken_for_it(ws):
    """The notification arrives on the same stream; the response must still be
    matched by id, not by arrival order."""
    out = _call(mcp_call, {"server": "grow", "tool": "grow_catalog", "confirm": True}, ws)
    assert "catalog grew" in out


# -- P3: the Plan Mode gate -------------------------------------------------

def test_plan_mode_denies_a_mutating_mcp_call(ws):
    out = _call(mcp_call, {"server": "grow", "tool": "grow_catalog",
                           "confirm": True}, ws, phase="plan")
    assert "PHASE_DENIED" in out and "Plan Mode" in out
    assert "grew" not in out, "the call executed during a plan"


def test_plan_mode_allows_a_read_only_call(ws):
    out = _call(mcp_call, {"server": "grow", "tool": "peek"}, ws, phase="plan")
    assert "peeked" in out
    assert "PHASE_DENIED" not in out


def test_agent_phase_still_asks_before_a_mutation(ws):
    out = _call(mcp_call, {"server": "grow", "tool": "grow_catalog"}, ws, phase="agent")
    assert "APPROVAL REQUIRED" in out and "PHASE_DENIED" not in out


# -- P4: receipts -----------------------------------------------------------

def test_a_call_leaves_a_receipt_in_the_ledger(ws, tmp_path, monkeypatch):
    ledger_dir = tmp_path / "ledger"
    monkeypatch.setenv("CRUSORAI_TELEMETRY_DIR", str(ledger_dir))
    monkeypatch.setenv("CRUSORAI_TELEMETRY", "on")

    _call(mcp_call, {"server": "grow", "tool": "peek"}, ws)

    files = list(ledger_dir.glob("calls-*.jsonl"))
    assert files, "no ledger file written"
    rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line]
    mcp_rows = [r for r in rows if r.get("kind") == "mcp_call"]
    assert mcp_rows, rows
    row = mcp_rows[-1]
    assert row["server"] == "grow" and row["tool"] == "peek"
    assert row["ok"] is True and row["wall_s"] >= 0


def test_a_denied_call_writes_no_receipt(ws, tmp_path, monkeypatch):
    ledger_dir = tmp_path / "ledger2"
    monkeypatch.setenv("CRUSORAI_TELEMETRY_DIR", str(ledger_dir))
    monkeypatch.setenv("CRUSORAI_TELEMETRY", "on")
    _call(mcp_call, {"server": "grow", "tool": "grow_catalog"}, ws, phase="plan")
    rows = []
    for path in ledger_dir.glob("calls-*.jsonl"):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert not [r for r in rows if r.get("kind") == "mcp_call"], \
        "a phase-denied call was metered as if it ran"
