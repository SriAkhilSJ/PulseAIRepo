# Verification — website-architect skill library

Generated 2026-10-30 from the repository state, not from intent.

## Inventory

| Branch | Skills |
|---|---|
| `api-development-architect/` | 7 |
| `backend-development-architect/` | 11 |
| `database-engineering-architect/` | 6 |
| `frontend-development-architect/` | 33 |
| `security-architect/` | 6 |
| `testing-and-deployment-architect/` | 7 |
| `ui-ux-implementation-architect/` | 5 |
| **total** | **75** |

## Spec conformance (every SKILL.md)

- files checked: **75**
- name == parent directory: **75/75**
- crusor-path == real location: **75/75**
- unique names across the repo: **75/75**
- longest body: **5955 chars** (injection cap 6000)
- longest description: **406 chars** (spec limit 1024)
- every skill carries triggers: **75/75**
- every skill carries provenance: **75/75**

## Runtime behaviour

- discovered as bundled skills: **75 architect skills**
- all recorded phase `planning`: **75/75**
- injected while executing: **1** (architect skills excluded)
- injected while planning: **2**

## Routing (trigger match, whole-word)

| Task | Skills selected |
|---|---|
| the site is slow on mobile | web-performance-architect |
| add a csp header | browser-security-architect |
| design a rest api | rest-architect, rest-graphql-debug |
| our graphql resolves n+1 | graphql-architect, rest-graphql-debug |
| postgres query is slow | db-connector, mcp, postgres-architect |
| add redis caching for sessions | nextjs-architect, redis-architect, web-performance-architect |
| our pipeline takes 40 minutes | ci-cd-architect, testing-and-deployment-architect |
| we need a canary rollout | release-strategy-architect, testing-and-deployment-architect |
| implement this figma design | design-handoff-architect |
| add oauth login | api-auth-architect |
| harden our ci pipeline | ci-cd-architect, supply-chain-architect, testing-and-deployment-architect |
| should we use trpc or rest | rest-architect, trpc-architect |
| how do we store api keys | secrets-management-architect |
| write a dockerfile for the service | containerization-architect |
| add tracing for the api | observability-architect |

## Library operations

- `skills_list()` → shelves at the root; `skills_list(shelf)` → one level at a time
- `skill_view(name)` → full body from disk, any depth, path-confined to the library
- `skill_view("a, b, c")` → several books per call, labelled and separated

## Test evidence

- `src/tests/test_agent_skills_tree.py` — discovery, spec conformance, uniqueness, path integrity, branch completeness
- `src/tests/test_skill_library.py` — shelf recording, browsing, full-body reads, planning phase, batch views
- `src/tests/test_skill_tools.py`, `test_skill_bundled.py`, `test_skill_lifecycle.py`, `test_skills_hub.py`, `test_skills_invalidation.py`, `test_hermes_prompt_parity.py`

## Full-suite regression run

- `pytest src/tests -q` → **2975 passed, 20 failed, 23 skipped, 1 xfailed** (277 s)
- The 20 failures are the pre-existing, unrelated failures in this repository
  (api-contract parity, hermes timing, reasoning-effort threading, scaffold
  layout); none of them touch skills, and the count is one *lower* than the
  baseline recorded before this work (21), with 31 more tests passing.
- The one skill-related regression introduced during a library-wide change —
  `test_skill_view_is_case_insensitive_and_never_raises` failing once the
  catalogue exceeded the 40-name listing cap — was found by this run and fixed
  by replacing the truncated name dump with browse guidance plus close matches.

## Known gaps

- Provenance is `original` for every skill: GitHub access is unavailable in this environment, so no body was adapted from an upstream repo. The `crusor-origin` field says so honestly.
- MCP hierarchy is not built yet.

