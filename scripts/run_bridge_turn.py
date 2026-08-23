"""Drive ONE long agent turn through the real bridge, recording every frame.

Used for lab tests (Test 5): spawns `python -m src.bridge`, handshakes,
creates a UNIQUE session (never reuse ids — durable checkpoint pollution),
sends the prompt from a file, then streams frames to <run-dir>/frames.jsonl
until turn_done / turn_failed / timeout. Prints a live one-line heartbeat
per frame type so watchdogs see activity.

Exit codes: 0 = turn_done completed; 1 = failed/timeout; 2 = setup error.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--timeout-s", type=int, default=5400)
    ap.add_argument("--max-llm-calls", type=int, default=60,
                    help="credit circuit-breaker: cancel the turn at this many provider calls")
    ap.add_argument("--max-input-tokens", type=int, default=250000,
                    help="credit circuit-breaker: cancel when cumulative input tokens pass this")
    ap.add_argument("--results-root", default="bench-results")
    args = ap.parse_args()

    workspace = str(Path(args.workspace).resolve())
    prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if not prompt:
        print("empty prompt file")
        return 2
    run_id = args.run_id or f"turn-{uuid.uuid4().hex[:12]}"
    run_dir = Path(args.results_root) / run_id
    if run_dir.exists():
        print(f"run-id conflict: {run_dir} exists (graded evidence is never overwritten)")
        return 2
    run_dir.mkdir(parents=True)

    env = dict(os.environ)
    env.setdefault("PULSEAI_AUTO_APPROVE_WRITES", "1")  # autonomous build: no human to approve

    proc = subprocess.Popen(
        [sys.executable, "-m", "src.bridge"],
        cwd=str(REPO_ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env,
    )

    frames_path = run_dir / "frames.jsonl"
    session_id = f"t5-{uuid.uuid4().hex[:10]}"
    outcome: dict = {"run_id": run_id, "session_id": session_id, "workspace": workspace}
    done = threading.Event()

    def stderr_pump():
        with open(run_dir / "bridge_stderr.log", "w", encoding="utf-8") as fh:
            for line in proc.stderr:
                fh.write(line)
                fh.flush()

    threading.Thread(target=stderr_pump, daemon=True).start()

    def send(frame: dict) -> None:
        proc.stdin.write(json.dumps(frame) + "\n")
        proc.stdin.flush()

    try:
        with open(frames_path, "w", encoding="utf-8") as out:
            send({"type": "hello", "protocol": 2})
            send({"type": "session_create", "session_id": session_id, "workspace": workspace})
            send({"type": "prompt", "session_id": session_id,
                  "workspace": workspace, "text": prompt})
            deadline = time.time() + args.timeout_s
            counts: dict[str, int] = {}
            llm_calls = 0
            tokens_in_seen = 0
            budget_stop = False
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    outcome["result"] = "bridge-exited"
                    break
                try:
                    frame = json.loads(line)
                except Exception:
                    continue
                out.write(json.dumps(frame, ensure_ascii=False) + "\n")
                out.flush()
                ftype = frame.get("type", "?")
                counts[ftype] = counts.get(ftype, 0) + 1
                if ftype == "llm.request":
                    llm_calls += 1
                if ftype == "telemetry":
                    tokens_in_seen = max(tokens_in_seen, int(frame.get("tokensIn") or 0))
                print(f"[{time.strftime('%H:%M:%S')}] {ftype} x{counts[ftype]}"
                      + (f" | calls={llm_calls}/{args.max_llm_calls} tokensIn~{tokens_in_seen}/{args.max_input_tokens}"
                         if ftype in ("llm.request", "telemetry") else ""),
                      flush=True)
                # ── CREDIT CIRCUIT-BREAKER ────────────────────────────────
                # Credits are valuable: past either cap the turn is CANCELLED
                # (proven zero post-cancel spend) instead of burning more.
                if not budget_stop and ftype not in ("turn_done", "turn_failed") and (
                    llm_calls >= args.max_llm_calls
                    or tokens_in_seen >= args.max_input_tokens
                ):
                    budget_stop = True
                    print(f"[BUDGET-STOP] calls={llm_calls} tokensIn~{tokens_in_seen} "
                          "— cancelling the turn to protect credits", flush=True)
                    try:
                        send({"type": "cancel", "session_id": session_id})
                    except Exception:
                        pass
                if ftype in ("turn_done", "turn_failed"):
                    outcome["result"] = ftype
                    outcome["completed"] = bool(frame.get("completed"))
                    outcome["error"] = frame.get("error")
                    break
            else:
                outcome["result"] = "timeout"
    finally:
        try:
            send({"type": "shutdown"})
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    outcome["frame_counts"] = counts
    outcome["llm_request_frames"] = llm_calls
    outcome["tokens_in_last_telemetry"] = tokens_in_seen
    outcome["budget_stop"] = budget_stop
    (run_dir / "outcome.json").write_text(
        json.dumps(outcome, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OUTCOME: {outcome.get('result')} completed={outcome.get('completed')} "
          f"llm.calls={llm_calls} -> {run_dir}")
    return 0 if outcome.get("result") == "turn_done" and outcome.get("completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
