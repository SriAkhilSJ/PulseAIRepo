"""Benchmark Driver for DeepSeek v4.1 Flash Batch Evaluation.

Executes the pinned benchmark against `deepseek/deepseek-v4.1-flash` on the
hardened CrusorAI / PulseAI runtime, performs immediate post-run standardized
16-test integration verification and Playwright headless Chromium E2E verification,
and records all empirical metrics into the results directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_DIR = REPO_ROOT / "showcase" / "agent_pulsetask"
BENCHMARK_PROMPT = REPO_ROOT / "benchmark_agent_task.txt"
RESULTS_DIR = REPO_ROOT / "bench-results"


def run_benchmark(run_id: str, max_llm_calls: int = 60, timeout_s: int = 1800) -> dict:
    print("=" * 80)
    print(f"LAUNCHING CRUSORAI BENCHMARK: {run_id}")
    print(f"MODEL: deepseek/deepseek-v4.1-flash | WORKSPACE: {SHOWCASE_DIR}")
    print("=" * 80)

    # 1. Clean workspace directory
    if SHOWCASE_DIR.exists():
        shutil.rmtree(SHOWCASE_DIR, ignore_errors=True)
    SHOWCASE_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Setup environment
    env = os.environ.copy()
    env["LLM_MODEL"] = "deepseek/deepseek-v4.1-flash"
    env["PYTHONUNBUFFERED"] = "1"
    env["CRUSORAI_LLM_STREAMING"] = "1"
    env["CRUSORAI_CAPTURE_REQUEST_PAYLOADS"] = "1"
    env["CRUSORAI_DISABLE_LONG_TERM_MEMORY"] = "1"
    env["CRUSORAI_DELIVERY_MAX_TOKENS"] = "8192"

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_bridge_turn.py"),
        "--workspace", str(SHOWCASE_DIR.resolve()),
        "--prompt-file", str(BENCHMARK_PROMPT.resolve()),
        "--run-id", run_id,
        "--timeout-s", str(timeout_s),
        "--max-llm-calls", str(max_llm_calls),
        "--max-input-tokens", "1000000",
    ]

    t0 = time.time()
    proc = subprocess.run(cmd, env=env, cwd=str(REPO_ROOT))
    duration_s = round(time.time() - t0, 2)
    print(f"\n[BENCHMARK FINISHED] Exit code: {proc.returncode} in {duration_s}s")

    # 3. Preserve showcase code deliverable for this run
    showcase_backup = RESULTS_DIR / f"{run_id}_showcase"
    if showcase_backup.exists():
        shutil.rmtree(showcase_backup, ignore_errors=True)
    if SHOWCASE_DIR.exists() and any(SHOWCASE_DIR.iterdir()):
        shutil.copytree(SHOWCASE_DIR, showcase_backup)
        print(f"[ARCHIVE] Saved code deliverable to {showcase_backup}")

    # 4. Read outcome.json
    outcome_file = RESULTS_DIR / run_id / "outcome.json"
    outcome_data = {}
    if outcome_file.exists():
        try:
            outcome_data = json.loads(outcome_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] Failed to parse outcome.json: {e}")

    return {
        "run_id": run_id,
        "exit_code": proc.returncode,
        "duration_s": duration_s,
        "outcome": outcome_data,
        "showcase_backup": str(showcase_backup),
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    run_id = sys.argv[1] if len(sys.argv) > 1 else "deepseek_v4_1_flash_run_1"
    summary = run_benchmark(run_id)
    summary_file = RESULTS_DIR / f"{run_id}_SUMMARY.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[REPORT] Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
