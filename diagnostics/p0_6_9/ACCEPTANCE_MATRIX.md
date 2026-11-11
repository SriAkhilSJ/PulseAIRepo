# P0.6.9 — Acceptance Matrix

> **Final re-acceptance (live10, `p0_6_5_20261107T224903_ddf70775`):** failed at
> implementation generation — provider output hit the 8192-token ceiling
> (`finish_reason='length'`), no module was written, no tests ran, no auxiliary
> call occurred. The final verdict remains `P0.6.9_ACCEPTANCE_FAILED`.
> See `FINAL_REACCEPTANCE.md`. No further run.

Run `p0_6_5_20261107T221000_edc9f5de` · turn `turn-b140891f…` · workspace
`ws-3064aec2…` · evidence `diagnostics/p0_6_9/live9`.

**Final verdict: `P0.6.9_ACCEPTANCE_FAILED`.**

The engineering task passed; the auxiliary title invocation was claimed and
reserved but never settled because the app was stopped mid-call.

| Criterion | Result | Evidence |
| --- | --- | --- |
| Actual Electron UI submission | **PASS** | all 8 UI/bridge gates; manifest prompt SHA matches |
| Real desktop worker/bridge | **PASS** | guard pid in app-owned bridge set |
| Real engineering provider calls | **PASS** | 2 settled (model `z-ai/glm-5.3-flash`) |
| Real auxiliary provider call | **PASS** | claim 3, model `qwen/qwen3.7-flash`; reservation `res_2f16815efba3` created before dispatch |
| Automatic session titling exercised | **FAIL** | title empty; call was in flight at shutdown and never settled |
| Provider invocation inventory complete | **PASS** | `PROVIDER_INVENTORY.md` + ledger for the run |
| Reservation before every call | **PASS** | task reservations + aux hold before invoke |
| Authentic usage captured | **PARTIAL** | task usage captured (1201/4693); auxiliary usage never captured |
| Settlement for every invocation | **FAIL** | 3 claims, 2 settlements, 1 in-flight hold |
| No unaccounted calls | **FAIL** | auxiliary claimed call has no settlement/usage |
| No hidden retries or failover | **PASS** | 1 attempt per dispatch; guard max 5 |
| Task cost reconciled | **PASS** | ₹0.092296, 2/2, SQLite + JSON |
| Auxiliary cost reconciled | **FAIL** | hold ₹0.014149 unresolved, ₹0 settled |
| Aggregate session cost reconciled | **FAIL** | settled ₹0.092296 vs 3 physical claims |
| Contract-first planning | **PASS** | contract hash `06a61371…`, 2 components, no ambiguities |
| Correct source/test assignment | **PASS** | `src/duration.py` SOURCE, `tests/test_duration.py` TEST |
| In-turn tests pass | **PASS** | 10/10 pytest, exit 0 |
| Independent verification passes | **PASS** | smoke all 9 checks; pytest rc 0 |
| Engineering task completed truthfully | **PASS** | delivery `COMPLETED`, turn `completed` |
| SQLite/JSON reconciliation | **PASS (task)** | task ledger reconciled; aux hold has no usage to reconcile |
| Final renderer result | **PASS** | turn_done completed; summary rendered |
| No unauthorised mutations | **PASS** | only the two contracted files |

## Engineering outcome (what the run proved)

The exact historical task passed end-to-end with the contract-first path:

- 2 role-correct work units, demand 2;
- contract `parse_duration(value) -> int`, units h/m/s, errors and imports;
- cross-file report clean;
- 10/10 in-turn tests;
- independent harness smoke passes;
- no repair dispatch needed;
- task cost ₹0.092296, 2/2 settled.

## Why the verdict is failed

`FINANCIAL_RECONCILIATION.md` documents 3 physical claims / 2 settlements and
one in-flight auxiliary hold. The auxiliary provider call was killed when the
harness stopped the app after reading the evidence manifest, which the bridge
had finalized before running the governed title call.

A claimed-but-unsettled invocation is exactly the condition P0.6.9 forbids, so
the result is not converted into a pass. The bridge/harness ordering fixes are
committed but not live-proven; no second run was performed.

## Evidence inventory

`live9/`: `evidence.json`, `acceptance_dispatch.json` (3 claims),
`provider_invocations.jsonl` (2 settled task records), engine journal, pytest
JSON/JUnit, task and auxiliary FinOps files, screenshots, signed turn manifest.
