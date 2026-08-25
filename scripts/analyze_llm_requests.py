"""Analyze llm.request events in benchmark run records — zero credits.

Reads bench-results/<run-id>/run-record.json (local files; no network, no key)
and prints one line per recorded provider request: time offset, model,
attempt, message count, and the first line of each message head — enough to
infer WHICH subsystem made the call (planner / main agent / aux janitor /
reflection) without sending any prompt content anywhere.

Pass ONE run dir for the per-call breakdown, or SEVERAL run dirs of the SAME
task for a variance comparison (calls / tokens / cost min-max-avg) — the
consistency signal for the rule-of-three.

Usage (repo root, any python):
    python scripts/analyze_llm_requests.py bench-results\\founder-pbr002-2
    python scripts/analyze_llm_requests.py bench-results\\founder-pbr002-2 bench-results\\founder-pbr002-3
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


def _load(run_dir: Path) -> dict:
    record_path = run_dir / "run-record.json"
    if not record_path.exists():
        raise SystemExit(f"no run record at {record_path}")
    return json.loads(record_path.read_text(encoding="utf-8"))


def _breakdown(record: dict) -> None:
    events = [e for e in record.get("events", []) if e.get("type") == "llm.request"]
    startup = int(record.get("startup_ms") or 0)

    # Loop anatomy (hermes doctrine: attribute before fixing): the frame
    # stream shows WHAT the model actually did — tool calls, safety
    # denials, plans, replans — not just provider requests.
    frames = record.get("frames", [])
    from collections import Counter
    frame_counts = Counter(f.get("type") for f in frames)
    tool_starts = [f for f in frames if f.get("type") == "tool_call_start"]
    safety = [f for f in frames if f.get("type") == "safety_request"]
    if tool_starts or safety or frame_counts.get("plan_updated"):
        print("loop anatomy:")
        if tool_starts:
            names = Counter(t.get("name") for t in tool_starts)
            print(f"  tool calls started: {len(tool_starts)} -> {dict(names)}")
        if safety:
            print(f"  safety requests (approvals/denials): {len(safety)}")
        if frame_counts.get("plan_updated"):
            print(f"  plan_updated frames: {frame_counts['plan_updated']}")
        print()

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


def _variance(records: list[dict]) -> None:
    rows = []
    for r in records:
        rows.append({
            "run": r.get("run_id"),
            "calls": int(r.get("model_calls") or 0),
            "in": int(r.get("input_tokens") or 0),
            "out": int(r.get("output_tokens") or 0),
            "cost": float(r.get("estimated_cost_usd") or 0.0),
        })
    print("## Variance across runs (same task) — the consistency signal")
    print()
    print("| Run | Model calls | Tokens in | Tokens out | Est. $ |")
    print("|---|---|---|---|---|")
    for row in rows:
        print(f"| {row['run']} | {row['calls']} | {row['in']} | {row['out']} | {row['cost']:.4f} |")
    if len(rows) >= 2:
        def stats(key: str) -> str:
            vals = [row[key] for row in rows]
            return f"min {min(vals)} · max {max(vals)} · avg {sum(vals) / len(vals):.1f}"
        print()
        print(f"- Model calls: {stats('calls')}  (spread {max(r['calls'] for r in rows) - min(r['calls'] for r in rows)})")
        print(f"- Tokens in:   {stats('in')}")
        print(f"- Est. cost:   {stats('cost')}")
        spread = max(r["cost"] for r in rows) - min(r["cost"] for r in rows)
        base = min(r["cost"] for r in rows) or 1e-9
        print(f"- Cost swing: {spread / base * 100:.0f}% — anything above ~20% on the "
              f"identical task means call bloat is nondeterministic (attribute it before claiming a baseline)")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    records = [_load(Path(p)) for p in argv[1:]]
    if len(records) == 1:
        _breakdown(records[0])
    else:
        _variance(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

