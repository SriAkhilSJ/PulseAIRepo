# Verification — the Architect library

Generated 2026-10-30 from repository state, after the breadth pass across
cloud, ai-ml, data, mobile and desktop.

## Inventory

| Domain | Skills |
|---|---|
| `ai-ml-architect/` | 31 |
| `cloud-and-devops-architect/` | 36 |
| `data-engineering-architect/` | 29 |
| `desktop-architect/` | 20 |
| `mobile-architect/` | 28 |
| `website-architect/` | 76 |
| **total** | **220** |

Counts include each domain's crown skill.

## Breadth status

| Domain | Books | Status |
|---|---|---|
| `website-architect/` | 76 | reference resolution |
| `cloud-and-devops-architect/` | 36 | at reference resolution, 7 shelves |
| `ai-ml-architect/` | 31 | at reference resolution, 8 shelves |
| `data-engineering-architect/` | 29 | at reference resolution, 7 shelves |
| `mobile-architect/` | 28 | at reference resolution, 5 shelves |
| `desktop-architect/` | 20 | at reference resolution, 5 shelves |

Reference resolution means: one book per framework or primitive, so a task lands on
the book about SQS rather than a book about messaging. It does not mean depth —
each book is 3–5 KB of decisions, failure modes and verification receipts.
`references/` material with real upstream citations would be a separate pass.

## Spec conformance

- files checked: **220**
- name == parent directory: **220/220**
- crusor-path == path from skills/: **220/220**
- unique names: **220/220**
- longest body: **5958 chars** (cap 6000)
- longest description: **406 chars** (limit 1024)
- provenance present: **220/220** (218 `original`, 2 `adapted`, both MIT/Apache-2.0 with a pinned SHA) (`crusor-origin`, `crusor-sources`, `crusor-verified-on`)
- brand gate: `grep -rin "^description:.*nous" skills/` → no matches

## Structural conformance (enforced by test)

`scripts/audit_skills.py` runs the library's own rules; `src/tests/test_skill_library_conformance.py`
fails the build on any violation.

- books checked: **220**, violations: **0**
- required in every book: `When to use`, `When NOT to use`, 2+ decision sections
  (domain crowns are index books and are exempt from this one), a failure-modes
  section, `Verification receipts`
- body between **2500 and 6000** chars (injection cap), under 500 lines
- 6+ triggers; adapted books must name a permissive licence and pin `owner/repo@sha`

## Runtime

- discovered as bundled skills: **240** (220 architect + 20 process/connector skills)
- architect skills with `phase: planning`: **220/220**
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

- 12 focused skill suites (including the conformance gate and the MCP server) → **261 passed, 1 skipped**
  (`test_agent_skills_tree`, `test_skill_library`, `test_skill_tools`,
  `test_skill_bundled`, `test_skill_lifecycle`, `test_skills_hub`,
  `test_skills_invalidation`, `test_hermes_prompt_parity`,
  `test_hermes_tool_name_parity`, `test_skill_library_conformance`,
  `test_skills_mcp_server`, `test_mcp_client`).
- `pytest src/tests/test_agent_skills_tree.py` → 21 passed.
- Full `pytest src/tests -q` baseline at this branch: 2975 passed / 20 pre-existing
  unrelated failures.

## Quality scorecard

The auditor also scores each book on evidence, not taste: size, decision density,
named APIs, quantified claims, tables, receipts and failure-mode bullets.

| Domain | mean | min | max |
|---|---|---|---|
| `website-architect` | 66.7 | 40 | 78 |
| `cloud-and-devops-architect` | 64.8 | 59 | 76 |
| `mobile-architect` | 64.1 | 57 | 77 |
| `desktop-architect` | 64.0 | 57 | 80 |
| `data-engineering-architect` | 62.7 | 53 | 76 |
| `ai-ml-architect` | 62.2 | 56 | 74 |

Every one of the 220 books is reachable: a query built from a book's own triggers
selects that book during planning, asserted in the gate test. Weakest books by score:
`website-architect` (index crown, by design), `lineage-architect`,
`semantic-layer-architect`, `data-observability-architect`, `react-ui-libraries-architect`
— these are the next depth pass, not defects.

## Known gaps

- Provenance is mixed: 218 books are `crusor-origin: original`; 2 desktop books are
  `adapted` from public MIT/Apache-2.0 skill repositories, pinned by commit SHA in
  `skills/PROVENANCE.md`. The rest of the public corpus surveyed was thin, unlicensed
  or out of scope — see that file for the per-repo verdicts.
- No `references/` depth yet — books carry decisions and receipts, not citations.
- The MCP hierarchy mirroring this tree is deferred by instruction.
