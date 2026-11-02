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


def _is_billing_failure(error: str) -> bool:
    """True when a turn failed because the account cannot pay.

    Delegates to the engine's own classifier so the harness and the agent agree
    on what "out of money" looks like; if the two disagree, one of them retries
    a dead wallet.
    """
    try:
        from src.llm.error_classifier import _is_billing_message

        return _is_billing_message(str(error).lower())
    except Exception:
        lowered = str(error).lower()
        return "402" in lowered or "balance" in lowered and "0.00" in lowered


def summarize(turns: list[dict], turns_requested: int) -> dict:
    """The session verdict, derived ONLY from what the turns actually said.

    Kept as a pure function because the first version of this driver got the
    answer wrong in the most expensive way: it counted `turn_done` frames as
    successes, so a session where three turns reported
    `completed=false / run_outcome=budget_exhausted` printed
    "7/7 turns completed — SURVIVED". A harness that overstates survival is
    worse than no harness.
    """
    completed = [t for t in turns if t["result"] == "turn_done" and t.get("completed")]
    cut = [t for t in turns if t["result"] == "turn_done" and not t.get("completed")]
    halted = next((t for t in turns if t["result"] == "session-halted-provider-balance"), None)
    aborted = next((t for t in turns if t["result"] == "harness-aborted-llm-call-cap"), None)
    stopped_at = next(
        (t["turn"] for t in turns
         if t["result"] not in ("turn_done", "session-halted-provider-balance")),
        None,
    )
    if aborted is not None:
        # The harness stopped it, so it says so. A harness-imposed ceiling must
        # never be reported as a property of the agent.
        verdict = (
            f"HARNESS ABORT at turn {aborted['turn']} — the run exceeded the "
            f"harness call cap; this measures the harness, not the agent"
        )
    elif halted is not None:
        verdict = (
            f"HALTED — provider balance exhausted after turn {halted['turn'] - 1}; "
            f"{halted.get('turns_skipped', 0)} turn(s) not attempted"
        )
    elif stopped_at is not None:
        verdict = f"STOPPED at turn {stopped_at}"
    elif cut:
        verdict = (
            f"RAN ALL {len(turns)} PROMPTS, but {len(cut)} were CYCLE-BUDGET-CUT "
            f"(turns {', '.join(str(t['turn']) for t in cut)}) — the session keeps "
            "answering while it stops being able to finish work"
        )
    else:
        verdict = "SURVIVED every prompt"
    spent_total = sum(int(t.get("tokens_in_telemetry") or 0) for t in turns)
    spent_on_cut = sum(int(t.get("tokens_in_telemetry") or 0) for t in cut)
    return {
        "tokens_spent_total": spent_total,
        "tokens_spent_on_cut_turns": spent_on_cut,
        "tokens_per_completed_turn": (
            round(spent_total / len(completed), 1) if completed else None
        ),
        "turns_completed": len(completed),
        "turns_budget_cut": len(cut),
        "turns_cut_at": [t["turn"] for t in cut],
        "stopped_at_turn": stopped_at,
        "halted_by_billing": halted is not None,
        "aborted_by_harness": aborted is not None,
        "verdict": verdict,
        "ok": stopped_at is None and not cut and halted is None and aborted is None,
        "turns_requested": turns_requested,
    }


def build_env(args) -> dict:
    env = dict(os.environ)
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
        env = dict(os.environ)
    except Exception:
        pass
    # Field 2026-11-01 (funded run 41290247998). This line used to set the
    # AGENT's iteration budget from --max-llm-calls, whose default is 20 — less
    # than half the agent's own 45. Every "budget-cut" verdict this harness has
    # ever produced was therefore measured against a budget IT imposed, and the
    # 1.2M-token A/B was confounded: raising the token cap while the iteration
    # cap stayed at 20 just moved which leg tripped first
    # (`[budget] exhausted: iterations 20/20 >= budget`). The two knobs are now
    # separate: the agent's budget is a measured property, and --max-llm-calls
    # is a harness safety stop that aborts a runaway turn instead of shaping it.
    continuous = getattr(args, "continuous", False) or str(env.get("AGENT_CONTINUOUS_EXECUTION", "")).strip().lower() in {"1", "true", "yes", "on"}
    if continuous:
        env["AGENT_CONTINUOUS_EXECUTION"] = "1"
    if not continuous or "agent_iteration_budget" in getattr(args, "_provided_limits", set()):
        env["AGENT_ITERATION_BUDGET"] = str(args.agent_iteration_budget)
    env["PYTHONUNBUFFERED"] = "1"
    for thread_var in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[thread_var] = "1"
    env.setdefault("CRUSORAI_AUTO_APPROVE_WRITES", "1")
    env.setdefault("CRUSORAI_BRIDGE_APPROVAL_POLICY", "workspace_session")
    env.setdefault("CRUSORAI_PREVIEW_AUTOSTART", "0")
    if args.max_input_tokens is not None:
        env["AGENT_TOKEN_BUDGET"] = str(args.max_input_tokens)
    # Field 2026-11-01 (funded run 41290247998 drained the wallet in 5 turns):
    # the token cap is not a money cap. It counts cached prompt tokens at full
    # weight (53%/46%/39% of turn 5/6/7 was cached), and it says nothing about
    # the rate. AGENT_COST_BUDGET is the leg that actually bounds spend, and the
    # driver never set it — so every session ran until the provider refused.
    if args.max_cost_usd > 0:
        env["AGENT_COST_BUDGET"] = f"{args.max_cost_usd:.4f}"
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


class _ExplicitLimit(argparse.Action):
    """Remember which benchmark limits the operator actually specified."""
    def __call__(self, parser, namespace, values, option_string=None):
        provided = set(getattr(namespace, "_provided_limits", set()))
        provided.add(self.dest)
        setattr(namespace, "_provided_limits", provided)
        setattr(namespace, self.dest, values)


def _build_parser() -> argparse.ArgumentParser:
    """The CLI, as a function so tests can assert the DEFAULTS.

    The defaults are the measurement: a harness that quietly gives the agent a
    smaller budget than production is measuring its own configuration.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--prompts-file", required=True)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--turns", type=int, default=0, help="0 = every prompt in the file")
    ap.add_argument("--continuous", action="store_true", help="continue per turn without implicit harness caps")
    ap.add_argument("--timeout-s-per-turn", type=int, default=600, action=_ExplicitLimit)
    ap.add_argument("--max-session-minutes", type=int, default=45, action=_ExplicitLimit)
    ap.add_argument(
        "--agent-iteration-budget",
        action=_ExplicitLimit,
        type=int,
        default=45,
        help="the AGENT's own per-turn iteration budget (production default is 45)",
    )
    ap.add_argument(
        "--max-cost-usd",
        type=float,
        default=0.0,
        help="estimated per-turn USD cap (0 = use the graph default). Not a whole-session spending cap. "
        "A token cap cannot bound money: cached tokens are charged at full weight, "
        "so a 600k-token cap can cost far more than the tokens that did work.",
    )
    ap.add_argument(
        "--max-llm-calls",
        action=_ExplicitLimit,
        type=int,
        default=60,
        help="harness safety stop: abandon a turn that exceeds this many calls",
    )
    ap.add_argument("--max-input-tokens", type=int, default=None)
    ap.add_argument("--results-root", default=str(REPO_ROOT / "bench-results"))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

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
    if str(env.get("AGENT_CONTINUOUS_EXECUTION", "")).strip().lower() in {"1", "true", "yes", "on"}:
        supplied = getattr(args, "_provided_limits", set())
        for name in ("timeout_s_per_turn", "max_session_minutes", "max_llm_calls"):
            if name not in supplied:
                setattr(args, name, 0)
        print("[continuous] implicit time, call, token and cost limits disabled; explicit limits still apply", flush=True)
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
    seen_terminal_turns: set[str] = set()
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
            remaining_session = (args.max_session_minutes * 60 - (time.time() - session_started)
                                 if args.max_session_minutes > 0 else float("inf"))
            if remaining_session <= 30:
                turns.append({
                    "turn": index + 1, "result": "session-wall-budget-exhausted",
                    "wall_s": 0, "turns_skipped": len(prompts) - index,
                })
                break

            # The bridge forwards event_bus traffic, and event_bus REPLAYS
            # retained history to a new subscriber (subscribe(thread_id=None)).
            # So a turn can start by reading yesterday's frames. Field
            # 2026-11-01: turns 5-7 "failed" in 0.6s with 0 tokens because the
            # driver consumed a REPLAYED terminal frame from an earlier turn and
            # believed it. Drain to silence before sending the next prompt.
            drained = 0
            while True:
                try:
                    leftover = lines.get(timeout=1.0)
                except queue.Empty:
                    break
                if leftover is None:
                    break
                drained += 1
            turn_started = time.time()
            send({
                "type": "prompt", "session_id": session_id,
                "workspace": workspace, "text": prompt,
            })

            turn_timeout = args.timeout_s_per_turn if args.timeout_s_per_turn > 0 else float("inf")
            deadline = turn_started + min(turn_timeout, remaining_session)
            message_count = 0
            llm_calls = 0
            tool_calls = 0
            result = "timeout"
            completed = False
            run_outcome = None
            error = ""
            frame_tokens = 0
            while True:
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
                    # The harness safety stop, now actually enforced: previously
                    # --max-llm-calls only set the AGENT's iteration budget, so a
                    # runaway turn was shaped by the harness rather than caught
                    # by it. Exceeding this is a harness abort and is reported as
                    # such — never as the agent's own budget telling us anything.
                    if args.max_llm_calls > 0 and llm_calls > args.max_llm_calls:
                        result = "harness-aborted-llm-call-cap"
                        try:
                            send({"type": "cancel", "session_id": session_id})
                        except Exception:
                            pass
                        break
                elif ftype in ("tool_call_start",):
                    tool_calls += 1
                elif ftype == "telemetry":
                    frame_tokens = max(frame_tokens, int(frame.get("tokensIn") or 0))
                elif ftype in TERMINAL:
                    turn_key = str(frame.get("turn_id") or "")
                    if turn_key and turn_key in seen_terminal_turns:
                        continue  # replayed from an earlier turn — not ours
                    if turn_key:
                        seen_terminal_turns.add(turn_key)
                    result = ftype
                    # Field 2026-11-01: a turn_done frame is NOT success. A
                    # budget-cut turn ALSO ends in turn_done, with
                    # completed=false and run_outcome=budget_exhausted. Counting
                    # the frame type alone reported "7/7 SURVIVED" on a session
                    # where three turns were cut mid-work — the exact false
                    # green this whole harness exists to catch, committed by
                    # the harness itself.
                    completed = bool(frame.get("completed"))
                    run_outcome = frame.get("run_outcome")
                    error = str(frame.get("error") or "")[:300]
                    break
            hits, stderr_offset = compaction_lines(stderr_path, stderr_offset)
            budget_cut = any("budget] exhausted" in h for h in hits)
            # A dead wallet is terminal, not transient. Field 2026-11-01: the
            # gateway answered 402 "Balance ₹0.00. Top up from ₹10 at
            # https://velona.in/wallet", the classifier called it `unknown` and
            # retryable, and the harness dutifully spent the remaining turns
            # failing again in 0.6s each. Stop the session and say why.
            billing_stop = bool(error) and _is_billing_failure(error)
            record(
                result,
                completed=completed,
                run_outcome=run_outcome,
                error=error,
                billing_stop=billing_stop,
                drained_before_turn=drained,
                budget_cut=budget_cut,
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
            if result in ("bridge-exited", "turn-timeout", "harness-aborted-llm-call-cap"):
                break
            if billing_stop:
                turns.append({
                    "turn": len(turns) + 1,
                    "result": "session-halted-provider-balance",
                    "wall_s": 0,
                    "turns_skipped": len(prompts) - index - 1,
                })
                print(
                    "[session] HALTED: the provider refused payment. Remaining "
                    "turns were not attempted — topping up is the only fix.",
                    flush=True,
                )
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

    summary = summarize(turns, len(prompts))
    completed = [t for t in turns if t["result"] == "turn_done" and t.get("completed")]
    cut = [t for t in turns if t["result"] == "turn_done" and not t.get("completed")]
    # Field 2026-11-01: the expensive number was never printed. Three cut turns
    # billed 2.5M tokens (~$0.38) and produced nothing, which is the actual
    # "bankrupt agent core" — not the per-token rate. Spend per COMPLETED turn
    # is the only cost metric that cannot be gamed by cutting work.
    _spent_on_cut = sum(int(t.get("tokens_in_telemetry") or 0) for t in cut)
    stopped_at = summary["stopped_at_turn"]
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
        "turns_completed": summary["turns_completed"],
        "turns_budget_cut": summary["turns_budget_cut"],
        "turns_cut_at": summary["turns_cut_at"],
        "stopped_at_turn": stopped_at,
        "verdict": summary["verdict"],
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
    out.append(
        f"**{summary['turns_completed']}/{len(prompts)} prompts genuinely completed — "
        f"{summary['verdict']}**"
    )
    out.append("")
    # Field 2026-11-01: "turn" was ambiguous — one reader meant one user
    # message, another meant one loop CYCLE (one LLM call). The unit matters,
    # because "20" was a CYCLE budget per prompt while a session contains ~100
    # cycles. Both are now named, so a report can never be read two ways.
    out.append(
        "One **prompt** = one user message = N **cycles**. "
        "One cycle = one LLM call = one graph iteration."
    )
    out.append("")
    out.append("| Prompt | Frame | Completed | Outcome | Cycles | History in | Tools | Wall | New tokens | Error |")
    out.append("| ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |")
    for turn, delta in zip(turns, token_deltas):
        done = "yes" if turn.get("completed") else "**NO**"
        outcome = turn.get("run_outcome") or ("budget-cut" if turn.get("budget_cut") else "—")
        out.append(
            f"| {turn['turn']} | {turn['result']} | {done} | {outcome} | "
            f"{turn.get('llm_calls', 0)} | {turn.get('messages_at_first_call', 0)} msgs | "
            f"{turn.get('tool_calls', 0)} | {turn['wall_s']}s | {delta:,} | "
            f"{(turn.get('error') or '—')[:90]} |"
        )
    out.append("")
    growth = [t.get("messages_at_first_call", 0) for t in turns]
    if len(growth) >= 2:
        out.append(f"History entering each prompt: {growth[0]} → {growth[-1]} messages "
                   f"over {len(growth)} prompts.")
    total_cycles = sum(int(t.get("llm_calls") or 0) for t in turns)
    out.append(f"Session wall clock: {total_wall}s, {total_cycles} cycles "
               f"({total_cycles / max(1, len(turns)):.1f} cycles per prompt).")
    report = "\n".join(out) + "\n"
    (run_dir / "LONG_SESSION_REPORT.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
