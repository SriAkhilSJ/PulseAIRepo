#!/usr/bin/env python3
"""
scripts/demonstrate_phase_11_2_scenarios.py -- Real-World Scenario Demonstrations (Phase 11.2).

Demonstrates Phase 11.2 architecture decision intelligence on:
1. Scenario A — Simple application: "Build a personal expense tracker."
2. Scenario B — Growing SaaS product: "Build a multi-tenant SaaS platform with subscriptions, teams, authentication, and analytics."
3. Scenario C — Explicit technical architecture: "Build using Next.js, FastAPI, PostgreSQL, Redis, and a modular monolith architecture."
Saves full execution artifacts to:
  bench-results/phase112_architecture_decision_intelligence/PHASE_11_2_SCENARIO_DEMONSTRATIONS.json
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

from src.intelligence.architecture_integration import ArchitectureIntelligenceSystem
from src.intelligence.requirement_integration import RequirementIntelligenceSystem

BENCH_DIR = REPO_ROOT / "bench-results" / "phase112_architecture_decision_intelligence"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = BENCH_DIR / "PHASE_11_2_SCENARIO_DEMONSTRATIONS.json"


def main() -> int:
    print("=" * 80)
    print("CRUSOR AI IDE -- REAL-WORLD ARCHITECTURE SCENARIO DEMONSTRATIONS (PHASE 11.2)")
    print("=" * 80)

    req_sys = RequirementIntelligenceSystem()
    arch_sys = ArchitectureIntelligenceSystem()

    # Scenario A: Simple Application
    prompt_a = "Build a personal expense tracker."
    print(f"\n[Scenario A] Simple Application: '{prompt_a}'")
    req_sys.analyze_request(prompt_a, str(REPO_ROOT), task_id="demo_scenario_a")
    res_a = arch_sys.synthesize_architecture("demo_scenario_a", str(REPO_ROOT))
    print(f"  Selected Architecture: {res_a.blueprint.architecture_style.value}")
    print(f"  Database Choice: {res_a.blueprint.database_architecture.database_choice}")
    print(f"  Estimated Monthly Cost: ${res_a.blueprint.cost_considerations.total_estimated_monthly_usd:.2f} ({res_a.blueprint.cost_considerations.cost_confidence.value})")
    print(f"  Nontechnical Summary: {res_a.blueprint.nontechnical_explanation.simple_summary if res_a.blueprint.nontechnical_explanation else 'N/A'}")

    # Scenario B: Growing SaaS Product
    prompt_b = "Build a multi-tenant SaaS platform with subscriptions, teams, authentication, and analytics."
    print(f"\n[Scenario B] Growing SaaS Product: '{prompt_b}'")
    req_sys.analyze_request(prompt_b, str(REPO_ROOT), task_id="demo_scenario_b")
    res_b = arch_sys.synthesize_architecture("demo_scenario_b", str(REPO_ROOT))
    print(f"  Selected Architecture: {res_b.blueprint.architecture_style.value}")
    print(f"  Tenant Isolation Strategy: {res_b.blueprint.database_architecture.tenant_isolation_strategy}")
    print(f"  Estimated Monthly Cost: ${res_b.blueprint.cost_considerations.total_estimated_monthly_usd:.2f} ({res_b.blueprint.cost_considerations.cost_confidence.value})")
    print(f"  Authorization Model: {res_b.blueprint.security_architecture.authorization_model}")

    # Scenario C: Explicit Technical Architecture
    prompt_c = "Build using Next.js, FastAPI, PostgreSQL, Redis, and a modular monolith architecture."
    print(f"\n[Scenario C] Explicit Technical Architecture: '{prompt_c}'")
    req_sys.analyze_request(prompt_c, str(REPO_ROOT), task_id="demo_scenario_c")
    res_c = arch_sys.synthesize_architecture("demo_scenario_c", str(REPO_ROOT))
    print(f"  Selected Architecture: {res_c.blueprint.architecture_style.value}")
    print(f"  Technology Stack: {res_c.blueprint.technology_stack}")
    print(f"  Total ADRs Created: {len(res_c.blueprint.adrs)}")
    for adr in res_c.blueprint.adrs:
        print(f"    * [{adr.id}] {adr.title} -> {adr.approval_status.value} (Explicit Lock: {adr.is_user_explicit})")

    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase": "11.2",
        "title": "Real-World Architecture Decision Intelligence Scenario Demonstrations",
        "scenarios": [
            {
                "id": "scenario_a_simple_app",
                "prompt": prompt_a,
                "architecture_style": res_a.blueprint.architecture_style.value,
                "technology_stack": res_a.blueprint.technology_stack,
                "cost_estimate": res_a.blueprint.cost_considerations.to_dict(),
                "nontechnical_explanation": res_a.blueprint.nontechnical_explanation.to_dict() if res_a.blueprint.nontechnical_explanation else {},
            },
            {
                "id": "scenario_b_growing_saas",
                "prompt": prompt_b,
                "architecture_style": res_b.blueprint.architecture_style.value,
                "technology_stack": res_b.blueprint.technology_stack,
                "tenant_isolation": res_b.blueprint.database_architecture.tenant_isolation_strategy,
                "cost_estimate": res_b.blueprint.cost_considerations.to_dict(),
            },
            {
                "id": "scenario_c_explicit_technical_mandate",
                "prompt": prompt_c,
                "architecture_style": res_c.blueprint.architecture_style.value,
                "technology_stack": res_c.blueprint.technology_stack,
                "adrs": [adr.to_dict() for adr in res_c.blueprint.adrs],
                "planner_context_preview": arch_sys.get_planner_architecture_context("demo_scenario_c", str(REPO_ROOT)),
            },
        ],
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved scenario demonstrations to: {OUT_JSON}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())

