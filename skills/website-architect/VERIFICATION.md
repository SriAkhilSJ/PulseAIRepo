# Verification — the Architect library

Generated 2026-10-30 from repository state.

## Inventory

| Domain | Skills |
|---|---|
| `ai-ml-architect/` | 7 |
| `cloud-and-devops-architect/` | 7 |
| `desktop-architect/` | 5 |
| `mobile-architect/` | 6 |
| `website-architect/` | 76 |
| **total** | **101** |

## Spec conformance

- files checked: **101**
- name == parent directory: **101/101**
- crusor-path == path from skills/: **101/101**
- unique names: **101/101**
- longest body: **5955 chars** (cap 6000)
- longest description: **406 chars** (limit 1024)
- provenance present: **101/101**

## Runtime

- discovered as bundled skills: **121**
- phase = planning: **101**
- injected while executing: **1**
- injected while planning: **2**

## Routing (whole-word trigger match)

| Task | Skills selected |
|---|---|
| the site is slow on mobile | web-performance-architect |
| add a csp header | browser-security-architect |
| design a rest api | rest-architect, rest-graphql-debug |
| postgres query is slow | db-connector, mcp, postgres-architect |
| our pipeline takes 40 minutes | ci-cd-architect, testing-and-deployment-architect |
| we need a canary rollout | release-strategy-architect, testing-and-deployment-architect |
| implement this figma design | design-handoff-architect |
| how do we store api keys | secrets-management-architect |
| build an ios app | ios-architect, mobile-architect |
| flutter state management | flutter-architect |
| tauri vs electron | desktop-architect, electron-architect, tauri-architect |
| sign our mac app | desktop-distribution-architect |
| set up our aws accounts | aws-architect |
| kubernetes pod keeps restarting | cloud-and-devops-architect, containerization-architect, kubernetes-architect |
| terraform state is a mess | cloud-and-devops-architect, terraform-architect |
| lambda cold starts are slow | aws-architect, serverless-architect |
| our cloud bill doubled | cost-optimization-architect |
| what availability should we promise | reliability-architect |
| add an ai chatbot to our docs | llm-app-architect |
| our answers make things up | rag-architect |
| should we fine tune or use rag | ai-ml-architect, rag-architect |
| agent keeps looping forever | agent-architect, ai-ml-architect |
| predict churn with a model | mlops-architect |
| gpu bill is too high | inference-serving-architect |

## Verification runs

- `pytest src/tests -q` → 2975 passed, 20 failed, 23 skipped, 1 xfailed — the 20 are the repository's pre-existing unrelated failures (baseline 21).
- `pytest src/tests/test_agent_skills_tree.py` → 20 passed (spec conformance, uniqueness, path integrity, domain crowns, capability contracts, discovery).
- `pytest src/tests/test_skill_library.py` → 13 passed (shelf recording, browsing, full-body reads, planning phase, batch views).

## Known gaps

- Every skill is `crusor-origin: original`: GitHub access is unavailable here, so no body was adapted from an upstream repository.
- The MCP hierarchy mirroring this tree is not built yet.
