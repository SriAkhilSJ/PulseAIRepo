#!/usr/bin/env python3
"""Multi-Model Live Performance & Skills Benchmark for CrusorAI / PulseAI.

Evaluates DeepSeek, GLM, and GPT against:
1. Raw Latency & Token Throughput (Speed & Efficiency)
2. Plan Mode Skills Adherence (Prompt Injection of Architect Books)
3. Architectural Concern Recall (Tenant Isolation, Offline Sync, Migrations, etc.)
4. Tool Calling Precision (Canonical Arguments vs Normalizer reliance)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import dotenv
dotenv.load_dotenv(REPO_ROOT / ".env")

import openai
from src.context.context_engine import _skills_text

MODELS = [
    {
        "id": "deepseek/deepseek-v4.1-flash",
        "alias": "DeepSeek V4.1 Flash",
        "provider": "Velona (custom)",
        "pricing_1m_in": 0.0475,
        "pricing_1m_out": 0.1568,
    },
    {
        "id": "z-ai/glm-5.3-flash",
        "alias": "GLM 5.3 Flash",
        "provider": "Velona (custom)",
        "pricing_1m_in": 0.0180,
        "pricing_1m_out": 0.1210,
    },
    {
        "id": "openai/gpt-4o-mini",
        "alias": "GPT-4o-mini",
        "provider": "Velona (custom)",
        "pricing_1m_in": 0.1500,
        "pricing_1m_out": 0.6000,
    },
]

ARCHITECT_CONCERNS = {
    "tenant_isolation": [
        r"tenant[_\s-]?isolat",
        r"multi-tenant",
        r"tenant[_\s-]?id",
        r"row-level security",
        r"rls",
        r"schema-per-tenant",
    ],
    "offline_sync": [
        r"offline[_\s-]?sync",
        r"conflict[_\s-]?resolut",
        r"local[_\s-]?store",
        r"crdt",
        r"last-write-wins",
        r"sync queue",
    ],
    "schema_migrations": [
        r"expand[_\s/-]?contract",
        r"schema[_\s-]?diff",
        r"zero[_\s-]?downtime",
        r"migration",
        r"version[_\s-]?control.*schema",
    ],
    "api_design": [
        r"contract[_\s-]?review",
        r"error[_\s-]?envelope",
        r"cursor[_\s-]?paginat",
        r"idempotency[_\s-]?key",
        r"api[_\s-]?version",
    ],
    "security_auth": [
        r"rbac",
        r"least[_\s-]?privilege",
        r"secrets[_\s-]?manage",
        r"token[_\s-]?revocat",
        r"owasp",
    ],
    "observability": [
        r"structured[_\s-]?log",
        r"telemetry",
        r"trace[_\s-]?id",
        r"metrics",
        r"audit[_\s-]?trail",
    ],
}


def create_client() -> openai.OpenAI:
    api_key = os.getenv("CUSTOM_API_KEY")
    base_url = os.getenv("CUSTOM_BASE_URL", "https://velona.in/v1")
    ua = os.getenv(
        "CRUSORAI_HTTP_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    )
    if not api_key:
        raise RuntimeError("CUSTOM_API_KEY not set in environment or .env")
    return openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers={"User-Agent": ua},
        timeout=120.0,
    )


def bench_speed_and_throughput(client: openai.OpenAI, model_id: str) -> dict:
    prompt = "Explain the difference between optimistic and pessimistic locking in 3 concise bullet points."
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.2,
    )
    total_time = time.perf_counter() - t0
    msg = resp.choices[0].message
    content = msg.content or ""
    usage = resp.usage
    out_toks = usage.completion_tokens if usage else len(content.split()) * 1.3
    in_toks = usage.prompt_tokens if usage else len(prompt.split()) * 1.3
    tok_per_sec = round(out_toks / total_time, 2) if total_time > 0 else 0.0

    return {
        "latency_s": round(total_time, 3),
        "prompt_tokens": in_toks,
        "completion_tokens": out_toks,
        "tokens_per_sec": tok_per_sec,
        "sample_response": content[:180] + ("..." if len(content) > 180 else ""),
    }


def bench_skills_plan_mode(client: openai.OpenAI, model_id: str) -> dict:
    task = "build a multi-tenant SaaS for field service teams with billing and offline mobile"
    # Inject full architect kit through CrusorAI context engine
    skills_kit = _skills_text({"execution_mode": "plan"}, task)

    system_prompt = (
        "You are CrusorAI Architect in PLAN MODE. Your objective is to formulate an authoritative "
        "engineering execution plan for the requested software system. Adhere strictly to the "
        "architectural patterns, verification receipts, and boundary rules specified in your loaded skills."
    )
    messages = [
        {"role": "system", "content": system_prompt + "\n\n" + skills_kit},
        {"role": "user", "content": task},
    ]

    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model_id,
        messages=messages,
        max_tokens=1500,
        temperature=0.2,
    )
    plan_time = time.perf_counter() - t0
    content = resp.choices[0].message.content or ""
    usage = resp.usage
    in_toks = usage.prompt_tokens if usage else len(skills_kit) // 4
    out_toks = usage.completion_tokens if usage else len(content) // 4

    # Evaluate architect concerns
    detected_concerns = {}
    content_lower = content.lower()
    for concern, patterns in ARCHITECT_CONCERNS.items():
        matched = False
        matched_str = None
        for pat in patterns:
            m = re.search(pat, content_lower)
            if m:
                matched = True
                matched_str = m.group(0)
                break
        detected_concerns[concern] = {"recalled": matched, "match": matched_str}

    recall_count = sum(1 for v in detected_concerns.values() if v["recalled"])
    recall_pct = round((recall_count / len(ARCHITECT_CONCERNS)) * 100, 1)

    return {
        "duration_s": round(plan_time, 2),
        "input_tokens": in_toks,
        "output_tokens": out_toks,
        "tokens_per_sec": round(out_toks / plan_time, 2) if plan_time > 0 else 0.0,
        "architect_recall_pct": recall_pct,
        "detected_concerns": detected_concerns,
        "plan_snippet": content[:350] + "...",
    }


def bench_tool_calling(client: openai.OpenAI, model_id: str) -> dict:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": "Edits a file by replacing old_text with new_text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Target file path"},
                        "old_text": {"type": "string", "description": "Exact text to find and replace"},
                        "new_text": {"type": "string", "description": "New replacement content"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
        }
    ]

    messages = [
        {
            "role": "user",
            "content": "Please edit config.py to update DB_PORT from 5432 to 5433 using edit_file.",
        }
    ]

    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model_id,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        max_tokens=250,
    )
    dt = time.perf_counter() - t0
    msg = resp.choices[0].message
    tool_calls = msg.tool_calls or []

    canonical_args = False
    args_json = {}
    called_tool = None

    if tool_calls:
        tc = tool_calls[0]
        called_tool = tc.function.name
        try:
            args_json = json.loads(tc.function.arguments)
            # Check canonical keys
            if "old_text" in args_json and "new_text" in args_json and "path" in args_json:
                canonical_args = True
        except Exception:
            args_json = {"raw": tc.function.arguments}

    return {
        "duration_s": round(dt, 3),
        "emitted_tool_call": bool(tool_calls),
        "tool_name": called_tool,
        "canonical_args_adherence": canonical_args,
        "parsed_arguments": args_json,
    }


def main():
    print("=" * 80)
    print("CRUSORAI 2.1 MULTI-MODEL BENCHMARK: DEEPSEEK vs GLM vs GPT")
    print("Tracking Live Performance, Plan Mode Skills Recall, and Tool Precision")
    print("=" * 80)

    client = create_client()
    results = {}

    for m in MODELS:
        mid = m["id"]
        alias = m["alias"]
        print(f"\n[BENCHMARKING] {alias} ({mid})...")

        # 1. Speed & Throughput
        print(f"  -> Test 1: Speed, Latency & Token Throughput...")
        try:
            speed_res = bench_speed_and_throughput(client, mid)
            print(f"     Latency: {speed_res['latency_s']}s | Out Tokens: {speed_res['completion_tokens']} | Throughput: {speed_res['tokens_per_sec']} t/s")
        except Exception as e:
            print(f"     Speed test failed: {e}")
            speed_res = {"error": str(e)}

        # 2. Plan Mode Skills Adherence
        print(f"  -> Test 2: Plan Mode Architect Skills Injection & Recall...")
        try:
            skills_res = bench_skills_plan_mode(client, mid)
            print(f"     Plan Time: {skills_res['duration_s']}s | Prompt Tokens: {skills_res['input_tokens']} | Architect Recall: {skills_res['architect_recall_pct']}%")
        except Exception as e:
            print(f"     Plan mode test failed: {e}")
            skills_res = {"error": str(e)}

        # 3. Tool Calling
        print(f"  -> Test 3: Structured Tool Calling Precision...")
        try:
            tool_res = bench_tool_calling(client, mid)
            print(f"     Emitted Tool: {tool_res.get('tool_name')} | Canonical Args: {tool_res.get('canonical_args_adherence')}")
        except Exception as e:
            print(f"     Tool calling test failed: {e}")
            tool_res = {"error": str(e)}

        results[mid] = {
            "meta": m,
            "speed": speed_res,
            "plan_mode": skills_res,
            "tool_calling": tool_res,
        }

    # Save Results
    results_dir = REPO_ROOT / "bench-results"
    results_dir.mkdir(parents=True, exist_ok=True)

    json_file = results_dir / "MULTI_MODEL_PERFORMANCE_TRACKING.json"
    json_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[DONE] Saved raw benchmark results to {json_file}")

    # Generate Markdown Scorecard
    md_file = results_dir / "MULTI_MODEL_PERFORMANCE_TRACKING.md"
    generate_markdown_report(results, md_file)
    print(f"[DONE] Generated scorecard to {md_file}")


def generate_markdown_report(results: dict, output_file: Path):
    lines = [
        "# CrusorAI 2.1 Multi-Model Performance Tracking Report",
        "",
        "**Date:** 2026-10-30  ",
        "**Gateway:** Velona Custom OpenAI-compatible (`https://velona.in/v1`)  ",
        "**Evaluated Models:** `deepseek/deepseek-v4.1-flash`, `z-ai/glm-5.3-flash`, `openai/gpt-4o-mini`  ",
        "",
        "---",
        "",
        "## 1. Executive Performance Scorecard",
        "",
        "| Metric | DeepSeek V4.1 Flash | GLM 5.3 Flash | GPT-4o-mini |",
        "| :--- | :---: | :---: | :---: |",
    ]

    models = ["deepseek/deepseek-v4.1-flash", "z-ai/glm-5.3-flash", "openai/gpt-4o-mini"]
    
    # Latency row
    latencies = [str(results.get(m, {}).get("speed", {}).get("latency_s", "N/A")) + " s" for m in models]
    lines.append(f"| **Completion Latency (Speed)** | {latencies[0]} | {latencies[1]} | {latencies[2]} |")

    # Throughput row
    throughputs = [str(results.get(m, {}).get("speed", {}).get("tokens_per_sec", "N/A")) + " tok/s" for m in models]
    lines.append(f"| **Token Throughput** | {throughputs[0]} | {throughputs[1]} | {throughputs[2]} |")

    # Plan Mode Duration
    plan_times = [str(results.get(m, {}).get("plan_mode", {}).get("duration_s", "N/A")) + " s" for m in models]
    lines.append(f"| **Plan Mode Generation Time** | {plan_times[0]} | {plan_times[1]} | {plan_times[2]} |")

    # Injected Tokens
    plan_in_toks = [f"{results.get(m, {}).get('plan_mode', {}).get('input_tokens', 0):,}" for m in models]
    lines.append(f"| **Injected Skills Prompt Tokens** | {plan_in_toks[0]} | {plan_in_toks[1]} | {plan_in_toks[2]} |")

    # Plan Output Tokens
    plan_out_toks = [f"{results.get(m, {}).get('plan_mode', {}).get('output_tokens', 0):,}" for m in models]
    lines.append(f"| **Plan Completion Tokens** | {plan_out_toks[0]} | {plan_out_toks[1]} | {plan_out_toks[2]} |")

    # Architect Concern Recall
    recalls = [f"{results.get(m, {}).get('plan_mode', {}).get('architect_recall_pct', 0)}%" for m in models]
    lines.append(f"| **Architect Skills Recall** | **{recalls[0]}** | **{recalls[1]}** | **{recalls[2]}** |")

    # Tool Calling Canonical Args
    tool_args = [
        "PASS (Canonical)" if results.get(m, {}).get("tool_calling", {}).get("canonical_args_adherence") else "FAIL / Normalized"
        for m in models
    ]
    lines.append(f"| **Tool Calling Schema Adherence** | {tool_args[0]} | {tool_args[1]} | {tool_args[2]} |")

    # Price / 1M Tokens
    prices = [
        f"${results[m]['meta']['pricing_1m_in']:.4f} / ${results[m]['meta']['pricing_1m_out']:.4f}"
        for m in models
    ]
    lines.append(f"| **API Cost (In / Out per 1M)** | {prices[0]} | {prices[1]} | {prices[2]} |")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Injected Architect Skills Recall Breakdown",
        "",
        "Evaluated on Plan Mode prompt: `build a multi-tenant SaaS for field service teams with billing and offline mobile` with injected 12 architect books (~13.7k tokens).",
        "",
        "| Architectural Dimension | DeepSeek V4.1 Flash | GLM 5.3 Flash | GPT-4o-mini |",
        "| :--- | :---: | :---: | :---: |",
    ])

    for dim in ARCHITECT_CONCERNS:
        row = [f"**{dim.replace('_', ' ').title()}**"]
        for m in models:
            c = results.get(m, {}).get("plan_mode", {}).get("detected_concerns", {}).get(dim, {})
            if c.get("recalled"):
                row.append(f"Replaced/Recalled (`{c.get('match')}`)")
            else:
                row.append("Not Detected")
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")

    lines.extend([
        "",
        "---",
        "",
        "## 3. Plan Mode Snippet Comparison",
        "",
    ])

    for m in models:
        meta = results[m]["meta"]
        snippet = results.get(m, {}).get("plan_mode", {}).get("plan_snippet", "N/A")
        lines.extend([
            f"### {meta['alias']}",
            f"> {snippet}",
            "",
        ])

    output_file.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
