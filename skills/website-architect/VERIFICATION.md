# Verification — the Architect library

Generated 2026-10-30 from repository state.

## Inventory

| Domain | Skills |
|---|---|
| `desktop-architect/` | 5 |
| `mobile-architect/` | 6 |
| `website-architect/` | 76 |
| **total** | **87** |

## Spec conformance

- files checked: **87**
- name == parent directory: **87/87**
- crusor-path == path from skills/: **87/87**
- unique names: **87/87**
- longest body: **5955 chars** (cap 6000)
- longest description: **406 chars** (limit 1024)
- provenance present: **87/87**

## Runtime

- discovered as bundled skills: **107**
- phase = planning: **87**
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
| app store signing | desktop-distribution-architect, mobile-release-architect |
| build a desktop app in electron | desktop-architect, electron-architect |
| tauri vs electron | desktop-architect, electron-architect, tauri-architect |
| sign our mac app | — (browse fallback) |
| auto update for windows | desktop-architect, desktop-distribution-architect |

## Verification runs

- `pytest src/tests -q` → 2975 passed, 20 failed, 23 skipped, 1 xfailed — the 20 are the repository's pre-existing unrelated failures (baseline 21).
- `pytest src/tests/test_agent_skills_tree.py` → 18 passed: spec conformance, uniqueness, path integrity, domain crowns, capability contracts, discovery.
- `pytest src/tests/test_skill_library.py` → 13 passed: shelf recording, browsing, full-body reads, planning phase, batch views.

## Known gaps

- Every skill is `crusor-origin: original`: GitHub access is unavailable here, so no body was adapted from an upstream repository.
- The MCP hierarchy mirroring this tree is not built yet.

