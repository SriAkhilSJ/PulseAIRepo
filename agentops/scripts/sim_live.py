"""Live telemetry simulator for DEMO mode.

Continues the seeded ACTIVE session: appends tool.intent/tool.result rows to the
demo journal and a turn receipt every few seconds, then rolls into new turns —
so the SSE stream, live ticker and KPI strip visibly move in the preview.

Writes ONLY to the demo data dir passed via CRUSORAI_OPS_DATA_DIR.
"""
from __future__ import annotations

import json
import random
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / ".demo-data"
TOOLS = ["read_file", "edit_file", "bash", "run_tests", "search_repo"]


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    rng = random.Random()
    meta = json.loads((DATA_DIR / "LIVE_SESSION").read_text())
    sid, ws, turn = meta["session_id"], meta["workspace"], meta["turn"]
    db = DATA_DIR / "runtime_events.db"
    receipts = DATA_DIR / "observability" / "turns.jsonl"
    conn = sqlite3.connect(db, timeout=5)
    turn_n = 1
    step = 0
    print(f"[sim] live session {sid}", flush=True)
    while True:
        ts = time.time()
        name = rng.choice(TOOLS)
        tcid = f"tc-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO runtime_events(event_id,created_at,event_type,session_id,turn_id,workspace_id,tool_call_id,payload_json) VALUES(?,?,?,?,?,?,?,?)",
            (f"evt-{uuid.uuid4().hex}", ts, "tool.intent", sid, turn, ws, tcid,
             json.dumps({"tool_name": name, "args": {"path": f"{ws}/src/live{step}.py"}})),
        )
        conn.commit()
        time.sleep(rng.uniform(1.2, 2.6))
        ts2 = time.time()
        conn.execute(
            "INSERT INTO runtime_events(event_id,created_at,event_type,session_id,turn_id,workspace_id,tool_call_id,payload_json) VALUES(?,?,?,?,?,?,?,?)",
            (f"evt-{uuid.uuid4().hex}", ts2, "tool.result", sid, turn, ws, tcid,
             json.dumps({"tool_name": name, "status": "ok", "content": f"applied live step {step}"})),
        )
        conn.commit()
        step += 1
        if step % 5 == 0:  # close the turn with a receipt, open the next
            ts3 = time.time()
            conn.execute(
                "INSERT INTO runtime_events(event_id,created_at,event_type,session_id,turn_id,workspace_id,tool_call_id,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                (f"evt-{uuid.uuid4().hex}", ts3, "turn_done", sid, turn, ws, None, json.dumps({"summary": "live turn complete"})),
            )
            conn.commit()
            tok_in, tok_out, tok_cache = rng.randint(8000, 40000), rng.randint(500, 4000), rng.randint(2000, 15000)
            with open(receipts, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": iso(ts3), "session": sid, "turn": turn, "model": "gemini-2.5-pro", "provider": "gemini",
                    "tokens": {"input": tok_in, "output": tok_out, "cache": tok_cache},
                    "estimated_cost_usd": round((tok_in * 1.25 + tok_out * 5.0 + tok_cache * 0.31) / 1e6, 6),
                    "duration_s": round(rng.uniform(10, 45), 3), "tool_calls": 5,
                    "tool_names": TOOLS[:5], "execution_mode": "agent", "task_type": "coding",
                    "completed": True, "error": "",
                }) + "\n")
            turn_n += 1
            turn = f"turn-live-{turn_n}"
            time.sleep(1.0)
            conn.execute(
                "INSERT INTO runtime_events(event_id,created_at,event_type,session_id,turn_id,workspace_id,tool_call_id,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                (f"evt-{uuid.uuid4().hex}", time.time(), "turn_started", sid, turn, ws, None,
                 json.dumps({"model": "gemini-2.5-pro", "mode": "agent"})),
            )
            conn.commit()
        time.sleep(rng.uniform(0.8, 2.0))


if __name__ == "__main__":
    main()
