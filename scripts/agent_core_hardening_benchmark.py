#!/usr/bin/env python3
"""Dependency-free measurement for the Agent Core hardening slice.

Measures only what this change can honestly affect: sanitizer CPU time,
SQLite append latency, durable payload/database bytes, and bounded-scan
selection stability. It makes no provider/model calls, so it cannot claim an
LLM token, quality, or API-price improvement.
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.context.bounded_scan import ScanLimits, scan_files
from src.runtime import event_journal as event_journal_module
from src.runtime.event_journal import EventJournal
from src.runtime.persistence import sanitize_event_payload


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction) - 1))
    return ordered[index]


def _timed(iterations: int, fn: Callable[[], object]) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - started) / 1_000)
    return {
        "median_us": round(statistics.median(samples), 3),
        "p95_us": round(_percentile(samples, 0.95), 3),
    }


def _journal_run(
    path: Path,
    event_type: str,
    payload: dict,
    writes: int,
    *,
    unsafe_reference: bool,
) -> dict:
    original = event_journal_module.sanitize_event_payload
    if unsafe_reference:
        # Exact pre-hardening behavior, isolated to this benchmark process.
        event_journal_module.sanitize_event_payload = lambda _kind, value: value
    samples: list[float] = []
    try:
        journal = EventJournal(path)
        for index in range(writes):
            started = time.perf_counter_ns()
            journal.append(
                event_type,
                payload,
                session_id="benchmark",
                tool_call_id=f"tool-{index}",
            )
            samples.append((time.perf_counter_ns() - started) / 1_000_000)
        journal._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        journal.close()
    finally:
        event_journal_module.sanitize_event_payload = original

    with sqlite3.connect(path) as conn:
        encoded = conn.execute(
            "SELECT payload_json FROM runtime_events ORDER BY seq LIMIT 1"
        ).fetchone()[0]
    return {
        "writes": writes,
        "median_ms": round(statistics.median(samples), 4),
        "p95_ms": round(_percentile(samples, 0.95), 4),
        "payload_bytes": len(encoded.encode("utf-8")),
        "database_bytes": path.stat().st_size,
        "encoded": encoded,
    }


def _scan_measure(runs: int) -> dict:
    selections: list[tuple[str, ...]] = []
    samples: list[float] = []
    for seed in range(runs):
        with tempfile.TemporaryDirectory(prefix="agent-core-scan-") as td:
            root = Path(td)
            names = [f"m{index:03d}.py" for index in range(120)]
            random.Random(seed).shuffle(names)
            for name in names:
                (root / name).write_text(
                    f"def target_{name[1:4]}():\n    pass\n",
                    encoding="utf-8",
                )
            started = time.perf_counter_ns()
            iterator, report = scan_files(
                root,
                limits=ScanLimits(
                    max_files=10,
                    max_bytes=0,
                    max_file_bytes=0,
                    max_elapsed=0,
                    max_considered=1_000,
                    max_visited=1_000,
                ),
                extensions={".py"},
                priority=True,
            )
            selections.append(tuple(path.name for path in iterator))
            samples.append((time.perf_counter_ns() - started) / 1_000_000)
            assert report.extra.get("priority_policy") == "bounded_top_k_v1"
    return {
        "runs": runs,
        "unique_prefixes": len(set(selections)),
        "all_prefixes_equal": len(set(selections)) == 1,
        "selected_prefix": list(selections[0]) if selections else [],
        "median_ms": round(statistics.median(samples), 4),
        "p95_ms": round(_percentile(samples, 0.95), 4),
    }


def _reduction(before: int, after: int) -> float:
    return round(100.0 * (before - after) / before, 2) if before else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--writes", type=int, default=200)
    parser.add_argument("--cpu-iterations", type=int, default=1_000)
    parser.add_argument("--scan-runs", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    prefixed_secret = "ghp_" + "A" * 32
    opaque_secret = "opaque-secret-value-7d9e2c"
    body = (
        "print('hello')\n"
        + "x" * 50_000
        + f"\nTOKEN={prefixed_secret}\n"
    )
    payload = {
        "tool_name": "write_file",
        "args": {
            "path": "app.py",
            "content": body,
            "api_key": opaque_secret,
        },
    }

    small_payload = {
        "status": "passed",
        "kind": "test",
        "scope": "full",
        "exit_code": 0,
        "path": "src/example.py",
    }

    raw_encode = _timed(
        args.cpu_iterations,
        lambda: json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )
    safe_encode = _timed(
        args.cpu_iterations,
        lambda: json.dumps(
            sanitize_event_payload("tool.intent", payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    raw_small_encode = _timed(
        args.cpu_iterations,
        lambda: json.dumps(
            small_payload, ensure_ascii=False, sort_keys=True
        ),
    )
    safe_small_encode = _timed(
        args.cpu_iterations,
        lambda: json.dumps(
            sanitize_event_payload("verification.updated", small_payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )

    with tempfile.TemporaryDirectory(prefix="agent-core-journal-") as td:
        root = Path(td)
        before = _journal_run(
            root / "before.db",
            "tool.intent",
            payload,
            args.writes,
            unsafe_reference=True,
        )
        after = _journal_run(
            root / "after.db",
            "tool.intent",
            payload,
            args.writes,
            unsafe_reference=False,
        )
        small_before = _journal_run(
            root / "small-before.db",
            "verification.updated",
            small_payload,
            args.writes,
            unsafe_reference=True,
        )
        small_after = _journal_run(
            root / "small-after.db",
            "verification.updated",
            small_payload,
            args.writes,
            unsafe_reference=False,
        )

        result = {
            "workload": {
                "journal_writes": args.writes,
                "tool_body_characters": len(body),
                "sanitizer_iterations": args.cpu_iterations,
                "scan_runs": args.scan_runs,
            },
            "sanitizer_cpu": {
                "body_heavy_tool_intent": {
                    "unsafe_json_only": raw_encode,
                    "safe_shape_redact_json": safe_encode,
                    "median_delta_us": round(
                        safe_encode["median_us"] - raw_encode["median_us"], 3
                    ),
                },
                "small_verification_event": {
                    "unsafe_json_only": raw_small_encode,
                    "safe_redact_json": safe_small_encode,
                    "median_delta_us": round(
                        safe_small_encode["median_us"]
                        - raw_small_encode["median_us"],
                        3,
                    ),
                },
            },
            "journal": {
                "before": {key: value for key, value in before.items() if key != "encoded"},
                "after": {key: value for key, value in after.items() if key != "encoded"},
                "payload_byte_reduction_percent": _reduction(
                    before["payload_bytes"], after["payload_bytes"]
                ),
                "database_byte_reduction_percent": _reduction(
                    before["database_bytes"], after["database_bytes"]
                ),
                "before_contains_body": "x" * 1_000 in before["encoded"],
                "after_contains_body": "x" * 1_000 in after["encoded"],
                "before_contains_prefixed_secret": prefixed_secret in before["encoded"],
                "after_contains_prefixed_secret": prefixed_secret in after["encoded"],
                "before_contains_opaque_secret": opaque_secret in before["encoded"],
                "after_contains_opaque_secret": opaque_secret in after["encoded"],
                "small_event": {
                    "before": {
                        key: value
                        for key, value in small_before.items()
                        if key != "encoded"
                    },
                    "after": {
                        key: value
                        for key, value in small_after.items()
                        if key != "encoded"
                    },
                    "median_delta_ms": round(
                        small_after["median_ms"] - small_before["median_ms"],
                        4,
                    ),
                },
            },
            "priority_scan": _scan_measure(args.scan_runs),
            "model_api_cost": {
                "provider_calls_made_by_benchmark": 0,
                "provider_tokens_used_by_benchmark": 0,
                "provider_cost_usd": 0.0,
                "claim": (
                    "Persistence hardening does not change model prompts, "
                    "model tokens, or provider pricing."
                ),
            },
        }

    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
