#!/usr/bin/env python3
"""Per-turn / per-month cost model, measured from the REAL prompt assembly.

Nothing here is a guess about prompt size: it builds the session's system
prompt through the shipped path (``session.system_prompt_for_session``) and
measures it, then multiplies by the call/turn economics from the graph's own
budget (``src/graphs/budget.py``).

    python scripts/cost_model.py
    python scripts/cost_model.py --calls-per-turn 25 --turns-per-day 100 \
        --price-in 0.30 --price-out 2.40 --cache-read-ratio 0.9
    python scripts/cost_model.py --json

Why this exists: the owner asked "what is the per-month expense". The answer is
dominated by ONE number — the system prompt is re-sent on every provider call,
and (before 2026-10-31) 86% of it was the skills index. This tool prints that
number for the current tree so pricing decisions are made on a measurement.

Tool schemas are measured too (2026-10-31 addition): the graph binds 68
schemas by default = 25,382 tokens re-sent on every call, ~4.3x the whole
system prompt. That is the single biggest line item in a turn, and it was
missing from the first version of this model.

Caveats stated up front:
  * prices are INPUT (list prices move; pass your own with --price-in/--price-out)
  * cache discounts are real but provider-specific; the model takes a
    cache-read ratio and a cache-read multiplier instead of assuming one
  * output tokens are modelled per call (assistant prose + tool-call JSON),
    which is where variance lives
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from langchain_core.messages import SystemMessage  # noqa: E402
from src.context.token_budget import count_tokens  # noqa: E402
from src.prompts.hermes import session as sess  # noqa: E402


def measure_prompt(budget_tokens: str | None) -> dict:
    """Measure the assembled system prompt under a given index budget."""
    if budget_tokens is None:
        os.environ.pop("CRUSORAI_SKILLS_INDEX_MAX_TOKENS", None)
    else:
        os.environ["CRUSORAI_SKILLS_INDEX_MAX_TOKENS"] = str(budget_tokens)
    sess.invalidate_all_sessions()
    try:
        from src.prompts.hermes.skills_index import clear_skills_system_prompt_cache

        clear_skills_system_prompt_cache()
    except Exception:
        pass
    cfg = {
        "configurable": {
            "thread_id": f"cost-model-{budget_tokens}",
            "provider": os.environ.get("LLM_PROVIDER", "openai"),
            "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            "workspace": str(REPO_ROOT),
        }
    }
    text = sess.system_prompt_for_session(cfg, {})
    return {"chars": len(text), "tokens": count_tokens([SystemMessage(content=text)])}


def measure_tool_schemas(waist: str = "all") -> dict:
    """Measure the tool JSON the provider receives on every call.

    ``waist="profile"`` applies the deterministic capability waist
    (``resolve_runtime_profile``) to a mixed sample of tasks and reports the
    mean — the parent-turn behaviour under ``CRUSORAI_TOOL_WAIST=profile``.
    """
    import src.graphs.chat_graph as cg

    by_name = {t.name: t for t in cg.tools}

    def _schemas(names):
        rows = []
        for name in names:
            tool = by_name.get(name)
            if tool is None:
                continue
            try:
                rows.append({
                    "name": tool.name,
                    "description": tool.description,
                    "args": tool.args_schema.model_json_schema(),
                })
            except Exception:
                rows.append({"name": name})
        return count_tokens([SystemMessage(content=json.dumps(rows))])

    if waist == "none":
        return {"waist": "none", "tools": 0, "tokens": 0, "samples": {}}

    if waist == "all":
        names = [t.name for t in cg.tools]
        return {"waist": "all", "tools": len(names),
                "tokens": _schemas(names), "samples": {}}

    samples = {
        "small talk": "hi",
        "explain repo": "what does this repo do?",
        "bugfix": "fix the failing test in parser.py",
        "build app": "build and verify a small web app",
    }
    prev = os.environ.get("CRUSORAI_TOOL_WAIST")
    os.environ["CRUSORAI_TOOL_WAIST"] = "profile"
    per = {}
    try:
      for label, task in samples.items():
        cfg = {"configurable": {"thread_id": "waist-probe",
                                "workspace": str(REPO_ROOT)}}
        bound = cg._resolve_bound_tools(
            {"current_task": task, "messages": [], "workspace": str(REPO_ROOT)},
            cfg,
        )
        names = [t.name for t in bound]
        per[label] = {"tools": len(names), "tokens": _schemas(names)}
    finally:
        if prev is None:
            os.environ.pop("CRUSORAI_TOOL_WAIST", None)
        else:
            os.environ["CRUSORAI_TOOL_WAIST"] = prev
    mean_tokens = int(sum(v["tokens"] for v in per.values()) / max(len(per), 1))
    mean_tools = int(sum(v["tools"] for v in per.values()) / max(len(per), 1))
    return {"waist": "profile", "tools": mean_tools, "tokens": mean_tokens,
            "samples": per}


def turn_cost(
    sys_tokens: int,
    calls_per_turn: int,
    history_tokens: int,
    out_tokens_per_call: int,
    price_in: float,
    price_out: float,
    cache_read_ratio: float,
    cache_read_multiplier: float,
) -> dict:
    """Cost of one turn, split the way a bill actually splits."""
    # Every call re-sends: system prompt + growing history (modelled flat) and
    # emits assistant text/tool JSON.
    cached_in = sys_tokens * cache_read_ratio
    fresh_in = sys_tokens - cached_in
    prompt_in = (cached_in * cache_read_multiplier) + fresh_in + history_tokens
    billed_in = prompt_in * calls_per_turn
    billed_out = out_tokens_per_call * calls_per_turn
    cost_in = billed_in / 1_000_000 * price_in
    cost_out = billed_out / 1_000_000 * price_out
    return {
        "billed_input_tokens": int(billed_in),
        "billed_output_tokens": int(billed_out),
        "cost_input_usd": round(cost_in, 4),
        "cost_output_usd": round(cost_out, 4),
        "cost_per_turn_usd": round(cost_in + cost_out, 4),
        "system_prompt_share_of_input": round(
            (sys_tokens * calls_per_turn) / max(billed_in, 1), 3
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calls-per-turn", type=int, default=25,
                    help="provider calls in one turn (budget.py allows 20-45)")
    ap.add_argument("--history-tokens", type=int, default=8000,
                    help="conversation history re-sent per call (post-compaction)")
    ap.add_argument("--out-tokens", type=int, default=400,
                    help="output tokens per call (prose + tool-call JSON)")
    ap.add_argument("--price-in", type=float, default=0.30, help="USD / 1M input tokens")
    ap.add_argument("--price-out", type=float, default=2.40, help="USD / 1M output tokens")
    ap.add_argument("--cache-read-ratio", type=float, default=0.0,
                    help="fraction of the system prompt served from cache (0-1)")
    ap.add_argument("--cache-read-multiplier", type=float, default=0.1,
                    help="billed fraction of a cache read (0.1 = 90%% discount)")
    ap.add_argument("--tool-schema-tokens", type=int, default=None,
                    help="override the measured tool-schema payload per call")
    ap.add_argument("--turns-per-day", type=int, default=100)
    ap.add_argument("--days-per-month", type=int, default=22)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    # The context/boot stack prints to stdout; keep --json parseable and the
    # human report clean by silencing only the measurement window.
    with contextlib.redirect_stdout(io.StringIO()):
        unbounded = measure_prompt("0")
        budgeted = measure_prompt(None)
    default_budget = os.environ.get("CRUSORAI_SKILLS_INDEX_MAX_TOKENS")
    sess.invalidate_all_sessions()
    os.environ.pop("CRUSORAI_SKILLS_INDEX_MAX_TOKENS", None)

    # Tool schemas ride in the same cached prefix as the system prompt.
    with contextlib.redirect_stdout(io.StringIO()):
        schemas_all = measure_tool_schemas("all")
        schemas_waist = measure_tool_schemas("profile")
    if args.tool_schema_tokens is not None:
        schemas_all["tokens"] = schemas_waist["tokens"] = args.tool_schema_tokens

    scenarios = (
        ("unbounded", unbounded["tokens"], schemas_all["tokens"]),
        ("budgeted", budgeted["tokens"], schemas_all["tokens"]),
        ("budgeted+waist", budgeted["tokens"], schemas_waist["tokens"]),
    )
    results = {}
    for label, prompt_tokens, schema_tokens in scenarios:
        results[label] = turn_cost(
            prompt_tokens + schema_tokens, args.calls_per_turn,
            args.history_tokens, args.out_tokens, args.price_in,
            args.price_out, args.cache_read_ratio, args.cache_read_multiplier,
        )
        results[label]["system_prompt_tokens"] = prompt_tokens
        results[label]["tool_schema_tokens"] = schema_tokens
        results[label]["fixed_prefix_tokens"] = prompt_tokens + schema_tokens

    turns_month = args.turns_per_day * args.days_per_month
    for label in results:
        results[label]["turns_per_month"] = turns_month
        results[label]["cost_per_month_usd"] = round(
            results[label]["cost_per_turn_usd"] * turns_month, 2
        )
    saving = results["unbounded"]["cost_per_month_usd"] - results["budgeted"]["cost_per_month_usd"]
    saving_waist = (
        results["budgeted"]["cost_per_month_usd"]
        - results["budgeted+waist"]["cost_per_month_usd"]
    )

    payload = {
        "assumptions": {
            "calls_per_turn": args.calls_per_turn,
            "turns_per_day": args.turns_per_day,
            "days_per_month": args.days_per_month,
            "history_tokens": args.history_tokens,
            "out_tokens_per_call": args.out_tokens,
            "price_in_per_1m": args.price_in,
            "price_out_per_1m": args.price_out,
            "cache_read_ratio": args.cache_read_ratio,
            "cache_read_multiplier": args.cache_read_multiplier,
        },
        "system_prompt_tokens": {
            "unbounded": unbounded["tokens"],
            "budgeted": budgeted["tokens"],
            "index_budget_env": default_budget or "default",
        },
        "tool_schema_tokens": {
            "all": schemas_all["tokens"],
            "all_tools": schemas_all["tools"],
            "profile_mean": schemas_waist["tokens"],
            "profile_mean_tools": schemas_waist["tools"],
            "profile_samples": schemas_waist["samples"],
        },
        "per_turn": {k: results[k] for k in results},
        "monthly_saving_usd": round(saving, 2),
        "monthly_saving_from_waist_usd": round(saving_waist, 2),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("=" * 68)
    print("AGENT CORE COST MODEL (measured prompt sizes, input prices)")
    print("=" * 68)
    print(f"system prompt  unbounded : {unbounded['tokens']:>7,} tokens")
    print(f"system prompt  budgeted  : {budgeted['tokens']:>7,} tokens "
          f"({100 * (1 - budgeted['tokens'] / max(unbounded['tokens'], 1)):.0f}% smaller)")
    print(f"tool schemas   all bound : {schemas_all['tokens']:>7,} tokens "
          f"({schemas_all['tools']} tools)")
    print(f"tool schemas   waist     : {schemas_waist['tokens']:>7,} tokens "
          f"(mean of {len(schemas_waist['samples'])} task profiles, "
          f"mean {schemas_waist['tools']} tools)")
    print(f"calls/turn {args.calls_per_turn}  ·  turns/day {args.turns_per_day}  ·  "
          f"{args.days_per_month} days  =  {turns_month:,} turns/month")
    print(f"prices: ${args.price_in}/1M in, ${args.price_out}/1M out, "
          f"cache read {args.cache_read_ratio:.0%} @ {args.cache_read_multiplier}x")
    print("-" * 68)
    for label in results:
        r = results[label]
        print(f"{label:>10}: ${r['cost_per_turn_usd']:.4f}/turn  "
              f"->  ${r['cost_per_month_usd']:>8,.2f}/month   "
              f"(sys prompt = {r['system_prompt_share_of_input']:.0%} of billed input)")
    print("-" * 68)
    print(f"saving from the index budget: ${saving:,.2f}/month "
          f"({100 * saving / max(results['unbounded']['cost_per_month_usd'], 0.01):.0f}%)")
    print(f"further saving from the waist: ${saving_waist:,.2f}/month "
          f"({100 * saving_waist / max(results['budgeted']['cost_per_month_usd'], 0.01):.0f}%)")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
