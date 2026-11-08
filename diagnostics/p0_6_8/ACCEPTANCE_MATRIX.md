# P0.6.8 — Acceptance Matrix

Run `p0_6_5_20261107T211727_fa1f0117` · turn `turn-5bd30b1c…` · workspace
`ws-d3b92f1c…` · evidence `diagnostics/p0_6_8/live8`. Prompt SHA
`a887a669…` (the exact P0.6.7 prompt).

**Final verdict: `P0.6.8_ACCEPTANCE_FAILED`** — every engineering criterion
passed; one financial-accounting criterion failed because an auxiliary
auto-title call claimed a dispatch that no task reservation settled.

| Criterion | Result | Evidence |
| --- | --- | --- |
| Genuine Electron UI submission | **PASS** | all 8 UI/bridge gates; manifest prompt SHA matches |
| Real worker/bridge ownership | **PASS** | guard pid in app-owned bridge set |
| Contract extraction | **PASS** | journal `CONTRACT_EXTRACTED`, hash `003a6fdb…`, 2 components |
| Explicit requirement classification | **PASS** | REQ-001..003 mandatory; REQ-004/005 optional suggestions |
| Role-aware file assignment | **PASS** | SOURCE `src/duration.py`, TEST `tests/test_duration.py` |
| Requirement-to-file mapping | **PASS** | REQ-001/002 → source; REQ-003 → test; no ambiguities |
| No lost requirements | **PASS** | plan `requirements` covers all three |
| Correct API and symbol contracts | **PASS** | `parse_duration(value) -> int`, units h/m/s, errors |
| Correct dispatch-demand calculation | **PASS** | `work_units=2`, `demand=2` |
| Pre-dispatch plan validation | **PASS** | `PLAN_VALIDATED` before implementation |
| Real provider dispatches | **PASS** | 2 task claims (model `z-ai/glm-5.3-flash`), 1 attempt each |
| FinOps reservation and settlement | **PASS** | 2/2 settled, 0 active, 0 uncertain, ₹0.125588, SQLite reconciled |
| Cross-file consistency | **PASS** | `CROSS_FILE_VALIDATED` ok; imports `src.duration`, symbol present |
| Source and test generation | **PASS** | both exist, AST valid |
| In-turn test execution | **PASS** | real pytest, 10/10 passed, JUnit + JSON evidence |
| Test integrity | **PASS** | no repair required; no weakening |
| Bounded repair, if needed | **PASS (not needed)** | zero failures on the first run |
| Final test execution | **PASS** | harness pytest exit 0 (10 passed) |
| Independent artifact verification | **PASS** | smoke: 1h30m, spaces, 45s, 5415, duplicate/unknown/empty/negative ValueError, non-string TypeError |
| Semantic requirement verification | **PASS** | `VERIFIED`; every requirement linked to executed passing tests |
| No unauthorized mutations | **PASS** | only the two contracted files |
| **No unaccounted dispatches** | **FAIL** | guard 3 claims vs 2 settled: auxiliary auto-title (`qwen/qwen3.7-flash`) used the provider outside task FinOps |
| Renderer receives truthful final result | **PASS** | turn terminal `completed`, delivery `COMPLETED`, 10 tests reported |
| SQLite/JSON reconciliation | **PASS** | task ledger reconciled (the failure is guard↔FinOps, not task ledger) |

## Engineering outcome

The exact historical failure is closed: the contract is understood before
writing, the source and test files agree, the generated import is the one the
user required, the return type is `int`, the units are `h/m/s`, and the full
suite runs and passes inside the task (10/10, no repair).

## Why the verdict is still FAILED

The dispatch budget is a financial boundary, not just a provider limit:

- claim 1: task `z-ai/glm-5.3-flash` — settled (`node_task_duration`)
- claim 2: task `z-ai/glm-5.3-flash` — settled (`node_task_tests_test_duration`)
- claim 3: **auxiliary `qwen/qwen3.7-flash`** — session auto-titler, no task
  reservation, no settlement

An unaccounted provider invocation is precisely what P0.6.6's financial
guarantee forbids. The acceptance was not converted to a pass.

The fix (`CRUSORAI_AUTOTITLE=off` + bridge refusal under
`CRUSORAI_ACCEPTANCE_RUN_ID`) is committed and offline-tested; no second live
run was performed.

## Evidence inventory

`live8/`: `evidence.json`, `acceptance_dispatch.json` (3 claims), engine journal
(contract/assignment/plan/cross-file/test/completion events), pytest JSON +
JUnit, screenshots, signed turn manifest, and the task FinOps ledger.
