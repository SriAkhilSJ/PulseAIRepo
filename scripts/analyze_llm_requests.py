"""Analyze llm.request events in a benchmark run record — zero credits.

Reads bench-results/<run-id>/run-record.json (local file; no network, no key)
and prints one line per recorded provider request: time offset, model,
attempt, message count, and the first line of each message head — enough to
infer WHICH subsystem made the call (planner / main agent / aux janitor /
reflection) without sending any prompt content anywhere.

Usage (repo root, any python):
    python scripts/analyze_llm_requests.py bench-results\\founder-pbr002-2

Also prints a usage roll-up (model calls, in/out tokens, est. cost) from the
same record, so one command gives the full efficiency picture of a run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _first_line(head: str, limit: int = 90) -> str:
    for line in (head or "").splitlines():
        text = line.strip()
        if text:
            return text[:limit]
    return ""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    run_dir = Path(argv[1])
    record_path = run_dir / "run-record.json"
    if not record_path.exists():
        print(f"no run record at {record_path}")
        return 2

    record = json.loads(record_path.read_text(encoding="utf-8"))
    events = [e for e in record.get("events", []) if e.get("type") == "llm.request"]
    startup = int(record.get("startup_ms") or 0)

    print(f"run: {record.get('run_id')}  task: {record.get('task_id')}")
    print(f"llm.request events: {len(events)}")
    print()
    for i, ev in enumerate(events, 1):
        p = ev.get("payload", {})
        ts = int(ev.get("ts_ms") or 0)
        offset = f"+{(ts - startup) / 1000:6.1f}s" if startup and ts else "    n/a"
        heads = p.get("messages") or []
        head0 = _first_line(heads[0].get("head", "")) if heads else ""
        head_last = _first_line(heads[-1].get("head", "")) if heads else ""
        print(f"{i}. {offset}  model={p.get('model')!r} attempt={p.get('attempt')} "
              f"msgs={p.get('message_count')}")
        print(f"   first: {head0}")
        print(f"   last : {head_last}")
        print()

    usage = {
        "model_calls": record.get("model_calls"),
        "tool_calls": record.get("tool_calls"),
        "input_tokens": record.get("input_tokens"),
        "output_tokens": record.get("output_tokens"),
        "est_cost_usd": record.get("estimated_cost_usd"),
    }
    print("usage:", json.dumps(usage))
    mc = usage["model_calls"] or 0
    it = usage["input_tokens"] or 0
    if mc:
        print(f"avg input tokens/call: {it / mc:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
