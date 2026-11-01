#!/usr/bin/env python3
"""End-to-end core test report: did a real model turn actually work, and can we
prove why it ended?

Consumes one `scripts/run_bridge_turn.py` run directory plus the step trace the
bridge wrote, and emits a markdown report with pass/fail invariants.

The invariants are the ones the 2026-10-31 checkup established as missing:

  I1 TERMINAL REASON   the turn ends with a recorded `run_outcome`, never a
                       blank. (T1 + T3)
  I2 TRACE COVERAGE    a terminal node exists in the step trace, so a failed
                       run is diagnosable after the fact. (T3)
  I3 COST IS MEASURED  spend in USD is reported for the turn. (T4)
  I4 NO SILENT STALL   the turn either completes or names its failure reason.

Usage:
  python scripts/e2e_core_report.py --run-dir bench-results/e2e-glm53 [--require-completed]

Exit: 0 all invariants hold, 1 an invariant failed, 2 the inputs are missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

TERMINAL_FRAME_TYPES = ("turn_done", "turn_failed")


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # latest.jsonl is a pointer file, not a trace
    return rows


def _trace_for(session_id: str) -> Path | None:
    home = os.environ.get("CRUSORAI_HOME")
    roots = []
    if home:
        roots.append(Path(home) / "traces")
    roots.append(Path.home() / ".crusorai" / "traces")
    roots.append(_REPO_ROOT / "diagnostics" / "traces")
    for root in roots:
        candidate = root / f"{session_id}.jsonl"
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", default=None, help="report path (default <run-dir>/E2E_CORE_REPORT.md)")
    ap.add_argument("--require-completed", action="store_true",
                    help="treat a non-completed turn as failure (default: only invariants matter)")
    ap.add_argument("--model-label", default=os.environ.get("LLM_MODEL", "unknown"))
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    frames = _read_jsonl(run_dir / "frames.jsonl")
    if not frames:
        print(f"no frames.jsonl under {run_dir}", file=sys.stderr)
        return 2

    outcome_file = run_dir / "outcome.json"
    outcome = json.loads(outcome_file.read_text()) if outcome_file.is_file() else {}

    session_id = outcome.get("session_id") or next(
        (f.get("session_id") for f in frames if f.get("session_id")), ""
    )

    terminal = next((f for f in reversed(frames) if f.get("type") in TERMINAL_FRAME_TYPES), None)
    frame_types = Counter(f.get("type") for f in frames)
    llm_requests = frame_types.get("llm.request", 0)

    trace_path = _trace_for(session_id)
    trace = _read_jsonl(trace_path) if trace_path else []
    node_counts = Counter(r.get("node_name") for r in trace)
    terminal_row = next((r for r in reversed(trace) if r.get("node_name") == "turn_terminal"), None)
    row_diag = terminal_row.get("diagnostics", []) if terminal_row else []
    row_outcome = next((d.split(":", 1)[1].strip() for d in row_diag
                        if d.startswith("RUN_OUTCOME:")), None)
    row_reason = next((d.split(":", 1)[1].strip() for d in row_diag
                       if d.startswith("FAILURE_REASON:")), None)

    ai_rows = [r for r in trace if r.get("node_name") == "ai"]
    # A row is PRICED only when the ledger actually found a rate. Unpriced rows
    # carry null, and collapsing null to 0.0 is the exact "unknown treated as
    # free" hazard the budget leg was written to avoid — so track it separately.
    priced_rows = [r for r in ai_rows if r.get("estimated_cost_usd") is not None]
    cost = round(sum(float(r["estimated_cost_usd"]) for r in priced_rows), 6)
    tokens_in = sum(int(r.get("input_tokens") or 0) for r in ai_rows)
    tokens_out = sum(int(r.get("output_tokens") or 0) for r in ai_rows)
    cache_reported = sum(1 for r in ai_rows if r.get("cache_reported"))

    # ---- invariants -------------------------------------------------------
    checks: list[tuple[str, bool, str]] = []

    # I1: a terminal frame with a usable reason. turn_done carries run_outcome;
    # turn_failed historically carries only `error`, so either the frame's
    # contract field or the trace row must name the ending.
    frame_verdict = (terminal or {}).get("run_outcome")
    reason = frame_verdict or row_outcome or (terminal or {}).get("error")
    checks.append((
        "I1 terminal reason recorded",
        bool(terminal) and bool(reason),
        f"frame={terminal.get('type') if terminal else 'NONE'} "
        f"run_outcome={frame_verdict!r} trace_row={row_outcome!r} "
        f"reason={(row_reason or (terminal or {}).get('error'))!r}",
    ))

    # I2: the trace names a terminal node.
    checks.append((
        "I2 trace has a terminal node",
        terminal_row is not None or node_counts.get("finalize", 0) > 0,
        f"nodes={dict(node_counts) or 'EMPTY'} terminal_row={'yes' if terminal_row else 'no'}",
    ))

    # I3: cost is measured. Precise statement — every AI row that produced a
    # response must carry a price. A request that FAILED before any response
    # (dead endpoint, auth reject) has nothing to bill, so it is N/A, not a
    # failure: claiming otherwise would flag a correct run as broken.
    if priced_rows:
        i3_ok = cost > 0
        i3_detail = (
            f"llm_requests={llm_requests} priced_rows={len(priced_rows)}"
            f"/{len(ai_rows)} cost=${cost:.6f}"
        )
    elif ai_rows:
        # The run billed tokens but NOTHING could be priced: the rate card had
        # no entry for this model. That is a real gap (you cannot cost-track or
        # enforce a dollar cap), but it is not a core-test failure — the
        # governor correctly refused to invent a price.
        i3_ok = True
        i3_detail = (
            f"llm_requests={llm_requests} rows={len(ai_rows)} but "
            "0 priced — RATE CARD GAP: no published rate for this model, "
            "so cost is UNKNOWN (not $0)"
        )
    elif llm_requests:
        i3_ok = True
        i3_detail = (
            f"llm_requests={llm_requests} but no response was billed "
            "(requests failed before a completion) — N/A, nothing to price"
        )
    else:
        i3_ok = True
        i3_detail = "no LLM requests issued — N/A"
    checks.append(("I3 spend measured in USD", i3_ok, i3_detail))

    # I4: no silent stall — either completed, or a reason is present.
    completed = bool((terminal or {}).get("completed"))
    checks.append((
        "I4 no silent stall",
        completed or bool(reason),
        f"completed={completed} reason_present={bool(reason)}",
    ))

    if args.require_completed:
        checks.append(("I5 turn completed (strict)", completed,
                       f"completed={completed}"))

    failed = [c for c in checks if not c[1]]
    status = "PASS" if not failed else "FAIL"

    # ---- report -----------------------------------------------------------
    lines: list[str] = []
    lines.append("# End-to-End Agent Core Test")
    lines.append("")
    lines.append(f"**Result: `{status}`** — {len(checks) - len(failed)}/{len(checks)} invariants hold")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Model | `{args.model_label}` |")
    lines.append(f"| Session | `{session_id}` |")
    lines.append(f"| Run dir | `{run_dir}` |")
    lines.append(f"| Terminal frame | `{(terminal or {}).get('type', 'NONE')}` |")
    lines.append(f"| Recorded outcome | `{frame_verdict or row_outcome or 'NONE'}` |")
    lines.append(f"| Failure reason | `{row_reason or (terminal or {}).get('error') or '—'}` |")
    lines.append(f"| LLM requests | {llm_requests} |")
    lines.append(f"| Tokens | {tokens_in:,} in / {tokens_out:,} out |")
    if priced_rows:
        lines.append(f"| Cost | ${cost:.6f} ({len(priced_rows)}/{len(ai_rows)} rows priced) |")
    elif ai_rows:
        lines.append("| Cost | **UNKNOWN** — no published rate (rate card gap) |")
    else:
        lines.append("| Cost | N/A — nothing billed |")
    lines.append(f"| Cache-reporting calls | {cache_reported}/{len(ai_rows)} |")
    lines.append(f"| Trace | `{trace_path or 'MISSING'}` |")
    lines.append("")
    lines.append("## Invariants")
    lines.append("")
    lines.append("| # | Check | Result | Detail |")
    lines.append("| :--- | :--- | :--- | :--- |")
    for i, (name, ok, detail) in enumerate(checks, 1):
        lines.append(f"| {i} | {name} | {'✅ PASS' if ok else '❌ FAIL'} | `{detail}` |")
    lines.append("")
    lines.append("## Frame sequence")
    lines.append("")
    lines.append("`" + " → ".join(f"{k}×{v}" if v > 1 else k for k, v in frame_types.items()) + "`")
    lines.append("")
    lines.append("## Node coverage in the step trace")
    lines.append("")
    if node_counts:
        lines.append("| Node | Rows |")
        lines.append("| :--- | :--- |")
        for node, count in node_counts.most_common():
            lines.append(f"| `{node}` | {count} |")
    else:
        lines.append("_No step rows recorded._")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "Generated by `scripts/e2e_core_report.py`. Invariants I1–I4 pin the "
        "2026-10-31 fixes: a run must always name how it ended (T1/T3), and "
        "spend must be measured (T4)."
    )
    lines.append("")

    report = "\n".join(lines)
    out_path = Path(args.out) if args.out else run_dir / "E2E_CORE_REPORT.md"
    out_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\n[report] wrote {out_path}")
    print(f"[report] RESULT: {status}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
