"""The long-session driver: one session, many turns.

Every other harness in this repo creates a fresh session per run, so "can the
agent keep going?" was never measured — every green result was a first turn
with an empty history. These tests pin the properties that make the new driver
answer that question honestly:

  1. prompts are parsed into discrete turns;
  2. ONE session_create is issued, and every prompt reuses that session id —
     a driver that silently minted a new session per prompt would "survive"
     forever while proving nothing;
  3. a real bridge round-trip produces a per-turn receipt.

The functional test uses the bridge's echo runner, so it costs nothing and
never touches a provider.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_prompts_split_into_turns(tmp_path):
    from scripts.run_long_session import load_prompts

    path = tmp_path / "prompts.txt"
    path.write_text("first turn\n---\nsecond turn\n---\n\nthird turn\n", encoding="utf-8")
    assert load_prompts(path) == ["first turn", "second turn", "third turn"]


def test_shipped_prompt_file_is_a_real_sequence():
    from scripts.run_long_session import load_prompts

    prompts = load_prompts(REPO_ROOT / "tests" / "e2e" / "prompts_session.txt")
    assert len(prompts) >= 6, "a stamina test needs more than a couple of turns"
    # Each turn should ask for verifiable work, not chatter.
    assert all("test_server.py" in p or "README" in p for p in prompts), \
        "every turn must end in something checkable"


def test_driver_uses_one_session_for_every_turn():
    source = (REPO_ROOT / "scripts" / "run_long_session.py").read_text(encoding="utf-8")
    # One session_create, outside the per-turn loop.
    assert source.count('"type": "session_create"') == 1
    create_at = source.index('"type": "session_create"')
    loop_at = source.index("for index, prompt in enumerate(prompts):")
    assert create_at < loop_at, "session_create must happen once, before the turns"


def test_driver_survives_a_multi_turn_round_trip(tmp_path):
    """Functional: 3 prompts down one session against the echo runner."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    results = tmp_path / "results"
    prompts = tmp_path / "prompts.txt"
    prompts.write_text("one\n---\ntwo\n---\nthree\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "scripts/run_long_session.py",
         "--workspace", str(workspace),
         "--prompts-file", str(prompts),
         "--turns", "3",
         "--timeout-s-per-turn", "60",
         "--max-session-minutes", "5",
         "--results-root", str(results)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300,
        env=dict(os.environ, CRUSORAI_BRIDGE_RUNNER="echo", PYTHONUNBUFFERED="1"),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    receipt = json.loads(next(results.glob("*/long_session.json")).read_text())
    assert receipt["turns_completed"] == receipt["turns_attempted"] == 3
    assert receipt["stopped_at_turn"] is None
    assert [t["turn"] for t in receipt["turns"]] == [1, 2, 3]
    assert receipt["session_id"].startswith("t5-")
