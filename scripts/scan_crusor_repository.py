#!/usr/bin/env python3
"""
scripts/scan_crusor_repository.py -- Scans the actual Crusor AI IDE repository.

Phase 11.0: Project & Repository Intelligence.
Extracts verified facts from the real PulseAIRepo workspace and writes output to:
  bench-results/phase110_project_intelligence/CRUSOR_REPO_INTELLIGENCE.json
"""

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.intelligence.persistence import PersistentProjectIntelligenceManager
from src.intelligence.agent_integration import ProjectIntelligenceRetriever

BENCH_DIR = REPO_ROOT / "bench-results" / "phase110_project_intelligence"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = BENCH_DIR / "CRUSOR_REPO_INTELLIGENCE.json"


def main() -> int:
    print("=" * 80)
    print("CRUSOR AI IDE — REAL REPOSITORY INTELLIGENCE DISCOVERY")
    print(f"Scanning Workspace: {REPO_ROOT}")
    print("=" * 80)

    mgr = PersistentProjectIntelligenceManager(str(REPO_ROOT))
    t0 = time.time()
    knowledge = mgr.get_project_knowledge(force_full_rescan=True)
    duration = time.time() - t0

    retriever = ProjectIntelligenceRetriever(mgr)
    md_summary = retriever.render_markdown_context()

    payload = {
        "scan_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(duration, 3),
        "workspace_root": str(REPO_ROOT),
        "summary": md_summary,
        "knowledge": knowledge.to_dict(),
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nScan completed in {duration:.2f}s!")
    print(f"Total files indexed: {len(knowledge.file_mtimes)}")
    print(f"Project Type: {knowledge.project_type.value.value} (Confidence: {knowledge.project_type.confidence.value})")
    print(f"Languages: {', '.join(knowledge.languages.keys())}")
    print(f"Frameworks: {', '.join(f.name for f in knowledge.frameworks)}")
    print(f"Components identified: {len(knowledge.architecture_map.components)}")
    print(f"Saved to: {OUT_JSON}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())

