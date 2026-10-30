# Verification — the Architect library

Generated 2026-10-30 from repository state.

## Inventory

| Domain | Skills |
|---|---|
| `ai-ml-architect/` | 31 |
| `cloud-and-devops-architect/` | 36 |
| `data-engineering-architect/` | 7 |
| `desktop-architect/` | 9 |
| `mobile-architect/` | 13 |
| `website-architect/` | 76 |
| **total** | **172** |

## Breadth status

| Domain | Books | Status |
|---|---|---|
| `website-architect/` | 76 | reference resolution — one book per framework |
| `cloud-and-devops-architect/` | 36 | at reference resolution, 7 shelves |
| `ai-ml-architect/` | 31 | at reference resolution, 8 shelves |
| `mobile-architect/` | 13 | deepened once; not yet at reference resolution |
| `desktop-architect/` | 9 | deepened once; not yet at reference resolution |
| `data-engineering-architect/` | 7 | not yet widened |

## Spec conformance

- files checked: **172**
- name == parent directory: **172/172**
- crusor-path == path from skills/: **172/172**
- unique names: **172/172**
- longest body: **5955 chars** (cap 6000)
- longest description: **406 chars** (limit 1024)
- provenance present: **172/172**

## Runtime

- discovered as bundled skills: **192**
- phase = planning: **172**
- injected while executing: **1**
- injected while planning: **2**

## Routing (whole-word trigger match)

| Task | Skills selected |
|---|---|
| set up our aws accounts | aws-architect |
| terraform state is a mess | cloud-and-devops-architect, terraform-architect |
| our cloud bill doubled | cost-optimization-architect |
| kafka consumer lag is growing | streaming-architect |
| which model should we pick for support | model-selection-architect |
| the model returns invalid json sometimes | structured-output-architect |
| prompt injection through support tickets | ai-ml-architect, prompting-architect, red-teaming-architect |
| our search misses error codes | hybrid-search-architect, systematic-debugging |
| pdf chunks come out garbled | chunking-architect |
| lora fine tune on our support data | ai-ml-architect, fine-tuning-architect |
| churn prediction with xgboost | classic-ml-architect, mlops-platform-architect |
| what should we recommend to users | recommender-architect |
| gpu memory is not enough for context | gpu-capacity-architect, inference-serving-architect |
| transcribe our sales calls | speech-architect |
| model decay in production | model-monitoring-architect |
| supervisor agent with two specialists | agent-architect, ai-ml-architect, multi-agent-architect |
| build a nightly etl into the warehouse | batch-pipeline-architect, data-engineering-architect |
| our dbt project is a mess | analytics-engineering-architect |
| build an ios app with swiftui | ios-architect, ios-swiftui-architect, mobile-architect |
| app works offline in the field | mobile-architect, mobile-offline-sync-architect, pwa-architect |
| tauri vs electron | desktop-architect, electron-architect, tauri-architect |
| auto update keeps failing | desktop-architect, desktop-distribution-architect, desktop-update-architect, systematic-debugging |

## Verification runs

- `pytest src/tests -q` → 2975 passed, 20 failed, 23 skipped, 1 xfailed — the 20 are the repository's pre-existing unrelated failures.
- `pytest src/tests/test_agent_skills_tree.py` → 21 passed.
- `pytest src/tests/test_skill_library.py` → 13 passed.

## Known gaps

- All skills are `crusor-origin: original`: GitHub access is unavailable here, so no body is adapted from an upstream repository.
- data-engineering is still at topic resolution; the breadth pass continues there next.
- The MCP hierarchy mirroring this tree is not built yet.
