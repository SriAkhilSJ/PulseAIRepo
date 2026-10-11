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
