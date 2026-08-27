#!/usr/bin/env python3
"""Run one guarded Test-5 agent turn in a fresh external workspace.

The historical credential is read directly from the parent of the security
removal commit and is never printed, written, or passed on the command line.
This wrapper monitors the real bridge runner every 30 seconds.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parent
WORKSPACE = Path("/home/user/test5-workspace-attempt7")
RUN_ID = "test5-7-arena"
RUN_DIR = REPO / "bench-results" / RUN_ID
PROMPT = REPO / "scripts" / "test5_prompt.txt"
KEY_COMMIT = "dce36ddf14978efa1e3e81fbaa398cb76aba65f6"


def historical_key() -> str:
    text = subprocess.check_output(
        ["git", "show", f"{KEY_COMMIT}:README.md"],
        cwd=REPO,
        text=True,
        stderr=subprocess.DEVNULL,
    )
    candidates = re.findall(r"(?m)^CUSTOM_API_KEY=([^\s]+)", text)
    valid = [
        value.strip().strip('"\'')
        for value in candidates
        if len(value.strip().strip('"\'')) >= 30
        and not any(word in value.lower() for word in ("your", "placeholder", "example", "<"))
    ]
    if len(valid) != 1:
        raise RuntimeError(f"expected exactly one historical credential; found {len(valid)}")
    return valid[0]


def frame_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    path = RUN_DIR / "frames.jsonl"
    if not path.exists():
        return counts
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                kind = str(json.loads(line).get("type") or "?")
            except Exception:
                continue
            counts[kind] = counts.get(kind, 0) + 1
    except OSError:
        pass
    return counts


def delivered_files() -> list[Path]:
    if not WORKSPACE.exists():
        return []
    return [path for path in WORKSPACE.rglob("*") if path.is_file()]


def main() -> int:
    if WORKSPACE.exists() or RUN_DIR.exists():
        print("PREFLIGHT_FAIL: fresh workspace or run directory already exists", flush=True)
        return 2
    if not PROMPT.exists():
        print("PREFLIGHT_FAIL: prompt missing", flush=True)
        return 2

    key = historical_key()
    WORKSPACE.mkdir(parents=True)
    env = dict(os.environ)
    env.update({
        "LLM_PROVIDER": "custom",
        "LLM_MODEL": "sarvam-105b-conversations",
        "CUSTOM_BASE_URL": "https://api.sarvam.ai/v1",
        "CUSTOM_API_KEY": key,
        "PULSEAI_BRIDGE_APPROVAL_POLICY": "workspace_session",
        "PULSEAI_AUTO_APPROVE_WRITES": "1",
        "PULSEAI_CAPTURE_REQUEST_PAYLOADS": "1",
        "PULSEAI_LLM_STREAMING": "1",
        "PULSEAI_LLM_TIMEOUT": "280",
        "PULSEAI_DISABLE_LONG_TERM_MEMORY": "1",
    })

    command = [
        sys.executable,
        str(REPO / "scripts" / "run_bridge_turn.py"),
        "--workspace", str(WORKSPACE),
        "--prompt-file", str(PROMPT),
        "--run-id", RUN_ID,
        "--timeout-s", "5280",
        "--max-llm-calls", "20",
        "--max-input-tokens", "180000",
        "--max-no-delivery-calls", "12",
    ]
    print(
        f"START run={RUN_ID} workspace={WORKSPACE} caps=calls:20,input:180000,no-file:12",
        flush=True,
    )
    proc = subprocess.Popen(
        command,
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(f"RUNNER {line.rstrip()}", flush=True)

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    started = time.monotonic()
    monitor_index = 0
    while proc.poll() is None:
        time.sleep(30)
        monitor_index += 1
        files = delivered_files()
        counts = frame_counts()
        print(
            f"MONITOR #{monitor_index} elapsed={time.monotonic()-started:.0f}s "
            f"alive={proc.poll() is None} files={len(files)} bytes={sum(p.stat().st_size for p in files)} "
            f"llm={counts.get('llm.request', 0)} tools={counts.get('tool_call_start', 0)} "
            f"done={counts.get('turn_done', 0)} failed={counts.get('turn_failed', 0)}",
            flush=True,
        )
    thread.join(timeout=5)
    files = delivered_files()
    counts = frame_counts()
    print(
        f"EXIT code={proc.returncode} files={len(files)} bytes={sum(p.stat().st_size for p in files)} "
        f"frames={json.dumps(counts, sort_keys=True)}",
        flush=True,
    )
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
