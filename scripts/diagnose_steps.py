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
    session_id = sys.argv[1] if len(sys.argv) > 1 else None
    print_step_report(session_id)
