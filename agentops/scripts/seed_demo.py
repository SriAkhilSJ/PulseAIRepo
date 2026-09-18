"""Seed a realistic DEMO data dir (journal SQLite + receipts JSONL).

Writes agentops/.demo-data/ in the EXACT engine schemas, plus Phase-2 telemetry:
  runtime_events.db  -> runtime_events(seq,event_id,created_at,event_type,session_id,
                        turn_id,workspace_id,tool_call_id,payload_json)
      event types: session_create, turn_started, plan_created, tool.intent, tool.result,
                   turn_done, turn_failed, runtime_degraded, context_status,
                   tool.approval.request, tool.approval.done
  observability/turns.jsonl -> one receipt per turn (src/observability.py shape,
                   extra.prompt_id for the prompt registry)

Deterministic (seed=42). Point the backend at it with:
  CRUSORAI_OPS_DATA_DIR=<this dir> CRUSORAI_OPS_DEMO=on
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent.parent / ".demo-data"

TOOLS = ["read_file", "write_file", "edit_file", "bash", "search_repo", "run_tests"]
MODES = ["agent", "plan", "debug", "ask"]
TASKS = ["coding", "research", "debug", "refactor", "docs"]
MODELS = [
    ("gemini-2.5-pro", "gemini", [1.25, 5.0, 0.31]),
    ("gpt-4o-mini", "openai", [0.15, 0.6, 0.075]),
    ("llama-3.3-70b", "groq", [0.2, 0.6, 0.05]),
    ("qwen3-coder", "velona", [0.3, 1.2, 0.07]),
]
ERRORS = [
    "provider 429: rate limited after 3 retries",
    "verification gate failed: pytest exit 1 (2 failed)",
    "tool bash denied by approval policy (timeout = deny)",
    "stall guard: trailing continue-intent after 2 re-prompts",
]
WORKSPACES = ["/home/sri/projects/atlas-api", "/home/sri/projects/nova-web", "/home/sri/projects/data-pipes"]
PROMPT_IDS = ["prm-9f2ac41be7d3", "prm-77c0815aa92e"]
LAYERS = ["system_stable", "repo_map", "history", "retrieval", "memory_semantic", "feedback", "tools_schema", "volatile_tail"]


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def context_payload(rng, t):
    usage = rng.uniform(35, 88)
    window = rng.choice([128000, 200000, 1000000])
    used = int(window * usage / 100)
    bd = {lay: int(rng.uniform(200, 9000)) for lay in rng.sample(LAYERS, k=rng.randint(4, 7))}
    return {
        "model": rng.choice(MODELS)[0],
        "context_window": window,
        "context_window_source": "provider",
        "threshold_percent": 75,
        "usage_percent": round(usage, 2),
        "usage_pressure_active": usage > 75,
        "used_tokens": used,
        "compaction": {
            "events": rng.randint(0, 6),
            "tokens_reclaimed": rng.randint(0, 48000),
            "micro_events": rng.randint(0, 12),
        },
        "prompt_cache": {
            "hit_ratio": round(rng.uniform(0.2, 0.9), 3),
            "breaks": rng.randint(0, 2),
            "peak_prefix_tokens": rng.randint(8000, 30000),
        },
        "stable_prefix_invalidations": rng.randint(0, 3),
        "context_breakdown": {"layers": bd, "total_tokens": sum(bd.values())},
    }


def main() -> None:
    rng = random.Random(42)
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    db = DEMO_DIR / "runtime_events.db"
    if db.exists():
        db.unlink()
    for side in ("approvals_decisions.jsonl", "control.jsonl"):
        p = DEMO_DIR / side
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS runtime_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL,
            event_type TEXT NOT NULL,
            session_id TEXT NOT NULL,
            turn_id TEXT,
            workspace_id TEXT,
            tool_call_id TEXT,
            payload_json TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_events_session_seq ON runtime_events(session_id, seq)")
    receipts_path = DEMO_DIR / "observability" / "turns.jsonl"
    receipts_path.parent.mkdir(parents=True, exist_ok=True)

    now = time.time()

    def emit(ts, etype, sid, payload, turn=None, ws=None, tcid=None):
        conn.execute(
            "INSERT INTO runtime_events(event_id,created_at,event_type,session_id,turn_id,workspace_id,tool_call_id,payload_json) VALUES(?,?,?,?,?,?,?,?)",
            (f"evt-{uuid.UUID(int=rng.getrandbits(128), version=4)}", ts, etype, sid, turn, ws, tcid,
             json.dumps(payload, sort_keys=True, default=str)),
        )

    rf = open(receipts_path, "w", encoding="utf-8")
    n_sessions = 16
    approval_pool: list[tuple[str, str, float, str, dict]] = []  # sid, ws, ts, tool, args
    for s in range(n_sessions):
        sid = f"sess-{rng.randint(10**7, 10**8 - 1)}"
        ws = rng.choice(WORKSPACES)
        started = now - rng.uniform(0.2, 6.8) * 86400
        mode = rng.choices(MODES, weights=[6, 2, 2, 2])[0]
        model, provider, price = rng.choice(MODELS)
        prompt_id = rng.choice(PROMPT_IDS)
        emit(started, "session_create", sid, {"mode": mode, "workspace": ws}, ws=ws)
        n_turns = rng.randint(1, 4)
        t = started
        for ti in range(n_turns):
            tid = f"turn-{ti + 1}-{rng.randint(1000, 9999)}"
            t += rng.uniform(2, 40)
            emit(t, "turn_started", sid, {"model": model, "mode": mode}, turn=tid, ws=ws)
            t += rng.uniform(0.5, 3)
            plan_steps = [{"step": f"step {i+1}", "detail": d} for i, d in enumerate(
                rng.sample(["inspect repo map", "locate target module", "apply patch", "run tests", "summarize"], k=rng.randint(2, 4)))]
            emit(t, "plan_created", sid, {"steps": plan_steps}, turn=tid, ws=ws)
            tok_in, tok_out, tok_cache = 0, 0, 0
            n_tools = 0 if mode == "ask" else rng.randint(1, 6)
            tool_names = []
            for k in range(n_tools):
                name = rng.choice(TOOLS)
                tcid = f"tc-{uuid.UUID(int=rng.getrandbits(96), version=4).hex[:12]}"
                t += rng.uniform(0.4, 2.5)
                args = {"path": f"{ws}/src/mod{rng.randint(1, 9)}.py"} if name != "bash" else {"cmd": rng.choice(["pytest -q", "npm run build", "git status --short", "rm -rf build"])}
                emit(t, "tool.intent", sid, {"tool_name": name, "args": args}, turn=tid, ws=ws, tcid=tcid)
                # guarded mutations generate approval cycles
                if name in ("bash", "write_file") and rng.random() < 0.5:
                    approval_pool.append((sid, ws, t, name, args))
                dur = rng.uniform(0.2, 6.0)
                t += dur
                status = rng.choices(["ok", "error"], weights=[8, 1])[0]
                emit(t, "tool.result", sid,
                     {"tool_name": name, "status": status,
                      "content": "ok" if status == "ok" else rng.choice(["exit code 1", "file not found", "permission denied"])},
                     turn=tid, ws=ws, tcid=tcid)
                tool_names.append(name)
            # context snapshot mid-turn
            if rng.random() < 0.8:
                emit(t, "context_status", sid, context_payload(rng, t), turn=tid, ws=ws)
            tok_in += rng.randint(4000, 60000)
            tok_out += rng.randint(300, 6000)
            tok_cache += int(tok_in * rng.uniform(0.2, 0.8))
            duration = t - started if ti == 0 else rng.uniform(8, 90)
            completed = rng.random() > 0.16
            err = "" if completed else rng.choice(ERRORS)
            if not completed:
                t += 0.4
                emit(t, "turn_failed", sid, {"error": err}, turn=tid, ws=ws)
            else:
                t += 0.3
                emit(t, "turn_done", sid, {"summary": "completed"}, turn=tid, ws=ws)
            if rng.random() < 0.18:
                emit(t + 0.1, "runtime_degraded", sid, {"reason": "bounded scan truncated", "layer": rng.choice(["repo_map", "history", "retrieval"])}, turn=tid, ws=ws)
            cost = (tok_in * price[0] + tok_out * price[1] + tok_cache * price[2]) / 1e6
            rf.write(json.dumps({
                "ts": iso(t), "session": sid, "turn": tid, "model": model, "provider": provider,
                "tokens": {"input": tok_in, "output": tok_out, "cache": tok_cache},
                "estimated_cost_usd": round(cost, 6), "duration_s": round(duration, 3),
                "tool_calls": n_tools, "tool_names": tool_names,
                "execution_mode": mode, "task_type": rng.choice(TASKS),
                "completed": completed, "error": err,
                "extra": {"prompt_id": prompt_id,
                          **({"runtime.cache_break": {"layer": "history", "delta_tokens": rng.randint(2100, 9000)}} if rng.random() < 0.12 else {})},
            }, ensure_ascii=False) + "\n")
        if s == 0:
            sid_live, ws_live = sid, ws
    conn.commit()

    # approval lifecycle history (request → done; one timeout deny, one always_allow)
    for i, (sid, ws, ts, tool, args) in enumerate(approval_pool[:14]):
        tcid = f"appr-{i}-{rng.randint(1000, 9999)}"
        emit(ts, "tool.approval.request", sid,
             {"tool_id": tcid, "tool_name": tool, "args": args, "reason": "guarded mutation"}, ws=ws, tcid=tcid)
        delay = rng.uniform(3, 40)
        timed_out = (i == 3)
        approved = False if timed_out else rng.random() > 0.25
        emit(ts + delay, "tool.approval.done", sid,
             {"tool_id": tcid, "tool_name": tool, "approved": approved,
              "timed_out": timed_out, "always_allow": (i == 5 and approved)}, ws=ws, tcid=tcid)
    # one request left PENDING for the Approvals queue demo
    emit(now - 20, "tool.approval.request", sid_live,
         {"tool_id": "appr-pending-1", "tool_name": "bash",
          "args": {"cmd": "rm -rf build && npm ci"}, "reason": "guarded mutation"}, ws=ws_live, tcid="appr-pending-1")
    conn.commit()

    # active session skeleton: started, planned, mid-tool — simulator continues it
    emit(now - 60, "session_create", sid_live, {"mode": "agent", "workspace": ws_live}, ws=ws_live)
    emit(now - 55, "turn_started", sid_live, {"model": "gemini-2.5-pro", "mode": "agent"}, turn="turn-live-1", ws=ws_live)
    emit(now - 52, "plan_created", sid_live, {"steps": [{"step": "step 1", "detail": "stream live telemetry"}]}, turn="turn-live-1", ws=ws_live)
    emit(now - 30, "context_status", sid_live, context_payload(rng, now - 30), turn="turn-live-1", ws=ws_live)
    conn.commit()
    conn.close()
    rf.close()

    (DEMO_DIR / "LIVE_SESSION").write_text(json.dumps({"session_id": sid_live, "workspace": ws_live, "turn": "turn-live-1"}))
    print(f"seeded {DEMO_DIR}: {n_sessions} sessions, {len(approval_pool)} approval candidates, receipts at {receipts_path}")


if __name__ == "__main__":
    sys.exit(main())
