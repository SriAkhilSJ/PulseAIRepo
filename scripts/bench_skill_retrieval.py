#!/usr/bin/env python3
"""Benchmark how the agent actually retrieves a skill.

Measures the three retrieval paths the library offers and prints the numbers the
design decisions were made from:

  0 calls  — planning injection: the right book is already in the prompt
  1 call   — skill_bundle(task) / skill_view("a, b")
  n calls  — browse: skills_list -> skills_list(shelf) -> skill_view

Run:  python scripts/bench_skill_retrieval.py [--json]
"""

from __future__ import annotations

import json
import pathlib
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.agents.skill_manager import SkillManager  # noqa: E402
from src.mcp_skills.index import SkillIndex  # noqa: E402

# task -> the book a good architect would open first
CASES: list[tuple[str, str]] = [
    ("kafka consumer lag is growing", "kafka-architect"),
    ("terraform state file is corrupted", "terraform-architect"),
    ("our lambda keeps timing out", "lambda-architect"),
    ("design a rest api for partners", "rest-architect"),
    ("postgres query is slow on a big table", "postgres-architect"),
    ("dbt model has duplicate rows", "dbt-architect"),
    ("airflow dag is stuck in backfill", "airflow-architect"),
    ("should we use snowflake or iceberg", "iceberg-architect"),
    ("kubernetes pods evicted on memory pressure", "kubernetes-architect"),
    ("aws bill doubled last month", "cost-optimization-architect"),
    ("redis cache hit rate is falling", "redis-architect"),
    ("which model should we use for support", "model-selection-architect"),
    ("prompt injection through support tickets", "prompting-architect"),
    ("vector search returns irrelevant chunks", "vector-store-architect"),
    ("fine tune or use rag", "fine-tuning-architect"),
    ("our evals do not catch regressions", "evals-architect"),
    ("react app rerenders on every keystroke", "react-core-architect"),
    ("nextjs page is slow on first load", "nextjs-architect"),
    ("django migrations on a live database", "django-architect"),
    ("graphql n+1 problem", "graphql-architect"),
    ("electron app needs a secure preload bridge", "desktop-ipc-architect"),
    ("windows installer requires admin rights", "desktop-distribution-architect"),
    ("mac app should feel native", "native-feel-architect"),
    ("linux app should ship as flatpak", "gtk-architect"),
    ("flutter app crashes on android release build", "flutter-architect"),
    ("app must work offline in the field", "mobile-offline-sync-architect"),
    ("ios app needs a widget", "ios-swiftui-architect"),
    ("push notifications are not delivered", "push-notifications-architect"),
    ("our screen reader can't read the desktop app", "desktop-accessibility-architect"),
    ("app store rejects our update", "mobile-release-architect"),
]

TOK = lambda chars: round(chars / 3.8)  # noqa: E731 - BPE vocab unavailable offline


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({round(100 * n / d)}%)"


def main() -> int:
    as_json = "--json" in sys.argv

    t0 = time.perf_counter()
    manager = SkillManager()
    build_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    index = SkillIndex.build()
    index_ms = (time.perf_counter() - t0) * 1000

    zero_hits = three_hits = one_hits = 0
    zero_chars: list[int] = []
    spread: list[int] = []
    latencies: list[float] = []
    misses: list[dict] = []

    for task, expected in CASES:
        # 0 calls: planning injection
        t = time.perf_counter()
        injected = manager.get_skills_text(task, phase="planning")
        latencies.append((time.perf_counter() - t) * 1000)
        zero_chars.append(len(injected))
        in_zero = expected in injected
        zero_hits += in_zero

        # 1 call: bundle of three
        bundle = [b["name"] for b in index.bundle(task, limit=3)]
        in_three = expected in bundle
        three_hits += in_three

        # 1 call: ranked search, top 1
        hits = index.search(task, limit=1)
        in_one = bool(hits and hits[0]["name"] == expected)
        one_hits += in_one

        spread.append(len(manager.ranked_for_task(task, phase="planning")))
        if not (in_zero or in_three):
            misses.append({"task": task, "expected": expected,
                           "bundle": bundle, "injected_first": injected.split("\n")[2][:80]})

    book_chars = [len(b.body) for b in index.books.values() if b.is_architect]

    report = {
        "cases": len(CASES),
        "zero_call": {"hit": zero_hits, "token_cost": TOK(statistics.mean(zero_chars))},
        "bundle_top3": {"hit": three_hits},
        "search_top1": {"hit": one_hits},
        "latency_ms": {
            "skill_manager_build": round(build_ms, 1),
            "index_build": round(index_ms, 1),
            "injection_mean": round(statistics.mean(latencies), 2),
            "injection_max": round(max(latencies), 2),
        },
        "costs_tokens": {
            "catalog_entry_per_book": TOK(statistics.mean([len(b.description) + len(b.name) for b in index.books.values()])),
            "catalog_whole_library": TOK(sum(len(b.description) + len(b.name) for b in index.books.values())),
            "one_book": TOK(statistics.mean(book_chars)),
            "three_books": TOK(3 * statistics.mean(book_chars)),
            "injected_planning_mean": TOK(statistics.mean(zero_chars)),
        },
        "matches_per_task": {
            "mean": round(statistics.mean(spread), 1),
            "max": max(spread),
        },
        "misses": misses,
    }

    if as_json:
        print(json.dumps(report, indent=1))
        return 0

    print(f"corpus           {len(index.books)} skills ({sum(1 for b in index.books.values() if b.is_architect)} architect)")
    print(f"build            SkillManager {build_ms:.0f} ms   index {index_ms:.0f} ms  (once per process)\n")
    print(f"cases            {len(CASES)} realistic tasks")
    print(f"  0 calls        {pct(zero_hits, len(CASES)):>14}  target book already in the planning prompt")
    print(f"  1 call bundle  {pct(three_hits, len(CASES)):>14}  skill_bundle(task) returns it in the top 3")
    print(f"  1 call search  {pct(one_hits, len(CASES)):>14}  skills_search ranks it first\n")
    print(f"latency          injection {report['latency_ms']['injection_mean']} ms mean / "
          f"{report['latency_ms']['injection_max']} ms max\n")
    print("token cost       catalog entry (1 book)      {:>6}".format(report["costs_tokens"]["catalog_entry_per_book"]))
    print("                 whole catalog (240)        {:>6}".format(report["costs_tokens"]["catalog_whole_library"]))
    print("                 one book                   {:>6}".format(report["costs_tokens"]["one_book"]))
    print("                 three books                {:>6}".format(report["costs_tokens"]["three_books"]))
    print("                 planning injection (mean)  {:>6}  <- the 0-call path".format(report["costs_tokens"]["injected_planning_mean"]))
    print(f"\nmatches/task     {report['matches_per_task']['mean']} mean, {report['matches_per_task']['max']} max "
          "(budget trims the tail)")
    if misses:
        print(f"\nmissed by both paths ({len(misses)}):")
        for m in misses:
            print(f"  {m['task']!r} -> wanted {m['expected']}, bundle gave {m['bundle']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
