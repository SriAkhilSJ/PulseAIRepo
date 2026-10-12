#!/usr/bin/env python3
"""CrusorAI Step Diagnostics CLI.

Run this script on your laptop to inspect the agent's step-by-step trace,
latency breakdown, cache hit rate, and automated bottleneck diagnosis.

Usage:
    python scripts/diagnose_steps.py              # Shows latest session
    python scripts/diagnose_steps.py <session_id> # Shows specific session
"""
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.runtime.step_tracker import print_step_report
from src.runtime.reliability_metrics import evaluate_reliability, pass_at_k, pass_hat_k, wilson_ci

if __name__ == "__main__":
    session_id = None
    user_ask = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--session", "-s") and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif arg in ("--ask", "-a", "--user-ask") and i + 1 < len(args):
            user_ask = args[i + 1]
            i += 2
        elif not arg.startswith("-") and session_id is None:
            session_id = arg
            i += 1
        else:
            i += 1

    print_step_report(session_id, user_ask)

    # Multi-trial reliability footer (Cline/HumanEval standard):
    # pass@k = capability, pass^k = reliability, Wilson CI for honest ranges.
    trace_dir = Path.home() / ".crusorai" / "traces"
    target = trace_dir / f"{session_id}.jsonl" if session_id else trace_dir / "latest.jsonl"
    if target.exists():
        import json
        outcomes = []
        for line in target.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                step = json.loads(line)
            except Exception:
                continue
            if step.get("node_name") == "ai":
                status = (step.get("verification_status") or "").lower()
                outcomes.append(status in ("passed", "completed"))
        if outcomes:
            r = evaluate_reliability(outcomes, k=min(5, len(outcomes)))
            print("-" * 80)
            print("  RELIABILITY (Cline / HumanEval standard, unbiased estimators)")
            print("-" * 80)
            print(f"  pass@{r.k} (capability)      : {r.pass_at_k:.1%}  [{r.ci_low:.1%}, {r.ci_high:.1%}]")
            print(f"  pass^{r.k} (reliability)      : {r.pass_hat_k:.1%}  (all {r.k} trials succeed)")
            print(f"  ICC(1) (skill vs luck)      : {r.icc1:.2f}")
            print(f"  Verdict                    : {r.verdict}")
