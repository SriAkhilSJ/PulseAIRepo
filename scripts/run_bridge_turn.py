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
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_MUTATION_TOOLS = frozenset({"write_file", "edit_file", "copy_file"})
_SENSITIVE_NAMES = frozenset({
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials", "secrets",
})


def safe_console_emit(message: str, fallback: Path) -> None:
    """Best-effort heartbeat output that can never abort a live turn."""
    try:
        print(message, flush=True)
    except OSError as exc:
        try:
            with fallback.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] "
                    f"console-error={type(exc).__name__}: {exc}; {message[:1000]}\n"
                )
        except OSError:
            pass


def _sanitize_runner_evidence(value: str, limit: int) -> str:
    """Redact common credential forms and exact secret environment values."""
    bounded = value[-limit:]
    bounded = re.sub(
        r"(?i)(bearer\s+)[a-z0-9._~+/=-]{8,}", r"\1[REDACTED]", bounded
    )
    for name, secret in os.environ.items():
        if (
            len(secret) >= 8
            and any(marker in name.upper() for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
        ):
            bounded = bounded.replace(secret, "[REDACTED]")
    return bounded


def record_runner_error(outcome: dict, exc: Exception) -> None:
    """Persist a bounded traceback without copying prompts, args, or env."""
    outcome["result"] = "runner-error"
    outcome["completed"] = False
    outcome["error"] = _sanitize_runner_evidence(
        f"{type(exc).__name__}: {exc}", 2000
    )
    outcome["runner_traceback"] = _sanitize_runner_evidence(
        traceback.format_exc(limit=12), 12000
    )


def should_auto_approve_safety_request(frame: dict, workspace: str) -> bool:
    """Approve only an ordinary mutation contained by this run's workspace.

    This is the headless equivalent of Hermes ACP's workspace-session edit
    policy: sensitive paths and warnings fail closed. The full content stays in
    the bridge/tool pipeline; this decision reads only tool name and path, so a
    large write cannot balloon the approval logic or leak into logs.
    """
    if frame.get("type") != "safety_request":
        return False
    if str(frame.get("name") or "") not in _MUTATION_TOOLS:
        return False
    if str(frame.get("warning") or "").strip():
        return False
    arguments = frame.get("arguments")
    if not isinstance(arguments, dict):
        return False
    raw_path = (
        arguments.get("path")
        or arguments.get("destination")
        or arguments.get("dest")
        or arguments.get("dst")
    )
    if not isinstance(raw_path, str) or not raw_path.strip():
        return False
    candidate = Path(raw_path).expanduser()
    root = Path(workspace).resolve()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    lowered_parts = {part.lower() for part in candidate.parts}
    if lowered_parts & {".git", ".ssh", ".aws"}:
        return False
    return candidate.name.lower() not in _SENSITIVE_NAMES


def workspace_has_delivered_file(workspace: str) -> bool:
    """Cheap fail-safe for paid empty-workspace loops.

    Any regular file outside dependency/metadata trees counts as first delivery;
    product grading remains responsible for deciding whether it is meaningful.
    """
    root = Path(workspace)
    ignored = {".git", "node_modules", ".venv", "__pycache__"}
    try:
        return any(
            path.is_file() and not (set(path.relative_to(root).parts) & ignored)
            for path in root.rglob("*")
        )
    except OSError:
        return False


def should_stop_for_no_delivery(llm_calls: int, limit: int, workspace: str) -> bool:
    return limit > 0 and llm_calls >= limit and not workspace_has_delivered_file(workspace)


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
    ap.add_argument("--max-no-delivery-calls", type=int, default=12,
                    help="cancel a paid build that still has no workspace file at this many LLM requests")
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

    # Console handles can disappear in long, redirected Windows desktop runs.
    # Heartbeats are observability only: never let an OSError from print abort
    # the bridge transport. Preserve a bounded fallback log instead.
    console_fallback = run_dir / "runner_console_fallback.log"

    def emit(message: str) -> None:
        safe_console_emit(message, console_fallback)

    env = dict(os.environ)
    env.setdefault("PULSEAI_AUTO_APPROVE_WRITES", "1")  # autonomous build: no human to approve
    # Tell the bridge/SafeToolNode to auto-approve ordinary workspace edits.
    # The runner also handles a residual safety_request defensively below so
    # protocol drift can never strand the turn waiting for a nonexistent UI.
    env.setdefault("PULSEAI_BRIDGE_APPROVAL_POLICY", "workspace_session")

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

    stdout_lines: queue.Queue[str | None] = queue.Queue()

    def stdout_pump() -> None:
        try:
            for line in proc.stdout:
                stdout_lines.put(line)
        finally:
            stdout_lines.put(None)

    threading.Thread(target=stdout_pump, daemon=True).start()

    def send(frame: dict) -> None:
        proc.stdin.write(json.dumps(frame) + "\n")
        proc.stdin.flush()

    # Defaults live outside the transport try so even an early broken pipe or
    # malformed first frame still produces a complete outcome receipt.
    counts: dict[str, int] = {}
    llm_calls = 0
    tokens_in_seen = 0
    budget_stop = False
    no_delivery_stop = False
    operator_cancelled = False
    safety_requests = 0
    safety_approved = 0
    safety_denied = 0
    try:
        with open(frames_path, "w", encoding="utf-8") as out:
            send({"type": "hello", "protocol": 2})
            send({"type": "session_create", "session_id": session_id, "workspace": workspace})
            send({"type": "prompt", "session_id": session_id,
                  "workspace": workspace, "text": prompt})
            deadline = time.time() + args.timeout_s
            while time.time() < deadline:
                remaining = deadline - time.time()
                try:
                    line = stdout_lines.get(timeout=max(0.01, min(1.0, remaining)))
                except queue.Empty:
                    continue
                if line is None:
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
                    if (
                        not no_delivery_stop
                        and should_stop_for_no_delivery(
                            llm_calls, args.max_no_delivery_calls, workspace
                        )
                    ):
                        no_delivery_stop = True
                        emit(
                            f"[NO-DELIVERY-STOP] {llm_calls} LLM requests and "
                            "workspace still has no files — cancelling to protect credits"
                        )
                        try:
                            send({"type": "cancel", "session_id": session_id})
                        except Exception:
                            pass
                if ftype == "telemetry":
                    tokens_in_seen = max(tokens_in_seen, int(frame.get("tokensIn") or 0))
                if ftype == "safety_request":
                    safety_requests += 1
                    approved = should_auto_approve_safety_request(frame, workspace)
                    if approved:
                        safety_approved += 1
                    else:
                        safety_denied += 1
                    # Always answer. A headless run must never wait five
                    # minutes for an approval UI that does not exist.
                    send({
                        "type": "safety_reply",
                        "session_id": session_id,
                        "tool_id": str(frame.get("tool_id") or ""),
                        "approved": approved,
                        "always_allow": False,
                    })
                emit(f"[{time.strftime('%H:%M:%S')}] {ftype} x{counts[ftype]}"
                     + (f" | calls={llm_calls}/{args.max_llm_calls} tokensIn~{tokens_in_seen}/{args.max_input_tokens}"
                        if ftype in ("llm.request", "telemetry") else ""))
                # ── CREDIT CIRCUIT-BREAKER ────────────────────────────────
                # Credits are valuable: past either cap the turn is CANCELLED
                # (proven zero post-cancel spend) instead of burning more.
                if not budget_stop and ftype not in ("turn_done", "turn_failed") and (
                    llm_calls >= args.max_llm_calls
                    or tokens_in_seen >= args.max_input_tokens
                ):
                    budget_stop = True
                    emit(f"[BUDGET-STOP] calls={llm_calls} tokensIn~{tokens_in_seen} "
                         "— cancelling the turn to protect credits")
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
    except KeyboardInterrupt:
        # Ctrl+C is an operator cancellation, not a bridge crash. Always leave
        # a receipt—the Attempt-6 manual stop otherwise looked like a missing
        # outcome/serialization failure and lost the true first boundary.
        operator_cancelled = True
        outcome["result"] = "operator-cancelled"
        outcome["completed"] = False
        outcome["error"] = None
        try:
            send({"type": "cancel", "session_id": session_id})
        except Exception:
            pass
    except Exception as exc:
        # Evidence must survive transport failures. Keep this sanitized: the
        # prompt, arguments, environment, and provider key are never copied.
        record_runner_error(outcome, exc)
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
    outcome["no_delivery_stop"] = no_delivery_stop
    outcome["operator_cancelled"] = operator_cancelled
    outcome["safety_requests"] = safety_requests
    outcome["safety_approved"] = safety_approved
    outcome["safety_denied"] = safety_denied
    (run_dir / "outcome.json").write_text(
        json.dumps(outcome, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    emit(f"OUTCOME: {outcome.get('result')} completed={outcome.get('completed')} "
         f"llm.calls={llm_calls} -> {run_dir}")
    return 0 if outcome.get("result") == "turn_done" and outcome.get("completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
