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
import math
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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_MUTATION_TOOLS = frozenset({"write_file", "edit_file", "copy_file"})
_SENSITIVE_NAMES = frozenset({
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials", "secrets",
})
EPHEMERAL_CHUNK_TYPES = frozenset({
    "reasoning", "reasoning.update", "token", "token_retract", "tool_call_args",
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


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|authorization|password|secret)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_KNOWN_TOKEN_RE = re.compile(
    r"(?i)\b(?:sk-[a-z0-9_-]{8,}|gh[pousr]_[a-z0-9_]{8,}|"
    r"github_pat_[a-z0-9_]{8,})\b"
)
_RESULT_SUMMARY_LIMIT = 240
_FILE_RESULT_TOOLS = frozenset({
    "write_file", "edit_file", "copy_file", "generate_image", "media_download",
})
_RECEIPT_RESULT_TOOLS = frozenset({
    "terminal", "run_terminal", "start_terminal", "check_terminal",
    "read_terminal_output", "typecheck_workspace", "verify_ui_workspace",
    "verify_ui_routes", "build_target", "verify_target_app",
})


def _redact_receipt_text(value: object) -> str:
    """Return one compact text fragment with credentials and controls removed."""
    text = str(value or "")
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = re.sub(
        r"(?i)(bearer\s+)[a-z0-9._~+/=-]{8,}", r"\1[REDACTED]", text
    )
    text = _SECRET_ASSIGNMENT_RE.sub(r"\1\2[REDACTED]", text)
    text = _KNOWN_TOKEN_RE.sub("[REDACTED]", text)
    for name, secret in os.environ.items():
        if (
            len(secret) >= 8
            and any(
                marker in name.upper()
                for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")
            )
        ):
            text = text.replace(secret, "[REDACTED]")
    text = "".join(ch if ch in "\n\t" or ord(ch) >= 32 else " " for ch in text)
    return " ".join(text.split())


def _tool_result_summary(
    tool_name: str, content: object, status: str,
    *, limit: int = _RESULT_SUMMARY_LIMIT,
) -> str:
    """Summarize a result without retaining file bodies, reasoning, or args."""
    if status == "unfinished":
        return "no result before the run ended"
    raw = str(content or "")
    if tool_name == "think":
        return "reasoning step recorded"

    if status == "succeeded":
        if tool_name in _FILE_RESULT_TOOLS:
            # File tools return a path-sized receipt rather than file content.
            clean = _redact_receipt_text(raw[:2000])
            return clean[:limit] if clean else "file operation completed"
        if tool_name in _RECEIPT_RESULT_TOOLS:
            # Keep only verdict-shaped lines from command/check output. This is
            # enough to retain exit codes and test totals without copying logs.
            lines = [
                line for line in raw.splitlines()
                if re.search(
                    r"(?i)(?:exit\s+code|status\s*:|tests?\b|passed\b|"
                    r"failed\b|failures?\b|errors?\b|completed\b|✅|❌|⛔)",
                    line,
                )
            ]
            clean = _redact_receipt_text("\n".join(lines[-6:]))
            if clean:
                return clean[-limit:]
            return f"tool completed ({len(raw)} chars; output omitted)"
        # Privacy-default: successful reads/searches/browser/code execution can
        # return source, web text, stdout, or model reasoning. Record size only.
        return f"result received ({len(raw)} chars; content omitted)"

    # Failures/skips retain a small redacted tail because the concrete reason
    # is what makes a failed path actionable.
    clean = _redact_receipt_text(raw[-2000:])
    if not clean:
        return "no textual result"
    return clean[-limit:]


def _normalize_tool_status(
    tool_name: str, content: object, explicit_status: object,
) -> str:
    explicit = str(explicit_status or "").strip().lower()
    if explicit in {"error", "failed", "failure", "denied", "cancelled", "canceled"}:
        return "failed"
    try:
        from src.graphs.progress_helpers import classify_tool_outcome

        classified = str(classify_tool_outcome(tool_name, str(content or ""))).lower()
        if "fail" in classified or "error" in classified:
            return "failed"
        if "skip" in classified:
            return "skipped"
        return "succeeded"
    except Exception:
        clean = _redact_receipt_text(content).lower()
        if clean.startswith(("error:", "traceback", "❌")):
            return "failed"
        return "succeeded"


def _bounded_receipts(receipts: list[dict], limit: int) -> tuple[list[dict], int]:
    """Keep chronological context plus the final boundary under one hard cap."""
    limit = max(0, int(limit))
    if len(receipts) <= limit:
        return receipts, 0
    if limit == 0:
        return [], len(receipts)
    head = (limit + 1) // 2
    tail = limit - head
    kept = receipts[:head] + (receipts[-tail:] if tail else [])
    return kept, len(receipts) - len(kept)


def latency_summary_ms(values: list[int | float]) -> dict:
    """Compact nearest-rank latency statistics with a stable empty schema."""
    samples = sorted(max(0, int(round(float(value)))) for value in values)
    if not samples:
        return {
            "count": 0, "total_ms": 0, "min_ms": None,
            "p50_ms": None, "p95_ms": None, "max_ms": None,
        }

    def percentile(percent: int) -> int:
        return samples[max(0, math.ceil((percent / 100) * len(samples)) - 1)]

    return {
        "count": len(samples),
        "total_ms": sum(samples),
        "min_ms": samples[0],
        "p50_ms": percentile(50),
        "p95_ms": percentile(95),
        "max_ms": samples[-1],
    }


def receipt_status_counts(receipts: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for receipt in receipts:
        status = str(receipt.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


class RequestTimingLedger:
    """Privacy-free provider-call timings paired by internal request identity."""

    def __init__(self, *, receipt_limit: int = 32) -> None:
        self.receipt_limit = max(1, int(receipt_limit))
        self._sequence = 0
        self._pending: dict[str, dict] = {}
        self._completed: list[dict] = []

    def start(
        self, request_id: object, *, now: float | None = None,
        group: str = "",
    ) -> str:
        self._sequence += 1
        key = str(request_id or f"request-{self._sequence}")
        if key in self._pending:
            key = f"{key}#{self._sequence}"
        self._pending[key] = {
            "sequence": self._sequence,
            "started_at": time.time() if now is None else float(now),
            "group": str(group or ""),
        }
        return key

    def has_pending(self, *, group: str = "") -> bool:
        return any(
            not group or item.get("group") == group
            for item in self._pending.values()
        )

    def finish(
        self, request_id: object, *, status: str = "succeeded",
        now: float | None = None,
    ) -> bool:
        key = str(request_id or "")
        item = self._pending.pop(key, None)
        if item is None:
            return False
        ended = time.time() if now is None else float(now)
        self._completed.append({
            "sequence": item["sequence"],
            "status": status if status in {"succeeded", "failed"} else "failed",
            "duration_ms": max(0, int(round((ended - item["started_at"]) * 1000))),
        })
        return True

    def finish_oldest(
        self, *, group: str = "", status: str = "succeeded",
        now: float | None = None,
    ) -> bool:
        candidates = [
            (key, item) for key, item in self._pending.items()
            if not group or item.get("group") == group
        ]
        if not candidates:
            return False
        key, _ = min(candidates, key=lambda pair: pair[1]["sequence"])
        return self.finish(key, status=status, now=now)

    def finish_all(
        self, *, status: str, now: float | None = None,
        group: str = "",
    ) -> None:
        keys = [
            key for key, item in self._pending.items()
            if not group or item.get("group") == group
        ]
        for key in keys:
            self.finish(key, status=status, now=now)

    def _all_receipts(self, now: float | None = None) -> list[dict]:
        observed = time.time() if now is None else float(now)
        receipts = [dict(item) for item in self._completed]
        receipts.extend({
            "sequence": item["sequence"],
            "status": "unfinished",
            "duration_ms": max(
                0, int(round((observed - item["started_at"]) * 1000))
            ),
        } for item in self._pending.values())
        return sorted(receipts, key=lambda item: item["sequence"])

    def snapshot(self, *, now: float | None = None) -> tuple[list[dict], int]:
        return _bounded_receipts(self._all_receipts(now), self.receipt_limit)

    def timing_values(self, *, now: float | None = None) -> list[int]:
        return [item["duration_ms"] for item in self._all_receipts(now)]


class ToolOutcomeLedger:
    """Ordered, bounded tool outcomes that never retain arguments/full output."""

    def __init__(self, *, receipt_limit: int = 32) -> None:
        self.receipt_limit = max(1, int(receipt_limit))
        self._sequence = 0
        self._pending: dict[str, dict] = {}
        self._completed: list[dict] = []

    @staticmethod
    def _safe_name(value: object) -> str:
        name = re.sub(r"[^A-Za-z0-9_.:-]", "_", str(value or "unknown"))
        return name[:80] or "unknown"

    def start_calls(self, calls: list[dict], *, now: float | None = None) -> None:
        started = time.time() if now is None else float(now)
        for call in calls:
            if not isinstance(call, dict):
                continue
            self._sequence += 1
            raw_id = str(call.get("id") or call.get("tool_id") or "")
            key = raw_id or f"anonymous-{self._sequence}"
            if key in self._pending:
                key = f"{key}#{self._sequence}"
            self._pending[key] = {
                "sequence": self._sequence,
                "tool": self._safe_name(call.get("name")),
                "started_at": started,
            }

    def finish_call(
        self, *, tool_call_id: object, tool_name: object,
        content: object, explicit_status: object = None,
        now: float | None = None,
    ) -> None:
        key = str(tool_call_id or "")
        item = self._pending.pop(key, None)
        safe_name = self._safe_name(tool_name)
        if item is None:
            # Protocol fallbacks can omit an id. Pair the oldest same-name call
            # before creating a result-only entry with a zero observed duration.
            matches = [
                (pending_key, pending) for pending_key, pending in self._pending.items()
                if pending.get("tool") == safe_name
            ]
            if matches:
                pending_key, _ = min(matches, key=lambda pair: pair[1]["sequence"])
                item = self._pending.pop(pending_key)
            else:
                self._sequence += 1
                item = {
                    "sequence": self._sequence,
                    "tool": safe_name,
                    "started_at": time.time() if now is None else float(now),
                }
        ended = time.time() if now is None else float(now)
        status = _normalize_tool_status(item["tool"], content, explicit_status)
        self._completed.append({
            "sequence": item["sequence"],
            "tool": item["tool"],
            "status": status,
            "duration_ms": max(0, int(round((ended - item["started_at"]) * 1000))),
            "result_summary": _tool_result_summary(item["tool"], content, status),
        })

    def _all_receipts(self, now: float | None = None) -> list[dict]:
        observed = time.time() if now is None else float(now)
        receipts = [dict(item) for item in self._completed]
        receipts.extend({
            "sequence": item["sequence"],
            "tool": item["tool"],
            "status": "unfinished",
            "duration_ms": max(
                0, int(round((observed - item["started_at"]) * 1000))
            ),
            "result_summary": "no result before the run ended",
        } for item in self._pending.values())
        return sorted(receipts, key=lambda item: item["sequence"])

    def snapshot(self, *, now: float | None = None) -> tuple[list[dict], int]:
        return _bounded_receipts(self._all_receipts(now), self.receipt_limit)

    def timing_values(self, *, now: float | None = None) -> list[int]:
        return [item["duration_ms"] for item in self._all_receipts(now)]


def attach_monitoring_receipts(
    outcome: dict,
    request_timings: RequestTimingLedger,
    tool_outcomes: ToolOutcomeLedger,
    *,
    run_started_at: float,
    now: float | None = None,
) -> None:
    """Attach the stable, sanitized outcome ledger and timing summaries."""
    observed = time.time() if now is None else float(now)
    request_receipts, request_omitted = request_timings.snapshot(now=observed)
    tool_receipts, tool_omitted = tool_outcomes.snapshot(now=observed)
    all_request_receipts = request_timings._all_receipts(observed)
    all_tool_receipts = tool_outcomes._all_receipts(observed)
    outcome["outcome_schema_version"] = 2
    outcome["request_receipts"] = request_receipts
    outcome["request_receipts_omitted"] = request_omitted
    outcome["request_outcome_counts"] = receipt_status_counts(all_request_receipts)
    outcome["tool_outcomes"] = tool_receipts
    outcome["tool_outcomes_omitted"] = tool_omitted
    outcome["tool_outcome_counts"] = receipt_status_counts(all_tool_receipts)
    outcome["timing_ms"] = {
        "run_elapsed_ms": max(0, int(round((observed - run_started_at) * 1000))),
        "requests": latency_summary_ms(
            [item["duration_ms"] for item in all_request_receipts]
        ),
        "tools": latency_summary_ms(
            [item["duration_ms"] for item in all_tool_receipts]
        ),
    }
    outcome["receipt_privacy"] = (
        "tool arguments, prompts, commands, file bodies, and full results omitted"
    )


def _monitoring_json(payload: dict) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return _sanitize_runner_evidence(serialized, len(serialized))


def build_github_monitoring_annotations(
    outcome: dict, *, max_message_chars: int = 3500,
) -> list[dict[str, str]]:
    """Build independently parseable CI annotations below GitHub's hard cap.

    ``outcome.json`` is the durable local receipt. CI log archives can be
    unavailable, and one large workflow annotation is truncated at 4,096
    characters, so publish the privacy-safe ledger in small semantic batches.
    Arguments, commands, ids, prompts, and full results are selected out again
    defensively even though the outcome contract already omits them.
    """
    limit = max(512, min(int(max_message_chars), 3500))
    summary_keys = (
        "outcome_schema_version", "result", "completed", "llm_request_frames",
        "tokens_in_last_telemetry", "request_outcome_counts",
        "tool_outcome_counts", "timing_ms", "request_receipts_omitted",
        "tool_outcomes_omitted", "receipt_privacy",
    )
    summary_payload = {
        key: outcome.get(key) for key in summary_keys if key in outcome
    }
    summary_message = _monitoring_json(summary_payload)
    if len(summary_message) > limit:
        # Nested count/timing maps are generated internally, but retain a hard
        # publication bound even if a caller supplies malformed oversized data.
        summary_message = _monitoring_json({
            "outcome_schema_version": _redact_receipt_text(
                outcome.get("outcome_schema_version")
            )[:40],
            "result": _redact_receipt_text(outcome.get("result"))[:80],
            "completed": bool(outcome.get("completed")),
            "summary_omitted": True,
        })
    annotations: list[dict[str, str]] = [{
        "title": "Agent Core monitoring summary",
        "message": summary_message,
    }]

    request_fields = ("sequence", "status", "duration_ms")
    tool_fields = (
        "sequence", "tool", "status", "duration_ms", "result_summary",
    )

    def safe_events(field: str, allowed: tuple[str, ...]) -> list[dict]:
        raw_events = outcome.get(field)
        if not isinstance(raw_events, list):
            return []
        events: list[dict] = []
        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            item: dict[str, object] = {}
            for key in allowed:
                if key not in raw:
                    continue
                value = raw.get(key)
                if key in {"sequence", "duration_ms"}:
                    try:
                        item[key] = max(0, int(value))
                    except (TypeError, ValueError):
                        continue
                else:
                    field_limit = (
                        _RESULT_SUMMARY_LIMIT if key == "result_summary" else 80
                    )
                    item[key] = _redact_receipt_text(value)[:field_limit]
            events.append(item)
        return events

    def append_batches(field: str, title: str, events: list[dict]) -> None:
        batches: list[list[dict]] = []
        current: list[dict] = []
        for event in events:
            candidate = [*current, event]
            if current and len(_monitoring_json({field: candidate})) > limit:
                batches.append(current)
                current = [event]
            else:
                current = candidate
        if current:
            batches.append(current)
        for index, batch in enumerate(batches, start=1):
            message = _monitoring_json({field: batch})
            # A single event is already bounded, but fail closed if a future
            # schema expansion violates that contract.
            if len(message) > limit:
                message = _monitoring_json({
                    field: [{
                        key: value for key, value in batch[0].items()
                        if key != "result_summary"
                    }],
                    "summary_omitted": True,
                })
            annotations.append({
                "title": f"Agent Core {title} {index}/{len(batches)}",
                "message": message,
            })

    append_batches(
        "request_receipts", "requests",
        safe_events("request_receipts", request_fields),
    )
    append_batches(
        "tool_outcomes", "tools",
        safe_events("tool_outcomes", tool_fields),
    )
    return annotations


def _github_command_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def emit_github_monitoring_annotations(outcome: dict, fallback: Path) -> None:
    """Publish the sanitized ledger when the runner is executing in Actions."""
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() != "true":
        return
    for annotation in build_github_monitoring_annotations(outcome):
        safe_console_emit(
            "::notice title="
            + _github_command_escape(annotation["title"])
            + "::"
            + _github_command_escape(annotation["message"]),
            fallback,
        )


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


def effective_iteration_budget(max_llm_calls: int) -> int:
    """Return the bridge's one inclusive provider-call ceiling.

    ``--max-llm-calls`` is the runner contract, so it replaces any stale
    process-level Agent Core budget instead of creating two different walls.
    """
    return max(1, int(max_llm_calls))


def resolve_default_max_input_tokens(env: dict) -> int:
    """Resolve an adaptive cumulative input token budget based on discovered model window.

    A 1M-window model (GLM-5.3, Gemini) consumes 250k-400k cumulative tokens across
    a 20-turn complex full-stack build without approaching single-turn limits.
    Safeguards adapt to provider capacity:
      - Window >= 500k: 1,000,000 cumulative tokens
      - Window >= 128k: 500,000 cumulative tokens
      - Unknown / small: 250,000 cumulative tokens
    CLI flag (--max-input-tokens) or env (CRUSORAI_MAX_INPUT_TOKENS) always wins.
    """
    raw_env = (env.get("CRUSORAI_MAX_INPUT_TOKENS") or "").strip()
    if raw_env:
        try:
            return max(10000, int(raw_env))
        except ValueError:
            pass
    try:
        from src.context.model_budgets import resolve_context_window
        model_name = env.get("LLM_MODEL")
        provider = env.get("LLM_PROVIDER")
        win, _ = resolve_context_window(model_name, provider=provider, allow_network=False)
        if win >= 500_000:
            return 1_000_000
        if win >= 128_000:
            return 500_000
    except Exception:
        pass
    return 250_000


def should_stop_for_call_budget(llm_calls: int, limit: int) -> bool:
    """Emergency backstop after Agent Core's inclusive final slot.

    The Nth request is allowed to finish; Agent Core disables tools there and
    must close the turn. N+1 indicates contract drift and is cancelled.
    """
    return limit > 0 and llm_calls > limit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--timeout-s", type=int, default=5400)
    ap.add_argument("--max-llm-calls", type=int, default=60,
                    help=("inclusive provider-call ceiling; Agent Core reserves the final "
                          "call for text and the runner cancels contract drift beyond it"))
    ap.add_argument("--max-input-tokens", type=int, default=None,
                    help="credit circuit-breaker: cancel when cumulative input tokens pass this (defaults dynamically)")
    ap.add_argument("--max-no-delivery-calls", type=int, default=12,
                    help="cancel a paid build that still has no workspace file at this many LLM requests")
    ap.add_argument("--reasoning-effort", default=None,
                    help="per-turn reasoning effort on the prompt frame (desktop Think-picker parity)")
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

    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass

    env = dict(os.environ)
    agent_iteration_budget = effective_iteration_budget(args.max_llm_calls)
    # The graph owns the inclusive N-call contract and reserves call N for a
    # tool-free final response. The runner remains an N+1 emergency backstop.
    env["AGENT_ITERATION_BUDGET"] = str(agent_iteration_budget)
    env["PYTHONUNBUFFERED"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["NUMEXPR_NUM_THREADS"] = "1"
    env.setdefault("CRUSORAI_AUTO_APPROVE_WRITES", "1")  # autonomous build: no human to approve
    # Tell the bridge/SafeToolNode to auto-approve ordinary workspace edits.
    # The runner also handles a residual safety_request defensively below so
    # protocol drift can never strand the turn waiting for a nonexistent UI.
    env.setdefault("CRUSORAI_BRIDGE_APPROVAL_POLICY", "workspace_session")
    env.setdefault("CRUSORAI_PREVIEW_AUTOSTART", "0")
    effective_max_input_tokens = (
        args.max_input_tokens
        if args.max_input_tokens is not None
        else resolve_default_max_input_tokens(env)
    )
    env["AGENT_TOKEN_BUDGET"] = str(effective_max_input_tokens)

    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "src.bridge"],
        cwd=str(REPO_ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env,
    )

    frames_path = run_dir / "frames.jsonl"
    session_id = f"t5-{uuid.uuid4().hex[:10]}"
    run_started_at = time.time()
    request_timings = RequestTimingLedger(receipt_limit=32)
    tool_outcomes = ToolOutcomeLedger(receipt_limit=32)
    outcome: dict = {
        "run_id": run_id,
        "session_id": session_id,
        "workspace": workspace,
        "agent_iteration_budget": agent_iteration_budget,
    }
    done = threading.Event()

    def stderr_pump():
        try:
            with open(run_dir / "bridge_stderr.log", "wb") as fh:
                for raw_line in iter(proc.stderr.readline, b""):
                    try:
                        fh.write(raw_line)
                        fh.flush()
                    except OSError:
                        break
        except Exception:
            pass

    threading.Thread(target=stderr_pump, daemon=True).start()

    stdout_lines: queue.Queue[str | None] = queue.Queue()

    def stdout_pump() -> None:
        try:
            for raw_line in iter(proc.stdout.readline, b""):
                stdout_lines.put(raw_line.decode("utf-8", errors="backslashreplace"))
        finally:
            stdout_lines.put(None)

    threading.Thread(target=stdout_pump, daemon=True).start()

    def send(frame: dict) -> None:
        proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
        proc.stdin.flush()

    # Defaults live outside the transport try so even an early broken pipe or
    # malformed first frame still produces a complete outcome receipt.
    raw_stream_chunks = (
        bool(getattr(args, "trace_raw_chunks", False))
        or os.environ.get("CRUSORAI_RAW_STREAM_CHUNKS", "").strip().lower() in ("1", "true", "on")
    )
    accumulated_reasoning: list[str] = []
    # Using module-level EPHEMERAL_CHUNK_TYPES
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
            prompt_frame = {"type": "prompt", "session_id": session_id,
                            "workspace": workspace, "text": prompt}
            if args.reasoning_effort:
                prompt_frame["reasoning_effort"] = args.reasoning_effort
            send(prompt_frame)
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
                ftype = frame.get("type", "?")
                counts[ftype] = counts.get(ftype, 0) + 1

                # Stream-vs-Persist Decoupling (Hermes/OpenHands/Aider pattern):
                # Micro-chunk deltas stream live for telemetry/UI, but writing thousands
                # of individual token frames to disk balloons frames.jsonl to ~1GB under
                # 16k-32k reasoning models. Coalesce in memory and write on llm.response.
                if ftype in ("reasoning", "reasoning.update"):
                    delta = str(frame.get("text") or frame.get("delta") or frame.get("content") or "")
                    if delta:
                        accumulated_reasoning.append(delta)

                if ftype in EPHEMERAL_CHUNK_TYPES and not raw_stream_chunks:
                    pass
                else:
                    if ftype == "llm.response" and accumulated_reasoning:
                        full_thought = "".join(accumulated_reasoning)
                        if full_thought and not frame.get("reasoning"):
                            frame["reasoning"] = full_thought
                        accumulated_reasoning.clear()
                    out.write(json.dumps(frame, ensure_ascii=False) + "\n")
                    out.flush()
                try:
                    event_time = float(frame.get("timestamp"))
                except (TypeError, ValueError):
                    event_time = time.time()
                frame_session = str(frame.get("session_id") or session_id)
                if ftype == "llm.request":
                    llm_calls += 1
                    # Provider attempts are sequential inside one session. If a
                    # retry starts without a response boundary, the prior
                    # attempt failed before producing a response event.
                    if request_timings.has_pending(group=frame_session):
                        request_timings.finish_oldest(
                            group=frame_session, status="failed", now=event_time
                        )
                    request_timings.start(
                        f"{frame_session}:{llm_calls}",
                        group=frame_session,
                        now=event_time,
                    )
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
                elif ftype == "llm.response":
                    response_status = str(frame.get("status") or "").lower()
                    failed_response = bool(frame.get("error")) or response_status in {
                        "error", "failed", "failure",
                    }
                    request_timings.finish_oldest(
                        group=frame_session,
                        status="failed" if failed_response else "succeeded",
                        now=event_time,
                    )
                elif ftype == "tool_call_start":
                    tool_outcomes.start_calls([{
                        "id": f"{frame_session}:{frame.get('tool_id') or ''}",
                        "name": frame.get("name"),
                    }], now=event_time)
                elif ftype == "tool_call_end":
                    tool_outcomes.finish_call(
                        tool_call_id=f"{frame_session}:{frame.get('tool_id') or ''}",
                        tool_name=frame.get("name"),
                        content=frame.get("result"),
                        explicit_status=frame.get("status"),
                        now=event_time,
                    )
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
                should_emit = True
                if ftype in EPHEMERAL_CHUNK_TYPES:
                    should_emit = (counts[ftype] == 1) or (counts[ftype] % 100 == 0)
                if should_emit:
                    emit(f"[{time.strftime('%H:%M:%S')}] {ftype} x{counts[ftype]}"
                         + (f" | calls={llm_calls}/{args.max_llm_calls} tokensIn~{tokens_in_seen}/{effective_max_input_tokens}"
                            if ftype in ("llm.request", "telemetry") else ""))
                # ── CREDIT CIRCUIT-BREAKER ────────────────────────────────
                # Credits are valuable: past either cap the turn is CANCELLED
                # (proven zero post-cancel spend) instead of burning more.
                if not budget_stop and ftype not in ("turn_done", "turn_failed") and (
                    should_stop_for_call_budget(llm_calls, args.max_llm_calls)
                    or tokens_in_seen >= effective_max_input_tokens
                ):
                    budget_stop = True
                    emit(f"[BUDGET-STOP] calls={llm_calls} tokensIn~{tokens_in_seen} "
                         "— cancelling the turn to protect credits")
                    try:
                        send({"type": "cancel", "session_id": session_id})
                    except Exception:
                        pass
                if ftype in ("turn_done", "turn_failed"):
                    if ftype == "turn_failed":
                        request_timings.finish_all(status="failed", now=event_time)
                    outcome["result"] = "budget_exhausted" if budget_stop else ftype
                    outcome["completed"] = False if budget_stop else bool(frame.get("completed"))
                    outcome["status_contract"] = frame.get("status_contract")
                    outcome["run_outcome"] = frame.get("run_outcome")
                    outcome["failure_reason"] = frame.get("failure_reason")
                    outcome["verification_status"] = frame.get("verification_status")
                    raw_error = frame.get("error")
                    outcome["error"] = (
                        "budget_exhausted: cumulative token budget exceeded" if budget_stop
                        else (_sanitize_runner_evidence(str(raw_error), 2000) if raw_error else None)
                    )
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

    outcome["reasoning_effort_requested"] = args.reasoning_effort
    outcome["frame_counts"] = counts
    outcome["llm_request_frames"] = llm_calls
    outcome["tokens_in_last_telemetry"] = tokens_in_seen
    outcome["budget_stop"] = budget_stop
    outcome["no_delivery_stop"] = no_delivery_stop
    outcome["operator_cancelled"] = operator_cancelled
    outcome["safety_requests"] = safety_requests
    outcome["safety_approved"] = safety_approved
    outcome["safety_denied"] = safety_denied

    # Durable compact receipts: sequence/name/status/timing only. Full bridge
    # frames remain the deep local trace; outcome.json never duplicates tool
    # arguments, commands, file bodies, prompts, or full tool results.
    attach_monitoring_receipts(
        outcome,
        request_timings,
        tool_outcomes,
        run_started_at=run_started_at,
    )
    (run_dir / "outcome.json").write_text(
        json.dumps(outcome, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    emit_github_monitoring_annotations(outcome, console_fallback)
    emit(f"OUTCOME: {outcome.get('result')} completed={outcome.get('completed')} "
         f"llm.calls={llm_calls} -> {run_dir}")
    return 0 if outcome.get("result") == "turn_done" and outcome.get("completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
