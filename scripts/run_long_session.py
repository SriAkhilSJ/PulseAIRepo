#!/usr/bin/env python3
"""Drive ONE bridge session through MANY consecutive turns, and measure whether
it survives them.

Every harness in this repo creates a fresh session per run — `run_bridge_turn.py`
says so explicitly ("creates a UNIQUE session, never reuse ids"). That means the
question "can the agent keep going for a long session?" has never been measured:
every green result is a FIRST turn, with an empty history and a cold context.

A long session is a different risk surface:

  * the transcript grows every turn, so the prompt grows every turn;
  * budgets are turn-scoped, so a long session is bounded by CONTEXT, not by
    iteration/token valves that reset;
  * compaction, checkpointing and memory are the only things standing between
    turn 1 and turn 50 — and none of them are exercised by a one-turn run.

This driver sends N prompts down a single session and records, per turn:
message_count at the first LLM call (how big the history was GOING IN), token
spend, wall time, tool calls, outcome, and any compaction the engine performed.

Usage:
  python scripts/run_long_session.py --workspace /tmp/ws \
      --prompts-file tests/e2e/prompts_session.txt \
      --turns 8 --max-session-minutes 45 --results-root /tmp/results

Exit: 0 every turn completed; 1 a turn failed/stopped; 2 setup error.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TERMINAL = ("turn_done", "turn_failed")


def load_prompts(path: Path) -> list[str]:
    """Turns separated by a line containing only `---`."""
    text = path.read_text(encoding="utf-8")
    chunks = [c.strip() for c in text.split("\n---\n")]
    return [c for c in chunks if c]


def build_env(args) -> dict:
    env = dict(os.environ)
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
        env = dict(os.environ)
    except Exception:
        pass
    env["AGENT_ITERATION_BUDGET"] = str(args.max_llm_calls)
    env["PYTHONUNBUFFERED"] = "1"
    for thread_var in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[thread_var] = "1"
    env.setdefault("CRUSORAI_AUTO_APPROVE_WRITES", "1")
    env.setdefault("CRUSORAI_BRIDGE_APPROVAL_POLICY", "workspace_session")
    env.setdefault("CRUSORAI_PREVIEW_AUTOSTART", "0")
    if args.max_input_tokens is not None:
        env["AGENT_TOKEN_BUDGET"] = str(args.max_input_tokens)
    return env


def compaction_lines(stderr_path: Path, offset: int) -> tuple[list[str], int]:
    """New stderr lines that mention context management, since `offset`."""
    try:
        with open(stderr_path, "r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            chunk = handle.read()
            new_offset = handle.tell()
    except OSError:
        return [], offset
    hits = [
        line for line in chunk.splitlines()
        if any(marker in line for marker in ("compact", "ContextEngine", "budget]", "pressure"))
    ]
    return hits, new_offset


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--prompts-file", required=True)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--turns", type=int, default=0, help="0 = every prompt in the file")
    ap.add_argument("--timeout-s-per-turn", type=int, default=600)
    ap.add_argument("--max-session-minutes", type=int, default=45)
    ap.add_argument("--max-llm-calls", type=int, default=20)
    ap.add_argument("--max-input-tokens", type=int, default=None)
    ap.add_argument("--results-root", default=str(REPO_ROOT / "bench-results"))
    args = ap.parse_args()

    prompts = load_prompts(Path(args.prompts_file))
    if not prompts:
        print("no prompts found", file=sys.stderr)
        return 2
    if args.turns > 0:
        prompts = prompts[: args.turns]

    workspace = str(Path(args.workspace).resolve())
    Path(workspace).mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or f"long-session-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir = Path(args.results_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    stderr_path = run_dir / "bridge_stderr.log"

    session_id = f"t5-{uuid.uuid4().hex[:10]}"
    env = build_env(args)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "src.bridge"],
        cwd=str(REPO_ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env,
    )

    lines: queue.Queue = queue.Queue()

    def pump_stdout() -> None:
        try:
            for raw in iter(proc.stdout.readline, b""):
                lines.put(raw.decode("utf-8", errors="backslashreplace"))
        finally:
            lines.put(None)

    def pump_stderr() -> None:
        with open(stderr_path, "wb") as handle:
            for raw in iter(proc.stderr.readline, b""):
                handle.write(raw)
                handle.flush()

    threading.Thread(target=pump_stdout, daemon=True).start()
    threading.Thread(target=pump_stderr, daemon=True).start()

    def send(frame: dict) -> None:
        proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
        proc.stdin.flush()

    turns: list[dict] = []
    session_phase = "starting"
    session_started = time.time()
    stderr_offset = 0

    def record(result, **extra) -> None:
        turns.append({
            "turn": len(turns) + 1,
            "result": result,
            "wall_s": round(time.time() - turn_started, 1),
            **extra,
        })

    try:
        send({"type": "hello", "protocol": 2})
        send({"type": "session_create", "session_id": session_id, "workspace": workspace})
        session_phase = "ready"

        for index, prompt in enumerate(prompts):
            remaining_session = args.max_session_minutes * 60 - (time.time() - session_started)
            if remaining_session <= 30:
                turns.append({
                    "turn": index + 1, "result": "session-wall-budget-exhausted",
                    "wall_s": 0, "turns_skipped": len(prompts) - index,
                })
                break

            turn_started = time.time()
            send({
                "type": "prompt", "session_id": session_id,
                "workspace": workspace, "text": prompt,
            })

            deadline = turn_started + min(args.timeout_s_per_turn, remaining_session)
            message_count = 0
            llm_calls = 0
            tool_calls = 0
            result = "timeout"
            frame_tokens = 0
            for _ in range(200000):
                if time.time() > deadline:
                    result = "turn-timeout"
                    try:
                        send({"type": "cancel", "session_id": session_id})
                    except Exception:
                        pass
                    break
                try:
                    line = lines.get(timeout=0.5)
                except queue.Empty:
                    continue
                if line is None:
                    result = "bridge-exited"
                    break
                try:
                    frame = json.loads(line)
                except Exception:
                    continue
                ftype = frame.get("type", "")
                if ftype == "llm.request":
                    llm_calls += 1
                    if llm_calls == 1:
                        message_count = int(frame.get("message_count") or 0)
                elif ftype in ("tool_call_start",):
                    tool_calls += 1
                elif ftype == "telemetry":
                    frame_tokens = max(frame_tokens, int(frame.get("tokensIn") or 0))
                elif ftype in TERMINAL:
                    result = ftype
                    break
            hits, stderr_offset = compaction_lines(stderr_path, stderr_offset)
            record(
                result,
                llm_calls=llm_calls,
                tool_calls=tool_calls,
                messages_at_first_call=message_count,
                tokens_in_telemetry=frame_tokens,
                context_events=hits[:6],
            )
            print(
                f"[turn {len(turns)}/{len(prompts)}] {result} "
                f"calls={llm_calls} history={message_count}msgs "
                f"tools={tool_calls} wall={turns[-1]['wall_s']}s",
                flush=True,
            )
            if result in ("bridge-exited", "turn-timeout"):
                break
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    completed = [t for t in turns if t["result"] == "turn_done"]
    stopped_at = next((t["turn"] for t in turns if t["result"] not in ("turn_done",)), None)
    total_wall = round(time.time() - session_started, 1)
    token_deltas: list[int] = []
    previous = 0
    for turn in turns:
        value = int(turn.get("tokens_in_telemetry") or 0)
        token_deltas.append(max(0, value - previous))
        previous = max(previous, value)

    receipt = {
        "run_id": run_id,
        "session_id": session_id,
        "phase_reached": session_phase,
        "turns_requested": len(prompts),
        "turns_attempted": len(turns),
        "turns_completed": len(completed),
        "stopped_at_turn": stopped_at,
        "session_wall_s": total_wall,
        "turns": turns,
        "tokens_per_turn": token_deltas,
        "bridge_stderr": str(stderr_path),
    }
    (run_dir / "long_session.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    # ---- markdown receipt -------------------------------------------------
    out: list[str] = []
    out.append("# Long-session stamina test")
    out.append("")
    verdict = "SURVIVED" if stopped_at is None else f"STOPPED at turn {stopped_at}"
    out.append(f"**{len(completed)}/{len(prompts)} turns completed — {verdict}**")
    out.append("")
    out.append("| Turn | Result | LLM calls | History going in | Tool calls | Wall | New tokens |")
    out.append("| ---: | :--- | ---: | ---: | ---: | ---: | ---: |")
    for turn, delta in zip(turns, token_deltas):
        out.append(
            f"| {turn['turn']} | {turn['result']} | {turn.get('llm_calls', 0)} | "
            f"{turn.get('messages_at_first_call', 0)} msgs | {turn.get('tool_calls', 0)} | "
            f"{turn['wall_s']}s | {delta:,} |"
        )
    out.append("")
    growth = [t.get("messages_at_first_call", 0) for t in turns]
    if len(growth) >= 2:
        out.append(f"History entering each turn: {growth[0]} → {growth[-1]} messages "
                   f"over {len(growth)} turns.")
    out.append(f"Session wall clock: {total_wall}s.")
    report = "\n".join(out) + "\n"
    (run_dir / "LONG_SESSION_REPORT.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    return 0 if stopped_at is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
