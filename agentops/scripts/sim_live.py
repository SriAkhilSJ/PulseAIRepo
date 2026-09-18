"""Live telemetry simulator for DEMO mode (Phase 2).

Continues the seeded ACTIVE session and emits, every few seconds:
  * tool.intent / tool.result journal rows (+ a turn receipt per closed turn)
  * context_status snapshots (get_status()-shaped) for the Context Health view
  * tool.approval.request → tool.approval.done cycles; an operator decision written
    to approvals_decisions.jsonl by the dashboard is HONORED instead of auto-resolve
  * honors control.jsonl: {"action":"stop"} → session_cancelled + respawn a new session

Writes ONLY inside the demo data dir.
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
GUARDED = ["bash", "edit_file"]
LAYERS = ["system_stable", "repo_map", "history", "retrieval", "memory_semantic", "tools_schema", "volatile_tail"]


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


class Sim:
    def __init__(self):
        self.rng = random.Random()
        self.conn = sqlite3.connect(DATA_DIR / "runtime_events.db", timeout=5)
        self.receipts = DATA_DIR / "observability" / "turns.jsonl"
        self.decisions = DATA_DIR / "approvals_decisions.jsonl"
        self.control = DATA_DIR / "control.jsonl"
        meta = json.loads((DATA_DIR / "LIVE_SESSION").read_text())
        self.sid, self.ws, self.turn = meta["session_id"], meta["workspace"], meta["turn"]
        self.turn_n = int(self.turn.rsplit("-", 1)[-1])
        self.step = 0
        self.usage = self.rng.uniform(40, 60)
        self.compactions = 0
        self.pending_approval: dict | None = None
        self.approval_at = 0.0
        self.control_seen = 0

    def emit(self, ts, etype, payload, turn=None, tcid=None):
        self.conn.execute(
            "INSERT INTO runtime_events(event_id,created_at,event_type,session_id,turn_id,workspace_id,tool_call_id,payload_json) VALUES(?,?,?,?,?,?,?,?)",
            (f"evt-{uuid.uuid4().hex}", ts, etype, self.sid, turn or self.turn, self.ws, tcid,
             json.dumps(payload, sort_keys=True, default=str)),
        )
        self.conn.commit()

    def decided(self, tool_id: str) -> dict | None:
        if not self.decisions.exists():
            return None
        for line in self.decisions.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("tool_id") == tool_id:
                return d
        return None

    def context_snapshot(self, ts):
        self.usage = min(92.0, max(28.0, self.usage + self.rng.uniform(-6, 7)))
        if self.usage > 80:
            self.compactions += 1
            self.usage -= self.rng.uniform(8, 18)
        window = 200000
        layers = {lay: int(self.rng.uniform(300, 8000)) for lay in self.rng.sample(LAYERS, k=5)}
        self.emit(ts, "context_status", {
            "model": "gemini-2.5-pro", "context_window": window, "context_window_source": "provider",
            "threshold_percent": 75, "usage_percent": round(self.usage, 2),
            "usage_pressure_active": self.usage > 75, "used_tokens": int(window * self.usage / 100),
            "compaction": {"events": self.compactions, "tokens_reclaimed": self.compactions * 6200, "micro_events": self.step // 3},
            "prompt_cache": {"hit_ratio": round(self.rng.uniform(0.4, 0.9), 3), "breaks": 0, "peak_prefix_tokens": 21000},
            "stable_prefix_invalidations": 0,
            "context_breakdown": {"layers": layers, "total_tokens": sum(layers.values())},
        })

    def check_control(self) -> bool:
        """True if this session was stopped (caller respawns)."""
        if not self.control.exists():
            return False
        lines = self.control.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if i < self.control_seen:
                continue
            self.control_seen = i + 1
            try:
                c = json.loads(line)
            except Exception:
                continue
            if c.get("action") == "stop" and c.get("session_id", "*") in ("*", self.sid):
                self.emit(time.time(), "session_cancelled", {"reason": "operator kill switch", "scope": c.get("session_id")})
                return True
        return False

    def respawn(self):
        self.turn_n = 1
        self.step = 0
        self.sid = f"sess-{self.rng.randint(10**7, 10**8 - 1)}"
        self.turn = "turn-live-1"
        self.usage = self.rng.uniform(35, 55)
        now = time.time()
        self.emit(now, "session_create", {"mode": "agent", "workspace": self.ws}, turn=None)
        self.emit(now + 0.5, "turn_started", {"model": "gemini-2.5-pro", "mode": "agent"})
        (DATA_DIR / "LIVE_SESSION").write_text(json.dumps({"session_id": self.sid, "workspace": self.ws, "turn": self.turn}))
        print(f"[sim] respawned live session {self.sid}", flush=True)

    def run(self):
        print(f"[sim] live session {self.sid}", flush=True)
        last_ctx = 0.0
        while True:
            if self.check_control():
                self.respawn()
                continue
            ts = time.time()
            name = self.rng.choice(TOOLS)
            tcid = f"tc-{uuid.uuid4().hex[:12]}"
            args = {"path": f"{self.ws}/src/live{self.step}.py"} if name != "bash" else {"cmd": "pytest -q"}
            self.emit(ts, "tool.intent", {"tool_name": name, "args": args}, tcid=tcid)
            if name in GUARDED and self.pending_approval is None and self.rng.random() < 0.45:
                aid = f"appr-live-{uuid.uuid4().hex[:8]}"
                self.pending_approval = {"tool_id": aid, "tool_name": name, "args": args, "at": ts}
                self.emit(ts + 0.2, "tool.approval.request",
                          {"tool_id": aid, "tool_name": name, "args": args, "reason": "guarded mutation"}, tcid=aid)
            time.sleep(self.rng.uniform(1.2, 2.4))
            ts2 = time.time()
            self.emit(ts2, "tool.result", {"tool_name": name, "status": "ok", "content": f"applied live step {self.step}"}, tcid=tcid)
            self.step += 1

            # approval auto-resolve (honors operator decisions from the dashboard)
            if self.pending_approval and ts2 - self.pending_approval["at"] > 6:
                aid = self.pending_approval["tool_id"]
                dec = self.decided(aid)
                approved = bool(dec["approved"]) if dec else self.rng.random() > 0.3
                self.emit(ts2 + 0.3, "tool.approval.done",
                          {"tool_id": aid, "tool_name": self.pending_approval["tool_name"],
                           "approved": approved, "timed_out": dec is None and not approved and self.rng.random() < 0.3,
                           "always_allow": False}, tcid=aid)
                self.pending_approval = None

            if ts2 - last_ctx > 9:
                self.context_snapshot(ts2 + 0.4)
                last_ctx = ts2

            if self.step % 5 == 0:
                ts3 = time.time()
                self.emit(ts3, "turn_done", {"summary": "live turn complete"})
                tok_in, tok_out, tok_cache = self.rng.randint(8000, 40000), self.rng.randint(500, 4000), self.rng.randint(2000, 15000)
                with open(self.receipts, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "ts": iso(ts3), "session": self.sid, "turn": self.turn, "model": "gemini-2.5-pro", "provider": "gemini",
                        "tokens": {"input": tok_in, "output": tok_out, "cache": tok_cache},
                        "estimated_cost_usd": round((tok_in * 1.25 + tok_out * 5.0 + tok_cache * 0.31) / 1e6, 6),
                        "duration_s": round(self.rng.uniform(10, 45), 3), "tool_calls": 5,
                        "tool_names": TOOLS, "execution_mode": "agent", "task_type": "coding",
                        "completed": True, "error": "", "extra": {"prompt_id": "prm-9f2ac41be7d3"},
                    }) + "\n")
                self.turn_n += 1
                self.turn = f"turn-live-{self.turn_n}"
                time.sleep(1.0)
                self.emit(time.time(), "turn_started", {"model": "gemini-2.5-pro", "mode": "agent"})
            time.sleep(self.rng.uniform(0.8, 2.0))


if __name__ == "__main__":
    Sim().run()
