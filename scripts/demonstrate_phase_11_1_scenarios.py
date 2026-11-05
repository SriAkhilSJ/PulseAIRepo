#!/usr/bin/env python3
"""
scripts/demonstrate_phase_11_1_scenarios.py -- Real-World Scenario Demonstrations.

Demonstrates Phase 11.1 requirement discovery on:
1. Nontechnical user request: "Build an Amazon-like ecommerce website for my startup."
2. Technical user request: "Build an ecommerce application using Next.js, FastAPI, PostgreSQL, Redis, and JWT authentication. Follow a modular monolith architecture."
Saves full execution artifacts to:
  bench-results/phase111_requirement_understanding/PHASE_11_1_SCENARIO_DEMONSTRATIONS.json
"""

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.intelligence.requirement_integration import RequirementIntelligenceSystem

BENCH_DIR = REPO_ROOT / "bench-results" / "phase111_requirement_understanding"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = BENCH_DIR / "PHASE_11_1_SCENARIO_DEMONSTRATIONS.json"


def main() -> int:
    print("=" * 80)
    print("CRUSOR AI IDE — REAL-WORLD SCENARIO DEMONSTRATIONS (PHASE 11.1)")
    print("=" * 80)

    system = RequirementIntelligenceSystem()

    # Scenario 1: Nontechnical user request
    prompt_nontech = "Build an Amazon-like ecommerce website for my startup."
    print(f"\n[Scenario 1] Nontechnical Request: '{prompt_nontech}'")
    res1 = system.analyze_request(prompt_nontech, str(REPO_ROOT), task_id="demo_nontechnical")
    print(f"  Communication Style: {res1.communication_style}")
    print(f"  Identified Functional Requirements: {len(res1.specification.functional_requirements)}")
    print(f"  Identified User Roles: {[p.role_name for p in res1.specification.user_personas]}")
    print(f"  Identified Workflows: {[w.name for w in res1.specification.user_workflows]}")
    print(f"  Generated Clarification Questions: {len(res1.clarification_questions)}")
    for q in res1.clarification_questions:
        print(f"    * [{q.id}] {q.question} (Default: {q.default_choice})")

    # Scenario 2: Technical user request
    prompt_tech = (
        "Build an ecommerce application using Next.js, FastAPI, PostgreSQL, Redis, and JWT authentication. "
        "Follow a modular monolith architecture."
    )
    print(f"\n[Scenario 2] Technical Request: '{prompt_tech}'")
    res2 = system.analyze_request(prompt_tech, str(REPO_ROOT), task_id="demo_technical")
    print(f"  Communication Style: {res2.communication_style}")
    print(f"  Technical Constraints Extracted: {len(res2.specification.technical_constraints)}")
    for tc in res2.specification.technical_constraints:
        print(f"    * [{tc.id}] {tc.description} ({tc.classification.value})")

    # Answer clarification for Scenario 1
    if res1.clarification_questions:
        target_q = res1.clarification_questions[0]
        print(f"\nAnswering clarification {target_q.id} with '{target_q.default_choice}'...")
        updated_spec = system.answer_clarification(
            "demo_nontechnical", target_q.id, target_q.default_choice or "Standard", str(REPO_ROOT)
        )
        print(f"  Updated spec status: {'Complete' if updated_spec.is_complete else 'Pending'}")

    planning_ctx = system.get_planning_prompt_context("demo_technical", str(REPO_ROOT))

    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase": "11.1",
        "title": "Real-World Requirement Discovery Scenario Demonstrations",
        "scenarios": [
            {
                "id": "scenario_01_nontechnical",
                "prompt": prompt_nontech,
                "style": res1.communication_style,
                "problem_statement": res1.specification.problem_statement,
                "desired_outcome": res1.specification.desired_outcome,
                "functional_requirements_count": len(res1.specification.functional_requirements),
                "clarification_questions": [q.to_dict() for q in res1.clarification_questions],
                "workflows": [w.to_dict() for w in res1.specification.user_workflows],
                "user_personas": [p.to_dict() for p in res1.specification.user_personas],
                "assumptions": res1.specification.assumptions_and_defaults,
            },
            {
                "id": "scenario_02_technical",
                "prompt": prompt_tech,
                "style": res2.communication_style,
                "technical_constraints": [tc.to_dict() for tc in res2.specification.technical_constraints],
                "planning_context_preview": planning_ctx,
            },
        ],
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved scenario demonstrations to: {OUT_JSON}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
