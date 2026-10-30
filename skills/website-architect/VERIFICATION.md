# Verification — the Architect library

Generated 2026-10-30 from repository state, after the breadth pass across
cloud, ai-ml, data, mobile and desktop.

## Inventory

| Domain | Skills |
|---|---|
| `ai-ml-architect/` | 31 |
| `cloud-and-devops-architect/` | 36 |
| `data-engineering-architect/` | 29 |
| `desktop-architect/` | 18 |
| `mobile-architect/` | 28 |
| `website-architect/` | 76 |
| **total** | **218** |

Counts include each domain's crown skill.

## Breadth status

| Domain | Books | Status |
|---|---|---|
| `website-architect/` | 76 | reference resolution |
| `cloud-and-devops-architect/` | 36 | at reference resolution, 7 shelves |
| `ai-ml-architect/` | 31 | at reference resolution, 8 shelves |
| `data-engineering-architect/` | 29 | at reference resolution, 7 shelves |
| `mobile-architect/` | 28 | at reference resolution, 5 shelves |
| `desktop-architect/` | 18 | at reference resolution, 5 shelves |

Reference resolution means: one book per framework or primitive, so a task lands on
the book about SQS rather than a book about messaging. It does not mean depth —
each book is 3–5 KB of decisions, failure modes and verification receipts.
`references/` material with real upstream citations would be a separate pass.

## Spec conformance

- files checked: **218**
- name == parent directory: **218/218**
- crusor-path == path from skills/: **218/218**
- unique names: **218/218**
- longest body: **5958 chars** (cap 6000)
- longest description: **406 chars** (limit 1024)
- provenance present: **218/218** (`crusor-origin`, `crusor-sources`, `crusor-verified-on`)
- brand gate: `grep -rin "^description:.*nous" skills/` → no matches

## Runtime

- discovered as bundled skills: **238** (218 architect + 20 process/connector skills)
- architect skills with `phase: planning`: **218/218**
- `get_relevant_skills(task, phase="executing")` → **0** architect skills
- `get_relevant_skills(task, phase="planning")` → routed normally

## Routing (whole-word trigger match, phase=planning)

| Task | Skills selected |
|---|---|
| build a windows native app | mobile-architect, winui-architect |
| mac app with menu bar | appkit-architect, desktop-distribution-architect |
| ship a linux app via flatpak | gtk-architect |
| screen reader support in our desktop app | accessibility-architect, desktop-accessibility-architect, desktop-architect, mobile-accessibility-architect |
| serial port scale integration | desktop-hardware-architect |
| app should run in the tray | desktop-tray-and-menus-architect, terminal-connector |
| translate the installer | desktop-distribution-architect, desktop-localization-architect |
| crash reports from desktop users | desktop-telemetry-architect, mobile-observability-architect, systematic-debugging |
| test our electron installer | desktop-architect, desktop-distribution-architect, electron-architect |
| auto update keeps failing | desktop-architect, desktop-distribution-architect, desktop-update-architect, systematic-debugging |
| electron app needs a secure bridge | desktop-architect, desktop-ipc-architect, electron-architect |
| build an ios app with swiftui | ios-architect, ios-swiftui-architect, mobile-architect |
| app works offline in the field | mobile-architect, mobile-offline-sync-architect, pwa-architect |
| design a rest api | rest-architect, rest-graphql-debug |

Skill selection is additive by design — cross-domain hits (e.g. a screen-reader task
reaching both the desktop and mobile accessibility books) are deduplicated when the
prompt is assembled.

## Verification runs

- 9 focused skill suites → **224 passed, 1 skipped**
  (`test_agent_skills_tree`, `test_skill_library`, `test_skill_tools`,
  `test_skill_bundled`, `test_skill_lifecycle`, `test_skills_hub`,
  `test_skills_invalidation`, `test_hermes_prompt_parity`,
  `test_hermes_tool_name_parity`).
- `pytest src/tests/test_agent_skills_tree.py` → 21 passed.
- Full `pytest src/tests -q` baseline at this branch: 2975 passed / 20 pre-existing
  unrelated failures.

## Known gaps

- Every book is `crusor-origin: original`: GitHub access is unavailable here, so no
  body is adapted from an upstream repository. These are authored architect books.
- No `references/` depth yet — books carry decisions and receipts, not citations.
- The MCP hierarchy mirroring this tree is deferred by instruction.
