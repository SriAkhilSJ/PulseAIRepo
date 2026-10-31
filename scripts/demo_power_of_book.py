#!/usr/bin/env python3
"""Empirical Demonstration: The Power of the Architect Book (CrusorAI 2.1).

Runs live prompts against the model:
1. Without Book (Raw LLM knowledge)
2. With Book (CrusorAI Architect Skills library injected)

Directly scores and compares the resulting system design across the 8 hard invariants
defined in the `SKILL.md` library.
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

TASK = "build a multi-tenant SaaS for field service teams with billing, offline mobile sync, and database migrations"

INVARIANTS = {
    "db_tenant_isolation": {
        "title": "Tenant Isolation Mechanism",
        "book_spec": "Postgres Row-Level Security (RLS) with SET LOCAL app.current_tenant_id",
        "raw_antipattern": "Application-level WHERE tenant_id = :id (vulnerable to app logic leaks)",
        "patterns": [r"row-level security", r"rls", r"current_tenant_id"],
    },
    "id_strategy": {
        "title": "Primary Key Strategy",
        "book_spec": "UUIDv7 or ULID (time-ordered, distributed, high B-tree locality)",
        "raw_antipattern": "Serial auto-increment integers (exposes tenant volume, low distributed scalability)",
        "patterns": [r"uuidv7", r"uuid\s*v7", r"ulid"],
    },
    "currency_storage": {
        "title": "Financial / Currency Representation",
        "book_spec": "Integer minor units (cents / bigint) or NUMERIC, never float",
        "raw_antipattern": "FLOAT / DOUBLE / REAL (floating point precision errors)",
        "patterns": [r"integer minor", r"amount_cents", r"cents", r"minor units", r"never float"],
    },
    "migration_pattern": {
        "title": "Database Schema Evolution",
        "book_spec": "Expand/Contract across two deploys (backward-compatible, zero table lock)",
        "raw_antipattern": "Single-deploy destructive DDL (causes downtime or locked tables)",
        "patterns": [r"expand[_\s/-]?contract", r"two[_\s-]?deploy", r"dual-write"],
    },
    "mobile_deletions": {
        "title": "Offline Deletion Policy",
        "book_spec": "Tombstones (deleted_at TIMESTAMPTZ) to propagate deletes across offline nodes",
        "raw_antipattern": "Hard DELETE statement (orphans offline client records)",
        "patterns": [r"tombstone", r"deleted_at", r"soft[_\s-]?delete"],
    },
    "sync_engine": {
        "title": "Offline Sync Synchronization",
        "book_spec": "Monotonic revision counter + append-only mutation queue",
        "raw_antipattern": "Ad-hoc last-write-wins without revision numbering",
        "patterns": [r"monotonic revision", r"revision[_\s-]?id", r"since_revision", r"mutation queue"],
    },
    "error_envelope": {
        "title": "API Error Contract",
        "book_spec": "Uniform envelope: { error: { code, message, request_id } }",
        "raw_antipattern": "Inconsistent error bodies, string-only error messages",
        "patterns": [r"request_id", r"error[_\s-]?envelope", r"error:\s*\{\s*code"],
    },
    "pagination": {
        "title": "API List Pagination",
        "book_spec": "Cursor pagination for all growing datasets (cursor/keyset)",
        "raw_antipattern": "LIMIT / OFFSET pagination (degrades at scale, skips on concurrent writes)",
        "patterns": [r"cursor", r"keyset"],
    },
}


def score_plan(text: str) -> dict:
    t_lower = text.lower()
    results = {}
    passed_count = 0
    for key, spec in INVARIANTS.items():
        matched = False
        match_str = None
        for p in spec["patterns"]:
            m = re.search(p, t_lower)
            if m:
                matched = True
                match_str = m.group(0)
                break
        if matched:
            passed_count += 1
        results[key] = {
            "title": spec["title"],
            "matched": matched,
            "match": match_str,
            "book_spec": spec["book_spec"],
            "raw_antipattern": spec["raw_antipattern"],
        }
    return {
        "score_pct": round((passed_count / len(INVARIANTS)) * 100, 1),
        "passed_count": passed_count,
        "total": len(INVARIANTS),
        "details": results,
    }


def main():
    client = openai.OpenAI(
        api_key=os.getenv("CUSTOM_API_KEY"),
        base_url=os.getenv("CUSTOM_BASE_URL", "https://velona.in/v1"),
        default_headers={"User-Agent": os.getenv("CRUSORAI_HTTP_USER_AGENT", "Mozilla/5.0")},
        timeout=180.0,
    )

    model = "openai/gpt-4o-mini"
    print("=" * 80)
    print(f"LIVE EXPERIMENT: The Power of the Book vs Raw Model ({model})")
    print(f"TASK: {TASK}")
    print("=" * 80)

    # 1. RUN WITHOUT BOOK
    print("\n[RUN 1/2] Prompting Model WITHOUT Book (Standard Prompting)...")
    t0 = time.time()
    resp_raw = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a software architect. Formulate an engineering plan for the requested software system."},
            {"role": "user", "content": TASK},
        ],
        max_tokens=2500,
        temperature=0.2,
    )
    dt_raw = round(time.time() - t0, 2)
    raw_content = resp_raw.choices[0].message.content or ""
    raw_score = score_plan(raw_content)
    print(f"  -> Finished in {dt_raw}s | Output: {len(raw_content)} chars | Score: {raw_score['score_pct']}% ({raw_score['passed_count']}/{raw_score['total']})")

    # 2. RUN WITH BOOK
    print("\n[RUN 2/2] Prompting Model WITH CrusorAI Architect Books Injected...")
    sm = SkillManager()
    kit = sm.plan_kit(TASK)
    manifest = ["### ARCHITECTURAL MANIFEST (Matched from loaded books)"]
    for tier in ("core", "stack"):
        for e in kit.get(tier, []):
            s = sm.get_skill(e["name"])
            if not s: continue
            name = e["name"]
            body = s.get("instruction", "")
            decs = [l.strip("# ").strip() for l in body.splitlines() if l.startswith("## Decision") or l.startswith("## Step")]
            if decs: manifest.append(f"- [{name}]: " + "; ".join(decs[:4]))
    manifest_text = "\n".join(manifest)
    base_skills = _skills_text({"execution_mode": "plan"}, TASK)
    full_book_context = manifest_text + "\n\n" + base_skills

    t0 = time.time()
    resp_book = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are CrusorAI Architect in PLAN MODE. Your plan must strictly embody the non-negotiables, "
                    "database boundaries, sync invariants, and verification receipts defined in your loaded skills.\n\n"
                    + full_book_context
                ),
            },
            {"role": "user", "content": TASK},
        ],
        max_tokens=2500,
        temperature=0.2,
    )
    dt_book = round(time.time() - t0, 2)
    book_content = resp_book.choices[0].message.content or ""
    book_score = score_plan(book_content)
    print(f"  -> Finished in {dt_book}s | Output: {len(book_content)} chars | Score: {book_score['score_pct']}% ({book_score['passed_count']}/{book_score['total']})")

    # 3. SAVE REPORT
    report_data = {
        "model": model,
        "task": TASK,
        "without_book": {
            "duration_s": dt_raw,
            "chars": len(raw_content),
            "score": raw_score,
            "plan_excerpt": raw_content[:600] + "...",
        },
        "with_book": {
            "duration_s": dt_book,
            "chars": len(book_content),
            "score": book_score,
            "plan_excerpt": book_content[:600] + "...",
        },
    }

    out_file = REPO_ROOT / "bench-results" / "POWER_OF_THE_BOOK_EVALUATION.json"
    out_file.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"\n[DONE] Saved evaluation data to {out_file}")

    # Output Side-by-Side Invariants Comparison Table
    print("\n" + "=" * 90)
    print(f"{'INVARIANT':<32} | {'WITHOUT BOOK':<25} | {'WITH THE BOOK':<25}")
    print("=" * 90)
    for key in INVARIANTS:
        r_match = raw_score["details"][key]["matched"]
        b_match = book_score["details"][key]["matched"]
        r_text = f"PASS ({raw_score['details'][key]['match']})" if r_match else "FAIL (Omitted/Naive)"
        b_text = f"PASS ({book_score['details'][key]['match']})" if b_match else "FAIL (Omitted)"
        print(f"{INVARIANTS[key]['title']:<32} | {r_text:<25} | {b_text:<25}")
    print("=" * 90)
    print(f"FINAL QUALITY SCORE:   Without Book = {raw_score['score_pct']}%  vs  With Book = {book_score['score_pct']}%")


if __name__ == "__main__":
    main()
