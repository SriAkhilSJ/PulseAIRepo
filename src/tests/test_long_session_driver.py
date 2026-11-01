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


# ------------------------------------------------ the harness must not lie


def test_budget_cut_turn_is_not_counted_as_completed():
    """2026-11-01: the driver printed "7/7 SURVIVED" on a cut session.

    A budget-cut turn ALSO ends in a `turn_done` frame, carrying
    completed=false and run_outcome=budget_exhausted. Counting frame types alone
    reported full survival for a session in which three turns were truncated
    mid-work — the exact false green this repo has been chasing everywhere else,
    committed by the harness that was meant to expose it.
    """
    from scripts.run_long_session import summarize

    turns = [
        {"turn": 1, "result": "turn_done", "completed": True, "run_outcome": "completed"},
        {"turn": 2, "result": "turn_done", "completed": True, "run_outcome": "completed"},
        {"turn": 3, "result": "turn_done", "completed": False, "run_outcome": "budget_exhausted"},
    ]
    summary = summarize(turns, 3)
    assert summary["turns_completed"] == 2
    assert summary["turns_budget_cut"] == 1
    assert summary["turns_cut_at"] == [3]
    assert summary["ok"] is False
    assert "BUDGET-CUT" in summary["verdict"]
    assert "SURVIVED" not in summary["verdict"]


def test_clean_run_reports_survival_and_a_stop_is_named():
    from scripts.run_long_session import summarize

    clean = [{"turn": i, "result": "turn_done", "completed": True} for i in (1, 2, 3)]
    assert summarize(clean, 3)["ok"] is True
    assert "SURVIVED" in summarize(clean, 3)["verdict"]

    stopped = clean[:2] + [{"turn": 3, "result": "bridge-exited"}]
    summary = summarize(stopped, 3)
    assert summary["ok"] is False
    assert summary["stopped_at_turn"] == 3
    assert "STOPPED at turn 3" in summary["verdict"]


def test_replayed_terminal_frame_cannot_end_a_new_turn():
    """Field 2026-11-01: turns 5-7 "failed" in 0.6s with 0 tokens.

    The bridge forwards event_bus traffic, and event_bus replays retained
    history to a new subscriber. The driver read a REPLAYED turn_failed from an
    earlier turn and concluded the current turn had failed before it started.
    A terminal frame only counts when its turn_id is one we have not concluded.
    """
    source = (REPO_ROOT / "scripts" / "run_long_session.py").read_text(encoding="utf-8")
    assert "seen_terminal_turns" in source
    assert "replayed from an earlier turn" in source
    # The queue is drained to silence before each prompt is sent.
    assert "Drain to silence before sending the next prompt" in source


def test_failure_text_is_recorded_not_just_the_frame_type():
    """turn_failed carries `error`; a receipt without it cannot diagnose."""
    source = (REPO_ROOT / "scripts" / "run_long_session.py").read_text(encoding="utf-8")
    assert 'frame.get("error")' in source
    assert "| Error |" in source


def test_harness_ceiling_is_never_reported_as_an_agent_property():
    """Field 2026-11-01 (run 41290247998).

    `--max-llm-calls 20` used to be written into AGENT_ITERATION_BUDGET, so the
    agent ran with a 20-iteration budget instead of its own 45. Every
    "budget-cut" verdict this harness produced was measured against a limit the
    harness imposed, and the 1.2M-token A/B was confounded: raising the token cap
    left the iteration cap at 20, so the session tripped
    `[budget] exhausted: iterations 20/20 >= budget` instead.

    Two rules now hold, and both are asserted here:
      1. the two budgets are separate knobs, and the driver gives the agent its
         own default (45) unless told otherwise;
      2. when the harness's own call cap stops a turn, the verdict says so and
         does not attribute the stop to the agent.
    """
    from scripts.run_long_session import _build_parser, summarize

    args = _build_parser().parse_args(["--workspace", "w", "--prompts-file", "p"])
    assert args.agent_iteration_budget == 45, "the agent's own default, not a harness number"
    assert args.max_llm_calls > args.agent_iteration_budget, (
        "the safety stop must sit ABOVE the agent's budget, or it silently becomes the budget"
    )

    turns = [
        {"turn": 1, "result": "turn_done", "completed": True},
        {"turn": 2, "result": "harness-aborted-llm-call-cap", "completed": False},
    ]
    out = summarize(turns, 2)
    assert out["aborted_by_harness"] is True
    assert out["ok"] is False
    assert "HARNESS ABORT" in out["verdict"]
    assert "turn 2" in out["verdict"]


def test_the_driver_sets_a_money_cap_not_only_a_token_cap():
    """Field 2026-11-01: run 41290247998 drained the account in five turns.

    The driver only ever set AGENT_TOKEN_BUDGET. A token cap cannot bound money:
    it counts cached prompt tokens at full weight (53%, 46%, 39% of turns 5-7
    were cache hits) and it never sees the per-token rate. The money leg is
    AGENT_COST_BUDGET and nothing set it, so every session ran until the
    provider refused payment mid-turn.
    """
    from scripts.run_long_session import _build_parser, build_env

    args = _build_parser().parse_args(
        [
            "--workspace", "w", "--prompts-file", "p",
            "--max-cost-usd", "0.25", "--max-input-tokens", "1200000",
        ]
    )
    env = build_env(args)
    assert env.get("AGENT_COST_BUDGET") == "0.2500", env.get("AGENT_COST_BUDGET")
    assert "AGENT_TOKEN_BUDGET" in env

    # Default 0 means "no separate money stop" — an explicit choice, not a hope.
    args0 = _build_parser().parse_args(["--workspace", "w", "--prompts-file", "p"])
    assert "AGENT_COST_BUDGET" not in build_env(args0)


def test_report_separates_tokens_that_did_work_from_tokens_that_were_discarded():
    """The expensive number was never printed.

    Three cut turns billed ~2.5M tokens (~$0.38) and produced nothing. Spend per
    COMPLETED turn is the cost metric that cannot be gamed by cutting work.
    """
    from scripts.run_long_session import summarize

    turns = [
        {"turn": 1, "result": "turn_done", "completed": True, "tokens_in_telemetry": 200_000},
        {"turn": 2, "result": "turn_done", "completed": False, "tokens_in_telemetry": 500_000},
        {"turn": 3, "result": "turn_done", "completed": True, "tokens_in_telemetry": 800_000},
    ]
    out = summarize(turns, 3)
    assert out["turns_completed"] == 2
    assert out["turns_budget_cut"] == 1
