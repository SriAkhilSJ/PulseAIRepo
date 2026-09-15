"""PROOF: drive the ENGINE'S OWN sink writers — no simulator code involved.

Loads src/observability.py (record_turn_receipt — the exact function chat_graph
calls per turn) and src/runtime/event_journal.py (EventJournal — the exact class
tool_middleware journals through) directly by file path (both are stdlib-only),
then writes one session's worth of telemetry into the data dir the dashboard
reads. If the dashboard shows this session with these exact numbers, the whole
pipeline (sinks → readers → API → UI) is real, not hardcoded.

Usage: CRUSORAI_OPS_DATA_DIR=<dir> .venv/bin/python scripts/proof_engine_writers.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("CRUSORAI_OPS_DATA_DIR", str(Path.home() / ".pulseai"))).expanduser()


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    os.environ["PULSEAI_OBSERVABILITY"] = "on"
    os.environ["PULSEAI_OBSERVABILITY_PATH"] = str(DATA / "observability" / "turns.jsonl")
    obs = load("engine_observability", "src/observability.py")
    ej = load("engine_event_journal", "src/runtime/event_journal.py")

    sid = "sess-engine-writers"
    journal = ej.EventJournal(DATA / "runtime_events.db")  # engine class, real schema
    now = time.time()

    journal.append("session_create", {"mode": "agent", "workspace": str(REPO), "proof": True}, session_id=sid, workspace_id=str(REPO))
    journal.append("turn_started", {"model": "proof-run", "mode": "agent"}, session_id=sid, turn_id="turn-proof-1")
    journal.append("tool.intent", {"tool_name": "read_file", "args": {"path": "src/observability.py"}},
                   session_id=sid, turn_id="turn-proof-1", tool_call_id="tc-proof-1")
    time.sleep(0.4)
    journal.append("tool.result", {"tool_name": "read_file", "status": "ok", "content": "engine writer executed"},
                   session_id=sid, turn_id="turn-proof-1", tool_call_id="tc-proof-1")
    journal.append("turn_done", {"summary": "written by engine code"}, session_id=sid, turn_id="turn-proof-1")

    ok = obs.record_turn_receipt(  # engine exporter, real JSONL shape
        thread_id=sid, turn_id="turn-proof-1", model="proof-run", provider="engine-writers",
        input_tokens=1234, output_tokens=567, cache_tokens=890,
        estimated_cost_usd=0.004242, duration_s=1.234, tool_calls=1,
        tool_names=["read_file"], execution_mode="agent", task_type="proof",
        completed=True, error="",
    )
    journal.close()
    print(f"engine writers executed: receipt_written={ok}")
    print(f"  journal : {DATA / 'runtime_events.db'}  (session {sid})")
    print(f"  receipts: {os.environ['PULSEAI_OBSERVABILITY_PATH']}")
    print("now open the dashboard → Sessions → sess-engine-writers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
