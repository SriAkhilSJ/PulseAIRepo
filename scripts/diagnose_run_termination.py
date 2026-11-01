#!/usr/bin/env python3
"""Why did each agent run end? — trace termination classifier.

Reads step traces (~/.crusorai/traces/*.jsonl and diagnostics/**/traces/*.jsonl)
and classifies the terminal state of every session, so a failed run can be
explained after the fact instead of guessed at.

    python3 scripts/diagnose_run_termination.py
    python3 scripts/diagnose_run_termination.py --session session-<id>
    python3 scripts/diagnose_run_termination.py --json

Exit codes: 0 all runs reached a terminal node, 1 at least one run ended
mid-graph (no terminal receipt).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field

TRACE_GLOBS = tuple(
    g for g in (
        # CRUSORAI_HOME wins: CI and lab runs relocate the store, and a
        # classifier that silently reads the wrong directory reports "no
        # traces" instead of "no terminal nodes".
        (os.path.join(os.environ["CRUSORAI_HOME"], "traces", "*.jsonl")
         if os.environ.get("CRUSORAI_HOME") else None),
        os.path.expanduser("~/.crusorai/traces/*.jsonl"),
        "diagnostics/**/traces/*.jsonl",
        "diagnostics/traces/*.jsonl",
    )
    if g
)

# Nodes that are legitimate terminal states of one turn.
TERMINAL_NODES = frozenset({"finalize", "recovery_limit", "tool_cycle_limit",
                            "plan_preview", "plan_cancelled", "approval_without_plan",
                            "turn_terminal"})
# Nodes that mean the process stopped mid-flight.
MIDGRAPH_NODES = frozenset({"ai", "tools", "progress", "planner", "finish_gate",
                            "pivot", "plan_reviser", "task_manager"})


@dataclass
class RunVerdict:
    path: str
    session: str = ""
    ai_calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    last_node: str = ""
    terminal_node: str | None = None
    verdict: str = ""
    cache_reported: int = 0
    cache_misses: int = 0
    nodes: Counter = field(default_factory=Counter)


def _load(path: str) -> list[dict]:
    events = []
    try:
        with open(path, errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("node_name"):
                    events.append(ev)
    except OSError:
        pass
    return events


def classify(path: str) -> RunVerdict:
    events = _load(path)
    v = RunVerdict(path=path, session=os.path.basename(path).replace(".jsonl", ""))
    for ev in events:
        node = ev.get("node_name", "")
        v.nodes[node] += 1
        if node == "ai":
            v.ai_calls += 1
            v.tokens += int(ev.get("input_tokens") or 0) + int(ev.get("output_tokens") or 0)
            v.cost_usd += float(ev.get("estimated_cost_usd") or 0.0)
            if ev.get("cache_reported"):
                v.cache_reported += 1
                if float(ev.get("cache_hit_ratio") or 0.0) < 0.5:
                    v.cache_misses += 1
    if not events:
        v.verdict = "no-trace-data"
        return v
    v.last_node = events[-1].get("node_name", "")
    for ev in reversed(events):
        if ev.get("node_name") in TERMINAL_NODES:
            v.terminal_node = ev["node_name"]
            break

    if v.terminal_node:
        v.verdict = f"terminal:{v.terminal_node}"
    elif v.last_node in MIDGRAPH_NODES:
        # The distinguishing fact: the run stopped with no terminal receipt,
        # so nothing recorded WHY. Candidates: cancel, crash, provider death,
        # or a wall-clock kill outside the graph.
        v.verdict = f"UNEXPLAINED:stops-on:{v.last_node}"
    else:
        v.verdict = f"unknown-node:{v.last_node}"
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="filter to sessions containing this substring")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--top", type=int, default=0, help="show only the N most expensive runs")
    args = ap.parse_args()

    seen: set[str] = set()
    paths: list[str] = []
    for pattern in TRACE_GLOBS:
        for p in glob.glob(pattern, recursive=True):
            real = os.path.realpath(p)
            if real in seen:
                continue
            seen.add(real)
            paths.append(p)

    verdicts = [classify(p) for p in paths]
    verdicts = [v for v in verdicts if v.ai_calls > 0]
    if args.session:
        verdicts = [v for v in verdicts if args.session in v.session]
    verdicts.sort(key=lambda v: v.cost_usd, reverse=True)
    if args.top:
        verdicts = verdicts[: args.top]

    if args.json:
        print(json.dumps([v.__dict__ | {"nodes": dict(v.nodes)} for v in verdicts], indent=2,
                         default=str))
        return 0

    unexplained = [v for v in verdicts if v.verdict.startswith("UNEXPLAINED")]
    print(f"traces analysed: {len(verdicts)}")
    print(f"total spend:     ${sum(v.cost_usd for v in verdicts):,.4f}")
    print(f"no terminal:     {len(unexplained)}/{len(verdicts)} "
          f"({100 * len(unexplained) / max(len(verdicts), 1):.0f}%)\n")
    print(f"{'AI':>3} {'tokens':>9} {'cost$':>7} {'cache':>9}  verdict / session")
    print("-" * 96)
    for v in verdicts:
        cache = (f"{v.cache_reported - v.cache_misses}/{v.cache_reported}"
                 if v.cache_reported else "unreported")
        print(f"{v.ai_calls:>3} {v.tokens:>9,} {v.cost_usd:>7.3f} {cache:>9}  "
              f"{v.verdict:<28} {v.session[:34]}")

    print("\nnode coverage across all traces:")
    total_nodes: Counter = Counter()
    for v in verdicts:
        total_nodes.update(v.nodes)
    for node, count in total_nodes.most_common():
        print(f"  {count:>6}  {node}")

    return 1 if unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
