#!/usr/bin/env python3
"""Controlled Experiment: Measuring the Impact of Dynamic Constraints Manifest and Token Budget.

Tests:
  Condition A (Baseline): Full Stack, No Manifest, max_tokens=1500
  Condition B (Token Cap): Full Stack, No Manifest, max_tokens=4096
  Condition C (Dynamic Manifest): Full Stack + Dynamic Manifest, max_tokens=4096

Measures across DeepSeek V4.1 Flash, GLM 5.3 Flash, GPT-4o-mini:
  - finish_reason ('stop' vs 'length' truncation)
  - Output token count & latency
  - Recall across the 6 architectural concerns (tenant isolation, offline sync, migrations, api contract, security, observability)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import dotenv
dotenv.load_dotenv(REPO_ROOT / ".env")

import openai
from src.agents.skill_manager import SkillManager
from src.context.context_engine import _skills_text

MODELS = [
    {"id": "deepseek/deepseek-v4.1-flash", "alias": "DeepSeek V4.1 Flash"},
    {"id": "z-ai/glm-5.3-flash", "alias": "GLM 5.3 Flash"},
    {"id": "openai/gpt-4o-mini", "alias": "GPT-4o-mini"},
]

ARCHITECT_CONCERNS = {
    "tenant_isolation": [r"tenant[_\s-]?isolat", r"multi-tenant", r"tenant[_\s-]?id", r"row-level security", r"rls"],
    "offline_sync": [r"offline[_\s-]?sync", r"conflict[_\s-]?resolut", r"local[_\s-]?store", r"crdt", r"last-write-wins", r"sync queue"],
    "schema_migrations": [r"expand[_\s/-]?contract", r"schema[_\s-]?diff", r"zero[_\s-]?downtime", r"migration"],
    "api_design": [r"contract[_\s-]?review", r"error[_\s-]?envelope", r"cursor[_\s-]?paginat", r"idempotency[_\s-]?key", r"api[_\s-]?version"],
    "security_auth": [r"rbac", r"least[_\s-]?privilege", r"secrets[_\s-]?manage", r"token[_\s-]?revocat", r"owasp", r"httponly"],
    "observability": [r"structured[_\s-]?log", r"telemetry", r"trace[_\s-]?id", r"metrics", r"audit[_\s-]?trail"],
}

TASK = "build a multi-tenant SaaS for field service teams with billing and offline mobile"


def build_dynamic_manifest(sm: SkillManager, task: str) -> str:
    kit = sm.plan_kit(task)
    manifest = ["### DYNAMIC ARCHITECTURAL MANIFEST (Matched from loaded books)"]
    for tier in ("core", "stack"):
        for e in kit.get(tier, []):
            s = sm.get_skill(e["name"])
            if not s:
                continue
            name = e["name"]
            body = s.get("instruction", "")
            decs = [l.strip("# ").strip() for l in body.splitlines() if l.startswith("## Decision") or l.startswith("## Step")]
            if decs:
                manifest.append(f"- [{name}]: " + "; ".join(decs[:4]))
    return "\n".join(manifest)


def evaluate_concerns(content: str) -> dict:
    res = {}
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
        res[concern] = {"recalled": matched, "match": matched_str}
    recall_pct = round((sum(1 for v in res.values() if v["recalled"]) / len(ARCHITECT_CONCERNS)) * 100, 1)
    return {"concerns": res, "recall_pct": recall_pct}


def run_single(client: openai.OpenAI, model: str, context_text: str, max_tokens: int) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "You are CrusorAI Architect in PLAN MODE. Formulate an authoritative execution plan "
                "strictly adhering to the architectural decisions and non-negotiables in your loaded skills.\n\n"
                + context_text
            ),
        },
        {"role": "user", "content": TASK},
    ]

    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.2,
    )
    dt = time.perf_counter() - t0
    choice = resp.choices[0]
    finish_reason = getattr(choice, "finish_reason", "unknown")
    content = choice.message.content or ""
    usage = resp.usage
    out_toks = usage.completion_tokens if usage else len(content) // 4

    eval_res = evaluate_concerns(content)
    return {
        "duration_s": round(dt, 2),
        "finish_reason": finish_reason,
        "output_tokens": out_toks,
        "recall_pct": eval_res["recall_pct"],
        "concerns": eval_res["concerns"],
    }


def main():
    sm = SkillManager()
    base_skills = _skills_text({"execution_mode": "plan"}, TASK)
    manifest = build_dynamic_manifest(sm, TASK)
    augmented_skills = manifest + "\n\n" + base_skills

    client = openai.OpenAI(
        api_key=os.getenv("CUSTOM_API_KEY"),
        base_url=os.getenv("CUSTOM_BASE_URL", "https://velona.in/v1"),
        default_headers={"User-Agent": os.getenv("CRUSORAI_HTTP_USER_AGENT", "Mozilla/5.0")},
        timeout=180.0,
    )

    print("=" * 80)
    print("CONTROLLED EXPERIMENT: Baseline vs Token Cap vs Dynamic Manifest")
    print("=" * 80)

    matrix = {}

    for m in MODELS:
        mid = m["id"]
        alias = m["alias"]
        print(f"\n--- Model: {alias} ({mid}) ---")
        matrix[mid] = {}

        # Condition A: Baseline (No manifest, 1500 tokens)
        print("  Running Condition A: Baseline (No Manifest, max_tokens=1500)...")
        try:
            res_a = run_single(client, mid, base_skills, max_tokens=1500)
            print(f"    -> Finish: {res_a['finish_reason']} | Tokens: {res_a['output_tokens']} | Recall: {res_a['recall_pct']}% in {res_a['duration_s']}s")
            matrix[mid]["A_baseline"] = res_a
        except Exception as e:
            print(f"    -> Condition A failed: {e}")

        # Condition B: Token Expansion (No manifest, 4096 tokens)
        print("  Running Condition B: Token Expansion (No Manifest, max_tokens=4096)...")
        try:
            res_b = run_single(client, mid, base_skills, max_tokens=4096)
            print(f"    -> Finish: {res_b['finish_reason']} | Tokens: {res_b['output_tokens']} | Recall: {res_b['recall_pct']}% in {res_b['duration_s']}s")
            matrix[mid]["B_token_expansion"] = res_b
        except Exception as e:
            print(f"    -> Condition B failed: {e}")

        # Condition C: Dynamic Manifest + 4096 tokens
        print("  Running Condition C: Dynamic Manifest (With Manifest, max_tokens=4096)...")
        try:
            res_c = run_single(client, mid, augmented_skills, max_tokens=4096)
            print(f"    -> Finish: {res_c['finish_reason']} | Tokens: {res_c['output_tokens']} | Recall: {res_c['recall_pct']}% in {res_c['duration_s']}s")
            matrix[mid]["C_dynamic_manifest"] = res_c
        except Exception as e:
            print(f"    -> Condition C failed: {e}")

    out_file = REPO_ROOT / "bench-results" / "CONTROLLED_EXPERIMENT_MANIFEST_RESULTS.json"
    out_file.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    print(f"\n[DONE] Saved controlled experiment results to {out_file}")


if __name__ == "__main__":
    main()
