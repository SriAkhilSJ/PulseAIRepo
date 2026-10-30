# Verification — the Architect library

Generated 2026-10-30 from repository state.

## Inventory

| Domain | Skills |
|---|---|
| `mobile-architect/` | 6 |
| `website-architect/` | 76 |
| **total** | **82** |

## Spec conformance

- files checked: **82**
- name == parent directory: **82/82**
- crusor-path == path from skills/: **82/82**
- unique names: **82/82**
- longest body: **5955 chars** (cap 6000)
- longest description: **406 chars** (limit 1024)
- provenance present: **82/82**

## Runtime

- discovered as bundled skills: **102**
- phase = planning: **82**
- injected while executing: **1**
- injected while planning: **2**

## Routing (whole-word trigger match)

| Task | Skills selected |
|---|---|
| the site is slow on mobile | web-performance-architect |
| add a csp header | browser-security-architect |
| design a rest api | rest-architect, rest-graphql-debug |
| our graphql resolves n+1 | graphql-architect, rest-graphql-debug |
| postgres query is slow | db-connector, mcp, postgres-architect |
| add redis caching for sessions | nextjs-architect, redis-architect |
| our pipeline takes 40 minutes | ci-cd-architect, testing-and-deployment-architect |
| we need a canary rollout | release-strategy-architect, testing-and-deployment-architect |
| implement this figma design | design-handoff-architect |
| add oauth login | api-auth-architect |
| harden our ci pipeline | ci-cd-architect, supply-chain-architect, testing-and-deployment-architect |
| should we use trpc or rest | rest-architect, trpc-architect |
| how do we store api keys | secrets-management-architect |
| write a dockerfile for the service | containerization-architect |
| add tracing for the api | observability-architect |
| build an ios app | ios-architect, mobile-architect |
| android compose navigation | android-architect, mobile-architect |
| react native performance | react-native-architect |
| flutter state management | flutter-architect |
| app store signing | mobile-release-architect |

## Verification runs

- `pytest src/tests -q` → 2975 passed, 20 failed, 23 skipped, 1 xfailed — the 20 are the repository's pre-existing unrelated failures (baseline was 21).
- `pytest src/tests/test_agent_skills_tree.py` → 17 passed (spec conformance, uniqueness, path integrity, domain crowns, capability contracts, library discovery).
- `pytest src/tests/test_skill_library.py` → 13 passed (shelf recording, browsing, full-body reads, planning phase, batch views).

## Known gaps

- Every skill is `crusor-origin: original`: GitHub access is unavailable in this environment, so no body was adapted from an upstream repository.
- The MCP hierarchy mirroring this tree is not built yet.

