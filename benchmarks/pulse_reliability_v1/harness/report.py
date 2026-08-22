"""Report card: aggregate benchmark results into the founder-facing one-pager.

Turns raw result JSONs into a single markdown page with:
- per-task outcome + check coverage per lane;
- the four axes that matter to the product: latency, performance (context
  bounds), cost (calls/tokens/$), durability (cancels, process hygiene);
- an honest "what this run proves / does not prove" section keyed to the
  lanes that were actually used.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.pulse_reliability_v1.contract import load_suite
from benchmarks.pulse_reliability_v1.harness.orchestrator import DEFAULT_SUITE

TASK_TITLES: dict[str, str] = {}


def _load_results(results_dir: str | Path) -> list[dict]:
    out: list[dict] = []
    root = Path(results_dir)
    if root.is_file():
        return [json.loads(root.read_text(encoding="utf-8"))]
    for path in sorted(root.rglob("result.json")):
        out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def _suite_info(suite_path: str | Path) -> dict[str, tuple[str, bool]]:
    """task id -> (title, model_calls_allowed). Falls back to titles only."""
    try:
        suite = load_suite(suite_path)
        return {t.id: (t.title, bool(t.model_calls_allowed)) for t in suite.tasks}
    except Exception:
        return {tid: (title, True) for tid, title in TASK_TITLES.items()}


def render_report(results_dir: str | Path, *, suite_path: str | Path = DEFAULT_SUITE) -> str:
    results = _load_results(results_dir)
    suite_info = _suite_info(suite_path)
    titles = {tid: info[0] for tid, info in suite_info.items()}
    lines: list[str] = [
        "# PulseAI — Reliability Benchmark Report Card",
        "",
        f"- **Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **Runs graded:** {len(results)}",
        f"- **Rule:** belief is not evidence — every row below was graded by the "
        f"evaluator, never by the agent itself.",
        "",
    ]

    if not results:
        lines += ["_No runs found._", ""]
        return "\n".join(lines) + "\n"

    commits = sorted({r.get("pulse_commit", "?") for r in results})
    lanes = sorted({_lane_of(r) for r in results})
    lines += [
        f"- **Pulse commits:** {', '.join(commits[:3])}",
        f"- **Lanes used:** {', '.join(lanes)}",
        "",
        "## Task outcomes",
        "",
        "| Task | Outcome | Checks | Covered | Lane |",
        "|---|---|---|---|---|",
    ]
    for result in results:
        task_id = result.get("task_id", "?")
        checks = result.get("checks", [])
        passed = sum(1 for c in checks if c.get("classification") == "passed")
        not_run = sum(1 for c in checks if c.get("classification") == "not_run")
        checks_cell = f"{passed}/{len(checks)}"
        if not_run:
            checks_cell += f" ({not_run} not run on lane)"
        title = titles.get(task_id, task_id)
        hard = result.get("hard_failure")
        outcome = result.get("outcome", "?")
        if hard:
            outcome = f"{outcome} (⚠ {hard})"
        lines.append(
            f"| {task_id} {title} | {outcome} | {checks_cell} | "
            f"{result.get('checks_covered', '?')} | {_lane_of(result)} |"
        )

    lines += [
        "",
        "## The four axes (per run)",
        "",
        "| Task | First token (ms) | Completion (ms) | Model calls | Tool calls | "
        "In/out/cache tokens | Est. $ |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in results:
        task_id = result.get("task_id", "?")
        timing = result.get("timing_ms", {})
        usage = result.get("usage", {})
        startup = int(timing.get("startup", 0) or 0)
        ft = int(timing.get("first_token", 0) or 0)
        comp = int(timing.get("completion", 0) or 0)
        ft_elapsed = (ft - startup) if (ft and startup) else ft
        comp_elapsed = (comp - startup) if (comp and startup) else comp
        lines.append(
            f"| {task_id} | {ft_elapsed} | {comp_elapsed} | "
            f"{usage.get('model_calls', 0)} | {usage.get('tool_calls', 0)} | "
            f"{usage.get('input_tokens', 0)}/{usage.get('output_tokens', 0)}/"
            f"{usage.get('cache_tokens', 0)} | {usage.get('estimated_cost_usd', 0.0):.4f} |"
        )

    lines += _pending_section(suite_info, results)
    lines += _honest_claims(results, lanes)
    return "\n".join(lines) + "\n"


def _lane_of(result: dict) -> str:
    lane = result.get("lane", "?")
    if result.get("mock"):
        lane = f"{lane} (mock)"
    return lane


def _pending_section(suite_info: dict[str, tuple[str, bool]],
                     results: list[dict]) -> list[str]:
    """List suite tasks that have no run in this batch, with the reason."""
    run_ids = {r.get("task_id") for r in results}
    pending = [tid for tid in suite_info if tid not in run_ids]
    if not pending:
        return []
    lines = ["", "## Not yet run", ""]
    for tid in sorted(pending):
        title, model_allowed = suite_info[tid]
        reason = "needs provider key" if model_allowed else "needs live engine/desktop lane"
        lines.append(f"- **{tid}** {title} — *{reason}*")
    lines.append("")
    return lines


def _honest_claims(results: list[dict], lanes: list[str]) -> list[str]:
    """State exactly what the report does and does not prove."""
    lines = ["", "## What this run proves (and does not)", ""]
    all_passed = all(
        r.get("outcome") == "passed" and not r.get("hard_failure") for r in results
    )
    has_live_dom = any(
        r.get("lane") == "cdp" and not r.get("mock") for r in results
    )
    has_mock_dom = any(
        r.get("lane") == "cdp" and r.get("mock") for r in results
    )
    if all_passed and results:
        lines.append("- ✅ **On the lanes used:** every graded task passed its coverable checks.")
    if has_live_dom:
        lines.append("- ✅ Desktop-lane evidence from the **live app** (DOM checks graded).")
    elif has_mock_dom:
        lines.append(
            "- ⚠️ **Desktop-lane DOM evidence is from the CDP integration mock** — it proves "
            "the driver+scenario+evaluator pipeline, not the live app. Re-run on a machine "
            "with the built PulseAI IDE for product evidence."
        )
    else:
        lines.append(
            "- ⚠️ **No desktop-lane (DOM) evidence in this batch** — UI-level checks "
            "(composer disabled state, workspace selector, cancel receipt) are NOT yet "
            "graded. Run `--driver cdp` on a machine with the built PulseAI IDE."
        )
    if not any(r.get("usage", {}).get("model_calls", 0) for r in results):
        lines.append(
            "- ⚠️ **No real model calls in this batch** — latency/cost rows are "
            "pipeline timings, not product latency. Real numbers need the bridge lane "
            "with a configured provider/key."
        )
    if not all_passed:
        failed = [r.get("task_id") for r in results
                  if r.get("outcome") != "passed" or r.get("hard_failure")]
        lines.append(f"- ❌ **Failed/unverified tasks:** {', '.join(failed)} — investigate before any claim.")
    lines += [
        "- **Rule of three:** product claims (\"fast\", \"cheap\", \"reliable\") require "
        "3 consecutive green runs on the same lane.",
        "",
        "_Usage numbers are harness-reported until reconciled against engine "
        "telemetry frames (see docs/CTO_BENCHMARK_REVIEW_PR7.md)._",
    ]
    return lines
