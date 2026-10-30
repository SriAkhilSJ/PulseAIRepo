# Verification — the Architect library

Generated 2026-10-30 from repository state.

## Inventory

| Domain | Skills |
|---|---|
| `cloud-and-devops-architect/` | 7 |
| `desktop-architect/` | 5 |
| `mobile-architect/` | 6 |
| `website-architect/` | 76 |
| **total** | **94** |

## Spec conformance

- files checked: **94**
- name == parent directory: **94/94**
- crusor-path == path from skills/: **94/94**
- unique names: **94/94**
- longest body: **5955 chars** (cap 6000)
- longest description: **406 chars** (limit 1024)
- provenance present: **94/94**

## Runtime

- discovered as bundled skills: **114**
- phase = planning: **94**
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
| sign our mac app | — (browse fallback) |
| set up our aws accounts | aws-architect |
| kubernetes pod keeps restarting | cloud-and-devops-architect, containerization-architect, kubernetes-architect |
| terraform state is a mess | cloud-and-devops-architect, terraform-architect |
| lambda cold starts are slow | aws-architect, serverless-architect |
| our cloud bill doubled | cost-optimization-architect |
| what availability should we promise | reliability-architect |

## Verification runs

- `pytest src/tests -q` → 2975 passed, 20 failed, 23 skipped, 1 xfailed — the 20 are the repository's pre-existing unrelated failures (baseline 21).
- `pytest src/tests/test_agent_skills_tree.py` → 19 passed (spec conformance, uniqueness, path integrity, domain crowns, capability contracts, discovery).
- `pytest src/tests/test_skill_library.py` → 13 passed (shelf recording, browsing, full-body reads, planning phase, batch views).

## Known gaps

- Every skill is `crusor-origin: original`: GitHub access is unavailable here, so no body was adapted from an upstream repository.
- The MCP hierarchy mirroring this tree is not built yet.

