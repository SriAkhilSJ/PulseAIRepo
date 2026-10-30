# Verification — the Architect library

Generated 2026-10-30 from repository state.

## Inventory

| Domain | Skills |
|---|---|
| `ai-ml-architect/` | 7 |
| `cloud-and-devops-architect/` | 36 |
| `data-engineering-architect/` | 7 |
| `desktop-architect/` | 9 |
| `mobile-architect/` | 13 |
| `website-architect/` | 76 |
| **total** | **148** |

## Breadth status

| Domain | Books | Status |
|---|---|---|
| `website-architect/` | 76 | reference resolution — one book per framework |
| `cloud-and-devops-architect/` | 36 | brought to reference resolution, 7 shelves |
| `mobile-architect/` | 13 | deepened once; still narrower than reference |
| `desktop-architect/` | 9 | deepened once; still narrower than reference |
| `ai-ml-architect/` | 7 | not yet widened |
| `data-engineering-architect/` | 7 | not yet widened |

## Spec conformance

- files checked: **148**
- name == parent directory: **148/148**
- crusor-path == path from skills/: **148/148**
- unique names: **148/148**
- longest body: **5955 chars** (cap 6000)
- longest description: **406 chars** (limit 1024)
- provenance present: **148/148**

## Runtime

- discovered as bundled skills: **168**
- phase = planning: **148**
- injected while executing: **1**
- injected while planning: **2**

## Routing (whole-word trigger match)

| Task | Skills selected |
|---|---|
| build a nightly etl into the warehouse | batch-pipeline-architect, data-engineering-architect |
| kafka consumer lag is growing | streaming-architect |
| our dbt project is a mess | analytics-engineering-architect |
| set up our aws accounts | aws-architect |
| bigquery partitioning costs | gcp-architect, postgres-architect, warehouse-architect |
| separate accounts per environment | multi-account-architect |
| our sqs queue is backing up | aws-architect, messaging-architect |
| redis cache stampede | caching-architect, redis-architect |
| argocd drift in production | gitops-architect, terraform-architect |
| mtls between services | service-mesh-architect |
| gke cluster hardening | gcp-architect, kubernetes-architect, kubernetes-security-architect, security-architect |
| restore our database from backup | backup-and-dr-architect, database-engineering-architect, db-connector, desktop-offline-storage-architect |
| on-call runbook for outages | cloud-incident-response-architect, incident-response-architect |
| terraform state is a mess | cloud-and-devops-architect, terraform-architect |
| our cloud bill doubled | cost-optimization-architect |
| add an ai chatbot to our docs | llm-app-architect |
| agent keeps looping forever | agent-architect, ai-ml-architect |
| build an ios app with swiftui | ios-architect, ios-swiftui-architect, mobile-architect |
| app works offline in the field | mobile-architect, mobile-offline-sync-architect, pwa-architect |
| tauri vs electron | desktop-architect, electron-architect, tauri-architect |
| electron app security review | desktop-architect, desktop-security-architect, electron-architect, requesting-code-review, security-architect |
| auto update keeps failing | desktop-architect, desktop-distribution-architect, desktop-update-architect, systematic-debugging |
| design a rest api | rest-architect, rest-graphql-debug |

## Verification runs

- `pytest src/tests -q` → 2975 passed, 20 failed, 23 skipped, 1 xfailed — the 20 are the repository's pre-existing unrelated failures.
- `pytest src/tests/test_agent_skills_tree.py` → 21 passed.
- `pytest src/tests/test_skill_library.py` → 13 passed.

## Known gaps

- All skills are `crusor-origin: original`: GitHub access is unavailable here, so no body is adapted from an upstream repository.
- ai-ml and data-engineering are still at topic resolution; the breadth pass continues there next.
- The MCP hierarchy mirroring this tree is not built yet.
