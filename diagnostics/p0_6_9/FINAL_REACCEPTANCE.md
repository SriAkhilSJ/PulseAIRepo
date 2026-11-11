# P0.6.9 — Final Live Re-Acceptance (one authorized attempt)

**Verdict: `P0.6.9_ACCEPTANCE_FAILED`.**

The implementation and both lifecycle fixes passed inspection and the full
offline preflight. The one authorized live run failed **during implementation
generation**, before tests or auxiliary titling: the source provider output hit
the 8192-token ceiling (`finish_reason='length'`) and the fail-closed adapter
refused to mutate the workspace. No auxiliary provider call was made because the
turn never completed.

Per the authorization, I stopped after this attempt. No further paid run was
executed.

## 1. Repository state (pre-run)

| Item | Value |
| --- | --- |
| Branch | `feat/prompt-cache-stabilization` |
| HEAD | `679fbb3dbc2a482f3113d9683705cf830466ee16` |
| origin HEAD | same (verified after fetch) |
| Working tree | clean |
| P0.6.9 commits present | `048fabb3`, `bea5e5df`, `c68ccc7c`, `6e216ded`, `f3ad118f`, `c8aab439`, `679fbb3d` |
| `live9/` | preserved unchanged |

## 2. Fix verification (code inspection)

- **Bridge ordering**: in the main turn path, `_maybe_autotitle_session(...,
  wait=True)` runs before `_finalize_evidence(...)` (bridge lines ~1451–1466).
  The manifest cannot declare completion before the governed title call.
- **Gateway lifecycle**: `GovernedProviderGateway.invoke` performs
  reserve → `mark_in_flight` → one `client.invoke` inside the invocation scope →
  authentic usage → actual cost → `commit_reservation` → terminal ledger record
  → return.
- **Harness ordering**: `finish()` calls
  `wait_for_auxiliary_accounting(self.workspace, timeout_s=90.0)` **before**
  `stop_app(app)`. Terminal states are `settled`, `uncertain`, `released`,
  `blocked`; only a `settled` auxiliary record satisfies the verdict.
- The P0.6.9 verdict requires: claims == settled invocations == aggregate
  calls; ≥2 engineering settled; ≥1 `session_titling` settled with
  provider/model/cost; non-empty title; ledger cost == aggregate cost (1e-6);
  no active/uncertain; ≤ ₹5.

## 3. Offline preflight

- Exact documented battery:
  **309 passed, 0 failed, 0 skipped** (233.09 s).
- `compileall` on all changed Python files: rc 0.
- Import smoke of gateway/ledger/adapter/factory/bridge/harness: OK.
- Invariant 7: maintained (0 changed, 0 drift, 0 undeclared).
- Secret scan: 0 real hits (only env-var names and the contextvar `token`
  assignment; reviewed false positives).
- Evidence checksums: 24/24 for `live9`.
- Exact prompt bytes from `live7` evidence; SHA-256
  `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8`.
- Offline tests use fakes/echo runners and scripted providers; no paid calls.

## 4. The live run

| Item | Value |
| --- | --- |
| Run | `p0_6_5_20261107T224903_ddf70775` |
| Session | `session-958f86b3aacf4b00a6b5311794bd7c0c` |
| Turn | `turn-894b79c852ba44098aab315fc26fe872` |
| Workspace | `ws-fb1cd8deeb1d5810` |
| Terminal | **`failed`**, completed=false, 79.459 s |
| Prompt SHA | `a887a669…` (exact historical bytes) |
| Contract | `82b51fcdda6b9f55edf1c94c668038e4c477dffa65a76e132312eb002a8c174b` |
| Components | 2 — SOURCE `src/duration.py` (REQ-001/002), TEST `tests/test_duration.py` (REQ-003) |
| Plan | `work_units=2`, `demand=2`, validated |
| Guard claims | **2** (source, tests) |
| Auxiliary claim | **0** — the turn failed before titling |

## 5. Exact failing stage

Journal (complete): `TASK_INITIALIZED`, `REQUEST_UNDERSTOOD`,
`DISCOVERY_COMPLETED`, `ARCHITECTURE_ESTABLISHED`, `CONTRACT_EXTRACTED`,
`FILES_ASSIGNED`, `PLAN_VALIDATED`, `PLAN_GENERATED`, `IMPACT_EVALUATED`,
`BASELINE_CAPTURED`. No `IMPLEMENTATION_DONE`, no tests, no verification.

Bridge stderr:

> `Task node task_duration failed with exception: Provider stopped before
> completing output for 'src/duration.py': finish_reason='length'.`

Source dispatch `res_6988ef02e5e6` produced exactly **8192 output tokens**.
`assert_provider_output_complete` rejected the response before extraction or
mutation. `src/duration.py` does not exist in the workspace; the test file does
(the second dispatch completed). The harness's independent pytest therefore
exited 2 (`ModuleNotFoundError`), smoke was not run.

This is a genuine model-output variance failure at the measured ceiling, not an
accounting failure. The engine behaved correctly: truncated code was refused,
nothing partial was written, and the turn failed closed.

## 6. Accounting reconciliation for this run

| Subsystem | Claims | Settled | Cost |
| --- | ---: | ---: | ---: |
| engineering source | 1 | 1 | ₹0.153887 (8192 output tokens) |
| engineering tests | 1 | 1 | ₹0.010265 |
| session titling | 0 | 0 | ₹0 |
| **total** | **2** | **2** | **₹0.164152** |

- Task FinOps: `calls_count=2`, `settled=2`, `uncertain=0`, `active=0`,
  SQLite + JSON reconciled.
- Session aggregate: 2 calls, ₹0.164152, 0 active/uncertain.
- Guard claims 2 == ledger settled 2 == aggregate calls 2.
- No unaccounted call in this run. The expected third (auxiliary) call never
  happened because the task did not complete.

The aux wait ran for 90 s, found no `session_titling` record, and honestly
returned `waited=false`. It did not fabricate a title or a settlement.

## 7. Acceptance criteria

| Criterion | Result | Evidence |
| --- | --- | --- |
| Electron submission | **PASS** | all 8 UI gates; prompt SHA matches |
| Real worker/bridge | **PASS** | guard pid in app-owned bridge set |
| Exact prompt SHA | **PASS** | `a887a669…` |
| Contract extraction | **PASS** | `82b51fcd…`, 2 components |
| Plan work units = 2 | **PASS** | `PLAN_VALIDATED` |
| SOURCE/TEST roles | **PASS** | `FILES_ASSIGNED` |
| Cross-file consistency | **NOT REACHED** | implementation failed |
| Source artifact generation | **FAIL** | truncated at 8192; refused |
| Test artifact generation | **PASS** | tests file written |
| In-turn pytest 10/10 | **FAIL** | never ran; harness rc 2 (missing module) |
| Independent smoke 9/9 | **FAIL** | not run |
| Task completion | **FAIL** | turn `failed` |
| Unauthorized mutations | **PASS** | none; fail-closed |
| Task accounting | **PASS** | 2/2 settled, ₹0.164152, reconciled |
| Auxiliary provider call | **FAIL** | no call; turn failed pre-titling |
| Auxiliary settlement | **FAIL** | none |
| Successful provider title | **FAIL** | empty |
| 3 physical claims | **FAIL** | 2 |
| No unaccounted physical calls | **PASS (2/2)** | no hidden claim |
| No active/uncertain holds | **PASS** | 0/0 |
| Aggregate reconciliation | **PASS** | 2 == 2 == 2, ₹0.164152 |
| Final verdict | **FAIL** | `P0.6.9_ACCEPTANCE_FAILED` |

## 8. Classification

- **Implemented**: invocation context/ledger, governed gateway, proxy
  fail-closed, adapter records, governed titling, harness wait, contract-first
  planning, cross-file validation, test execution/repair/completion gate.
- **Offline-tested**: 309 tests, including gateway lifecycle, fail-closed proxy,
  ledger attribution, titling wiring, wait helper, contract/planner/cross-file,
  repair integrity, FinOps regressions.
- **Live-tested (this run)**: Electron UI, worker/bridge, guard, contract
  extraction, role assignment, plan validation, task FinOps (2/2 settled),
  fail-closed truncation refusal.
- **Live-tested (earlier)**: engineering task completion with 10/10 tests
  (`live9`), and the P0.6.9 invocation ledger for task calls.
- **Live-accepted**: **nothing** — no P0.6.9 acceptance has passed.
- **Not proven live**: automatic title provider call/settlement, auxiliary
  invocation accounting, aggregate 3/3 reconciliation.

## 9. Remaining issues (unchanged, not hidden)

1. **Output-ceiling variance**: the same model that produced a 4.4k-token module
   in `live9` produced 8192 tokens here and was truncated. There is no
   generation-failure repair path (repair starts only after tests). This is the
   immediate blocker, not FinOps.
2. **Legacy AI lanes remain outside FinOps outside acceptance**: chat graph,
   summarizer, compaction, self-curation, planner helpers, one-shot runner,
   inline completions. They fail closed in acceptance without a reservation.
3. **No OS-level network sandbox.**
4. **No second live run** was attempted, per the authorization.

## 10. Evidence

`diagnostics/p0_6_9/live10/`: `evidence.json`, `acceptance_dispatch.json`
(2 claims), `orchestration_journal.jsonl` (10 events), engine journal,
`provider_invocations.jsonl` (2 settled task records), task FinOps file,
screenshots, signed turn manifest. `live9/` remains untouched.

SHA-256 manifest regenerated over both runs; see `SHA256SUMS.txt`.
