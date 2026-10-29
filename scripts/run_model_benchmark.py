"""Multi-Model Benchmark Runner for CrusorAI / PulseAI.

Executes the cryptographically pinned benchmark specification against ANY specified model
(e.g., `openai/gpt-4o-mini`, `qwen/qwen3-coder-flash`, `deepseek/deepseek-v4.1-flash`, `z-ai/glm-5.3-flash`),
captures all request receipts and frames, archives the code deliverable, and outputs summary metrics.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHOWCASE_DIR = REPO_ROOT / "showcase" / "agent_pulsetask"
DEFAULT_BENCHMARK_PROMPT = REPO_ROOT / "benchmark_agent_task.txt"
RESULTS_DIR = REPO_ROOT / "bench-results"

KNOWN_HASHES = {
    "benchmark_agent_task.txt": "C184E32DA17735287F4049502E793AC68A4F56D42A641BA6CA9CEF4D5A5CC972",
    "benchmark_logpulse_task.txt": "4A7D33EDA603BAFA3B3C126A1944025980C65BB1C470F79CD4821C0B69492D22",
    "benchmark_gatepulse_task.txt": "427BF7B29A3BB3581FEA8FC05CA28F36590A85950797F10BA20978890BC7582D",
}


def run_benchmark(
    model: str,
    run_id: str,
    max_llm_calls: int = 60,
    timeout_s: int = 1800,
    prompt_file: Path | None = None,
    workspace: Path | None = None,
) -> dict:
    if prompt_file is None:
        prompt_file = DEFAULT_BENCHMARK_PROMPT
    else:
        prompt_file = Path(prompt_file).resolve()

    if workspace is None:
        if "logpulse" in prompt_file.name.lower():
            workspace = REPO_ROOT / "showcase" / "agent_logpulse"
        elif "gatepulse" in prompt_file.name.lower():
            workspace = REPO_ROOT / "showcase" / "agent_gatepulse"
        else:
            workspace = DEFAULT_SHOWCASE_DIR
    else:
        workspace = Path(workspace).resolve()

    print("=" * 80)
    print(f"LAUNCHING CRUSORAI MULTI-MODEL BENCHMARK: {run_id}")
    print(f"MODEL: {model} | WORKSPACE: {workspace}")
    print(f"PROMPT FILE: {prompt_file.name}")
    print("=" * 80)

    # 1. Verify pinned prompt SHA-256 hash
    import hashlib
    content = prompt_file.read_bytes()
    prompt_hash = hashlib.sha256(content).hexdigest().upper()
    expected_hash = KNOWN_HASHES.get(prompt_file.name)
    if expected_hash and prompt_hash != expected_hash:
        raise ValueError(f"PINNED PROMPT HASH MISMATCH for {prompt_file.name}: {prompt_hash} != {expected_hash}")
    print(f"[PINNED PROMPT] Verified SHA-256: {prompt_hash}")

    # 2. Derive context and budget limits from model capabilities
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from src.context.model_budgets import resolve_context_window, usable_window_budget
        window, source = resolve_context_window(model, provider="custom", allow_network=False)
        usable_budget = usable_window_budget(window)
        # Distinguish single-request context window capacity from multi-turn cumulative credit budget:
        # A 128k window model needs ~121.6k per-request context, but 500k cumulative token allowance for a multi-call build.
        cumulative_budget = 1_000_000 if window >= 500_000 else 500_000 if window >= 128_000 else 250_000
        max_input_tokens = str(cumulative_budget)
        print(f"[BUDGET] Model limits for {model}: window={window:,} ({source}), single_call_usable={usable_budget:,}, cumulative_budget={cumulative_budget:,}")
    except Exception as e:
        max_input_tokens = "500000" if "mini" in model else "1000000"
        print(f"[BUDGET] Fallback limits for {model}: {max_input_tokens} ({e})")

    # 3. Clean workspace directory
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)

    # 4. Setup environment tailored to model capabilities
    delivery_max = "4096" if "mini" in model.lower() else "8192"
    env = os.environ.copy()
    env["LLM_MODEL"] = model
    env["PYTHONUNBUFFERED"] = "1"
    # GPT models on buffered router gateways require non-streaming mode to avoid 35s chunk silence timeouts
    if "gpt" in model.lower() or "openai" in model.lower():
        env["CRUSORAI_LLM_STREAMING"] = "0"
        env["REASONING_EFFORT"] = "none"
    else:
        env["CRUSORAI_LLM_STREAMING"] = "1"
    env["CRUSORAI_LLM_STALL_TIMEOUT_S"] = "180"
    env["CRUSORAI_LLM_TIMEOUT"] = "180"
    env["CRUSORAI_CAPTURE_REQUEST_PAYLOADS"] = "1"
    env["CRUSORAI_DISABLE_LONG_TERM_MEMORY"] = "1"
    env["CRUSORAI_DELIVERY_MAX_TOKENS"] = delivery_max

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_bridge_turn.py"),
        "--workspace", str(workspace.resolve()),
        "--prompt-file", str(prompt_file.resolve()),
        "--run-id", run_id,
        "--timeout-s", str(timeout_s),
        "--max-llm-calls", str(max_llm_calls),
        "--max-input-tokens", max_input_tokens,
    ]

    t0 = time.time()
    proc = subprocess.run(cmd, env=env, cwd=str(REPO_ROOT))
    duration_s = round(time.time() - t0, 2)
    print(f"\n[BENCHMARK FINISHED] Exit code: {proc.returncode} in {duration_s}s")

    # 3. Preserve showcase code deliverable for this run
    showcase_backup = RESULTS_DIR / f"{run_id}_showcase"
    if showcase_backup.exists():
        shutil.rmtree(showcase_backup, ignore_errors=True)
    if workspace.exists() and any(workspace.iterdir()):
        shutil.copytree(workspace, showcase_backup)
        print(f"[ARCHIVE] Saved code deliverable to {showcase_backup}")

    # 4. Read outcome.json
    outcome_file = RESULTS_DIR / run_id / "outcome.json"
    outcome_data = {}
    if outcome_file.exists():
        try:
            outcome_data = json.loads(outcome_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] Failed to parse outcome.json: {e}")

    summary = {
        "model": model,
        "run_id": run_id,
        "task": prompt_file.name,
        "workspace": str(workspace),
        "exit_code": proc.returncode,
        "duration_s": duration_s,
        "outcome": outcome_data,
        "showcase_backup": str(showcase_backup),
    }

    summary_file = RESULTS_DIR / f"{run_id}_SUMMARY.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[REPORT] Summary saved to: {summary_file}")
    return summary


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Multi-model benchmark runner")
    parser.add_argument("--model", default="openai/gpt-4o-mini", help="Model name on provider")
    parser.add_argument("--run-id", default="gpt_4o_mini_run_1", help="Unique run identifier")
    parser.add_argument("--max-calls", type=int, default=60, help="Maximum LLM iterations")
    parser.add_argument("--timeout-s", type=int, default=1800, help="Execution timeout in seconds")
    parser.add_argument("--prompt-file", default=None, help="Path to prompt file")
    parser.add_argument("--workspace", default=None, help="Path to workspace directory")
    args = parser.parse_args()

    run_benchmark(
        model=args.model,
        run_id=args.run_id,
        max_llm_calls=args.max_calls,
        timeout_s=args.timeout_s,
        prompt_file=args.prompt_file,
        workspace=args.workspace,
    )


if __name__ == "__main__":
    main()
