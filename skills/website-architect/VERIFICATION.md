# Verification — the Architect library

Generated 2026-10-30 from repository state.

## Inventory

| Domain | Skills |
|---|---|
| `ai-ml-architect/` | 7 |
| `cloud-and-devops-architect/` | 7 |
| `data-engineering-architect/` | 7 |
| `desktop-architect/` | 9 |
| `mobile-architect/` | 13 |
| `website-architect/` | 76 |
| **total** | **119** |

## Thin-domain coverage

| Domain | Before deepening | Now |
|---|---|---|
| `mobile-architect/` | 6 | 13 |
| `desktop-architect/` | 5 | 9 |

## Spec conformance

- files checked: **119**
- name == parent directory: **119/119**
- crusor-path == path from skills/: **119/119**
- unique names: **119/119**
- longest body: **5955 chars** (cap 6000)
- longest description: **406 chars** (limit 1024)
- provenance present: **119/119**

## Runtime

- discovered as bundled skills: **139**
- phase = planning: **119**
- injected while executing: **1**
- injected while planning: **2**

## Routing (whole-word trigger match)

| Task | Skills selected |
|---|---|
| the site is slow on mobile | web-performance-architect |
| design a rest api | rest-architect, rest-graphql-debug |
| postgres query is slow | db-connector, mcp, postgres-architect |
| we need a canary rollout | release-strategy-architect, testing-and-deployment-architect |
| build an ios app with swiftui | ios-architect, ios-swiftui-architect, mobile-architect |
| android app keeps losing state | android-architect, android-compose-architect, mobile-architect |
| our ui tests are flaky | mobile-testing-architect, test-strategy-architect |
| screen reader cannot read the buttons | accessibility-architect, mobile-accessibility-architect |
| app works offline in the field | mobile-architect, mobile-offline-sync-architect, pwa-architect |
| tauri vs electron | desktop-architect, electron-architect, tauri-architect |
| electron app needs a secure bridge | desktop-architect, desktop-ipc-architect, electron-architect |
| our desktop app loses data on crash | desktop-architect, desktop-offline-storage-architect, systematic-debugging |
| auto update keeps failing | desktop-architect, desktop-distribution-architect, desktop-update-architect, systematic-debugging |
| set up our aws accounts | aws-architect |
| terraform state is a mess | cloud-and-devops-architect, terraform-architect |
| our cloud bill doubled | cost-optimization-architect |
| should we fine tune or use rag | ai-ml-architect, rag-architect |
| agent keeps looping forever | agent-architect, ai-ml-architect |
| predict churn with a model | mlops-architect |
| kafka consumer lag is growing | streaming-architect |
| our dbt project is a mess | analytics-engineering-architect |

## Verification runs

- `pytest src/tests -q` → 2975 passed, 20 failed, 23 skipped, 1 xfailed — the 20 are the repository's pre-existing unrelated failures (baseline 21).
- `pytest src/tests/test_agent_skills_tree.py` → 21 passed (spec conformance, uniqueness, path integrity, domain crowns, capability contracts, discovery).
- `pytest src/tests/test_skill_library.py` → 13 passed (shelf recording, browsing, full-body reads, planning phase, batch views).

## Known gaps

- Every skill is `crusor-origin: original`: GitHub access is unavailable here, so no body was adapted from an upstream repository.
- The MCP hierarchy mirroring this tree is not built yet.
