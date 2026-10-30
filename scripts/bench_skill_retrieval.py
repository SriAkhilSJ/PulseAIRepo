#!/usr/bin/env python3
"""Benchmark how the agent actually retrieves a skill — and a capability.

Two retrieval stories, one harness:

  skills (we own them)
    0 calls  — planning injection: the right book is already in the prompt
    1 call   — skill_bundle(task) / skill_view("a, b")
    n calls  — browse: skills_list -> skills_list(shelf) -> skill_view

  MCP (third party, cannot be precomputed)
    flat     — the three meta-tool schemas, whatever the server count
    1 call   — mcp_tools(server) for names, mcp_tools(server, query) for a schema
    1 call   — mcp_call(server, tool, args) on a pooled session

Run:  python scripts/bench_skill_retrieval.py [--json] [--mcp-tools N]
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


# -- MCP: the other half of retrieval --------------------------------------
# Skills are zero-call because we own them. A third-party server's tools cannot
# be precomputed, so MCP has a different question to answer: what does a
# workspace with N server tools cost per turn, and what does one capability cost
# to reach? Measured here so both halves are read off the same harness.

_MCP_SERVER = r'''
import json, sys
N = __COUNT__
TOOLS = [{"name": "tool_%d" % i,
          "description": ("Does the %d-th thing on this server, with a description "
                          "long enough to look like a real third-party tool." % i),
          "inputSchema": {"type": "object",
                          "properties": {"arg": {"type": "string", "description": "input"}}},
          "annotations": {"readOnlyHint": i % 2 == 0}} for i in range(N)]
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    m = req.get("method")
    if m == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "bench", "version": "0"}}}), flush=True)
    elif m == "notifications/initialized":
        pass
    elif m == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"tools": TOOLS}}), flush=True)
    elif m == "tools/call":
        print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {
            "content": [{"type": "text", "text": "ok"}]}}), flush=True)
'''


def bench_mcp(tool_count: int = 40) -> dict:
    """Cost and latency of reaching a third-party capability."""
    import tempfile

    from src.tools.mcp_client import close_all, mcp_config_path, server_tools

    try:
        from src.tools.mcp_tool import MCP_TOOLS, mcp_call, mcp_servers, mcp_tools
        try:
            from langchain_core.utils.function_calling import convert_to_openai_tool
            schema_json = json.dumps([convert_to_openai_tool(t) for t in MCP_TOOLS])
        except Exception:
            schema_json = json.dumps([{"name": t.name, "description": t.description}
                                      for t in MCP_TOOLS])
    except Exception as exc:  # MCP must never break the skills bench
        return {"error": f"{type(exc).__name__}: {exc}"}

    ws = tempfile.mkdtemp()
    script = pathlib.Path(ws) / "bench_server.py"
    script.write_text(_MCP_SERVER.replace("__COUNT__", str(tool_count)), encoding="utf-8")
    cfg = mcp_config_path(ws)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"servers": {"bench": {
        "command": sys.executable, "args": [str(script)], "enabled": True}}}), encoding="utf-8")
    config = {"configurable": {"workspace": ws, "tool_phase": "agent"}}

    def timed(fn, args=None):
        started = time.perf_counter()
        text = fn.invoke(args or {}, config)
        return text, (time.perf_counter() - started) * 1000

    try:
        _, ms_servers = timed(mcp_servers)
        listing, ms_cold = timed(mcp_tools, {"server": "bench"})
        _, ms_warm = timed(mcp_tools, {"server": "bench"})
        one_schema, _ = timed(mcp_tools, {"server": "bench", "query": "tool_17", "limit": 2})
        called, ms_call = timed(mcp_call, {"server": "bench", "tool": "tool_0",
                                           "arguments": {}, "confirm": True})
        bound_directly = json.dumps(server_tools(ws, "bench"))
        report = {
            "meta_tools": len(MCP_TOOLS),
            "meta_schema_tokens": TOK(len(schema_json)),
            "server_tools": tool_count,
            "listing_tokens": TOK(len(listing)),
            "one_schema_tokens": TOK(len(one_schema)),
            "bound_directly_tokens": TOK(len(bound_directly)),
            "saving_multiple": round(len(bound_directly) / max(1, len(schema_json)), 1),
            "latency_ms": {
                "servers": round(ms_servers, 1),
                "catalog_cold": round(ms_cold, 1),
                "catalog_warm": round(ms_warm, 1),
                "call": round(ms_call, 1),
            },
            "call_ok": "ok" in called,
        }
    finally:
        try:
            close_all()
        except Exception:
            pass
    return report


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({round(100 * n / d)}%)"


def main() -> int:
    as_json = "--json" in sys.argv
    tool_count = 40
    for i, arg in enumerate(sys.argv):
        if arg == "--mcp-tools" and i + 1 < len(sys.argv):
            tool_count = int(sys.argv[i + 1])

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
                           "bundle": bundle,
                           "injected_first": (injected.split("\n")[2][:80]
                                              if len(injected.split("\n")) > 2
                                              else (injected[:80] or "<empty>"))})

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
        "mcp": bench_mcp(tool_count),
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

    mcp = report.get("mcp") or {}
    if mcp and "error" not in mcp:
        lat = mcp["latency_ms"]
        print(f"\nMCP              {mcp['meta_tools']} meta-tools, {mcp['meta_schema_tokens']} tok of "
              f"schema per turn (flat, whatever the server count)")
        print(f"                 server with {mcp['server_tools']} tools: "
              f"catalog {mcp['listing_tokens']} tok, one schema {mcp['one_schema_tokens']} tok")
        print(f"                 bound directly: {mcp['bound_directly_tokens']} tok every turn "
              f"({mcp['saving_multiple']}x the meta-tools)")
        print(f"                 latency: servers {lat['servers']} ms, catalog "
              f"{lat['catalog_cold']} ms cold / {lat['catalog_warm']} ms warm, call {lat['call']} ms")
    elif mcp:
        print(f"\nMCP              unmeasured: {mcp['error']}")

    print(f"\nmatches/task     {report['matches_per_task']['mean']} mean, {report['matches_per_task']['max']} max "
          "(budget trims the tail)")
    if misses:
        print(f"\nmissed by both paths ({len(misses)}):")
        for m in misses:
            print(f"  {m['task']!r} -> wanted {m['expected']}, bundle gave {m['bundle']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
