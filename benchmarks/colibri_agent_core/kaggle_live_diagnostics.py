#!/usr/bin/env python3
"""Capture a bounded, redacted status/quota/log snapshot for a Kaggle kernel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = "pulseai-kaggle-live-diagnostics/v1"
_TOKEN_PATTERN = re.compile(r"\bKGAT_[A-Za-z0-9_-]+\b")
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)((?:KAGGLE_(?:API_TOKEN|KEY)|Authorization)\s*[=:]\s*)[^\s,;]+"
)
_ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_JSON_DATA_PATTERN = re.compile(r'(?<!\\)"data"\s*:\s*("(?:\\.|[^"\\])*")')
_HIGHLIGHT_TERMS = (
    '"name": "tool_result_round_trip"',
    '"name": "long_context"',
    '"name": "colibri_endpoint_probe"',
    '"ram_cache_slots_per_layer"',
    '"ram_available_gb"',
    '"vram_budget_bytes"',
    "queue_timeout",
    "CUDA VRAM tier",
    "[qtier]",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    result = str(text)
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    result = _TOKEN_PATTERN.sub("[REDACTED]", result)
    result = _ASSIGNMENT_PATTERN.sub(r"\1[REDACTED]", result)
    return result


def _seconds(value: Any) -> float | None:
    if isinstance(value, timedelta):
        return round(value.total_seconds(), 3)
    return None


def _quota_receipt(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {
        "time_used_seconds": _seconds(getattr(value, "time_used", None)),
        "time_reserved_seconds": _seconds(getattr(value, "time_reserved", None)),
        "total_time_allowed_seconds": _seconds(
            getattr(value, "total_time_allowed", None)
        ),
        "minimum_time_allowed_seconds": _seconds(
            getattr(value, "minimum_time_allowed", None)
        ),
        "has_ever_run": bool(getattr(value, "has_ever_run", False)),
    }


def _decode_chunks(response: Any, max_bytes: int) -> tuple[str, int, int, bool, bool]:
    """Read until EOF/deadline while retaining only a bounded byte suffix."""
    retained = bytearray()
    observed = 0
    truncated = False
    deadline_reached = False
    try:
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            encoded = chunk if isinstance(chunk, bytes) else str(chunk).encode()
            observed += len(encoded)
            retained.extend(encoded)
            overflow = len(retained) - max_bytes
            if overflow > 0:
                del retained[:overflow]
                truncated = True
    except _DeadlineExpired:
        deadline_reached = True
    return (
        bytes(retained).decode("utf-8", errors="replace"),
        len(retained),
        observed,
        truncated,
        deadline_reached,
    )


def _unescape_persisted_suffix(text: str) -> str | None:
    """Peel the outer JSON-string layer from a bounded persisted-log suffix."""
    marker = r"{\"stream_name\""
    start = text.find(marker)
    if start < 0:
        return None
    fragment = text[start:].strip()
    # The retained suffix normally includes the outer JSON string's closing quote.
    # Try a tiny bounded trim so a split escape or response trailer cannot hide all
    # complete records that precede it.
    for trim in range(17):
        candidate = fragment[:-trim] if trim else fragment
        if not candidate:
            break
        candidate = (
            candidate.replace("\r", r"\r").replace("\n", r"\n").replace("\t", r"\t")
        )
        try:
            value = json.loads(f'"{candidate}"')
        except json.JSONDecodeError:
            continue
        if isinstance(value, str):
            return value
    return None


def _decode_structured_log(text: str) -> tuple[str, int]:
    """Recover worker stdout/stderr data fields from a full or suffix JSON body."""
    candidates = [text]
    unescaped = _unescape_persisted_suffix(text)
    if unescaped is not None:
        candidates.append(unescaped)

    best: list[str] = []
    for candidate in candidates:
        records: list[str] = []
        for match in _JSON_DATA_PATTERN.finditer(candidate):
            try:
                value = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, str):
                records.append(value)
        if len(records) > len(best):
            best = records
    return ("".join(best), len(best)) if best else (text, 0)


def _clean_log_tail(text: str, secrets: tuple[str, ...], max_chars: int) -> str:
    clean = _CONTROL_PATTERN.sub("", _ANSI_PATTERN.sub("", text))
    redacted = _redact(clean, secrets)
    lines: list[str] = []
    for original in redacted.splitlines():
        line = original.rstrip()
        if line.startswith("data:"):
            line = line[5:].lstrip()
        if line.startswith(("event:", "id:", "retry:")):
            continue
        if line:
            lines.append(line)
    compact = "\n".join(lines)
    if len(compact) > max_chars:
        marker = "[... bounded prefix omitted ...]\n"
        compact = marker + compact[-(max_chars - len(marker)) :]
    return compact


def _log_highlights(text: str, max_chars: int, radius: int = 1200) -> str:
    """Return merged bounded neighborhoods around actionable runner terms."""
    intervals: list[tuple[int, int]] = []
    for term in _HIGHLIGHT_TERMS:
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                break
            intervals.append((max(0, index - radius), min(len(text), index + radius)))
            start = index + len(term)
    if not intervals:
        return ""
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    chunks = [text[start:end].strip() for start, end in merged]
    result = "\n\n[... next diagnostic neighborhood ...]\n\n".join(chunks)
    if len(result) > max_chars:
        marker = "[... bounded highlights truncated ...]\n"
        result = result[: max_chars - len(marker)] + marker
    return result


class _DeadlineExpired(Exception):
    pass


def _deadline_handler(signum, frame):
    raise _DeadlineExpired("log stream capture deadline reached")


def collect_diagnostics(args: argparse.Namespace) -> dict[str, Any]:
    username = os.environ.get("KAGGLE_USERNAME", "").strip()
    token = (
        os.environ.get("KAGGLE_API_TOKEN") or os.environ.get("KAGGLE_KEY") or ""
    ).strip()
    secrets = (username, token)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "running",
        "captured_at": _utc_now(),
        "kernel": {
            "slug_sha256": hashlib.sha256(args.kernel_slug.encode()).hexdigest(),
            "slug_persisted": False,
        },
        "credentials": {"present": bool(username and token), "persisted": False},
        "session": {},
        "quota": {},
        "log": {},
    }
    if not username or not token:
        receipt.update(
            {
                "status": "failed",
                "error": "Kaggle username or API token is unavailable",
            }
        )
        return receipt

    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        from kagglesdk.kernels.types.kernels_api_service import (
            ApiGetAcceleratorQuotaStatisticsRequest,
            ApiGetKernelSessionLogsStreamRequest,
            ApiGetKernelSessionStatusRequest,
        )

        api = KaggleApi()
        api.authenticate()
        with api.build_kaggle_client() as client:
            status_request = ApiGetKernelSessionStatusRequest()
            status_request.user_name = username
            status_request.kernel_slug = args.kernel_slug
            status_response = (
                client.kernels.kernels_api_client.get_kernel_session_status(
                    status_request
                )
            )
            state = getattr(status_response.status, "name", str(status_response.status))
            receipt["session"] = {
                "status": str(state).lower(),
                "failure_message": _redact(
                    str(status_response.failure_message or ""), secrets
                )[:2000],
            }

            quota_response = (
                client.kernels.kernels_api_client.get_accelerator_quota_statistics(
                    ApiGetAcceleratorQuotaStatisticsRequest()
                )
            )
            receipt["quota"] = {
                "gpu": _quota_receipt(quota_response.gpu_quota),
                "tpu": _quota_receipt(quota_response.tpu_quota),
                "refresh_time": (
                    quota_response.quota_refresh_time.isoformat()
                    if quota_response.quota_refresh_time
                    else None
                ),
            }

            log_request = ApiGetKernelSessionLogsStreamRequest()
            log_request.user_name = username
            log_request.kernel_slug = args.kernel_slug
            log_request.wait_for_logs_url_seconds = min(args.wait_for_logs_seconds, 300)

            old_handler = signal.signal(signal.SIGALRM, _deadline_handler)
            signal.alarm(args.capture_seconds)
            response = None
            raw = ""
            retained = 0
            observed = 0
            truncated = False
            deadline_reached = False
            try:
                response = (
                    client.kernels.kernels_api_client.get_kernel_session_logs_stream(
                        log_request
                    )
                )
                raw, retained, observed, truncated, deadline_reached = _decode_chunks(
                    response, args.max_bytes
                )
            except _DeadlineExpired:
                deadline_reached = True
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
                if response is not None:
                    response.close()

            decoded, records_decoded = _decode_structured_log(raw)
            cleaned = _clean_log_tail(decoded, secrets, args.max_bytes)
            highlights = _log_highlights(cleaned, args.max_highlight_chars)
            tail = _clean_log_tail(decoded, secrets, args.max_tail_chars)
            receipt["log"] = {
                "content_type": (
                    response.headers.get("Content-Type")
                    if response is not None
                    else None
                ),
                "bytes_retained": retained,
                "bytes_observed": observed,
                "retained_suffix": truncated,
                "deadline_reached": deadline_reached,
                "records_decoded": records_decoded,
                "retained_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "highlights": highlights,
                "highlight_chars": len(highlights),
                "tail": tail,
                "tail_chars": len(tail),
            }
            receipt["status"] = "passed" if tail else "partial"
    except BaseException as exc:  # noqa: BLE001 - diagnostic receipt must survive API errors
        receipt.update(
            {
                "status": "failed",
                "error": _redact(f"{type(exc).__name__}: {exc}", secrets)[:2000],
            }
        )
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-slug", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-seconds", type=int, default=30)
    parser.add_argument("--wait-for-logs-seconds", type=int, default=20)
    parser.add_argument("--max-bytes", type=int, default=256 * 1024)
    parser.add_argument("--max-tail-chars", type=int, default=12_000)
    parser.add_argument("--max-highlight-chars", type=int, default=12_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.capture_seconds <= 120:
        raise SystemExit("--capture-seconds must be within 1..120")
    if not 1 <= args.wait_for_logs_seconds <= 300:
        raise SystemExit("--wait-for-logs-seconds must be within 1..300")
    if not 1024 <= args.max_bytes <= 1024 * 1024:
        raise SystemExit("--max-bytes must be within 1024..1048576")
    if not 1000 <= args.max_tail_chars <= 20_000:
        raise SystemExit("--max-tail-chars must be within 1000..20000")
    if not 1000 <= args.max_highlight_chars <= 20_000:
        raise SystemExit("--max-highlight-chars must be within 1000..20000")
    receipt = collect_diagnostics(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[KAGGLE_DIAGNOSTICS] status={receipt['status']}", flush=True)
    return 0 if receipt["status"] in {"passed", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
