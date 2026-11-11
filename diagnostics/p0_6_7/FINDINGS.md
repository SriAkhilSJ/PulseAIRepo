# P0.6.7 — Autonomous Engineering Closure

## 1. Final verdict

**`P0.6.7_ACCEPTANCE_FAILED`.**

The lifecycle capability was built, qualified offline, and exercised live: the
engine executed the task's tests, diagnosed the failure, spent exactly one
bounded repair dispatch and refused completion when the repaired suite was
rejected for weakening. The live task still did not produce a passing artifact,
and the acceptance harness correctly refused to call it a pass.

| Summary | Value |
| --- | --- |
| Run | `p0_6_5_20261107T200147_b4abe305` |
| Turn | `turn-a4dacdd653774af4b87092d60e171887` |
| Dispatches / attempts | 4 / 1 each (guard budget 5) |
| Actual settled cost | **₹0.189584** (₹0.002078-equivalent USD ledger) |
| Settlements | 4/4, 0 uncertain, 0 active, SQLite reconciled |
| In-turn test runs | 1 (real pytest, exit 2, 1 collection error) |
| Repair dispatches | 1 (rejected before mutation by the test integrity audit) |
| Turn status | `failed` (correctly fail-closed) |
| Offline suite | **248 passed, 0 failed** (final tree) |

## 2. Architecture changes

- **In-turn test execution** (`src/orchestration/test_execution.py`, new):
  discovery (generated / explicit / related), real runner selection
  (pytest → unittest → npm test), list-based workspace-scoped execution with a
  hard timeout and tree kill, JUnit + text parsing, persisted evidence
  (command, cwd, exit code, timestamps, stdout/stderr, counts, report path,
  artifact hashes). The test subprocess environment has provider keys and
  acceptance bookkeeping scrubbed.
- **Failure diagnosis**: normalized categories
  (IMPLEMENTATION_DEFECT / TEST_EXPECTATION_DEFECT / ENVIRONMENT_FAILURE /
  DISCOVERY_FAILURE / EXECUTION_INFRASTRUCTURE_FAILURE / AMBIGUOUS), per-test
  messages/tracebacks, and a mapping from a test file back to the module under
  test.
- **Bounded repair**: `ModelExecutionAdapter` now has ONE paid dispatch path
  (`_dispatch_code_prompt`) shared by implementation and repair — verified
  pricing → reserve → one invoke → authentic usage → verified cost → commit.
  `repair_node` validates the completion receipt and AST and mutates through
  `WorkspaceMutationBroker`. Test edits pass `TestIntegrityAuditor` before
  mutation.
- **Lifecycle states**: `VALIDATING_ARTIFACTS`, `DISCOVERING_TESTS`,
  `EXECUTING_TESTS` were added to the existing state machine; diagnosis and
  correction reuse `FAILURE_DIAGNOSIS` / `CORRECTING`; verification and delivery
  reuse `VERIFYING` / `FINAL_DELIVERY`.
- **Completion gate**: `COMPLETED` now requires artifacts present and parseable,
  required tests actually executed and passing, no unresolved mandatory
  requirement, no out-of-scope mutation, no active/uncertain financial hold and
  no budget breach. Otherwise `BLOCKED` (tests cannot run) or `FAILED`, with
  reasons journaled in `COMPLETION_EVALUATED`.
- **Semantic verification**: requirements are verified against plan-scoped files
  and **executed test ids**. With tests required, file presence without a
  passing test is `NOT_VERIFIED`; unattributable evidence is `INCONCLUSIVE`;
  the completion gate refuses both. Optional analyzer suggestions are
  `NOT_APPLICABLE`.
- **Analyzer discipline**: sentence splitting preserves file paths (`src/x.py`
  is no longer shattered); only `EXPLICIT` / `NECESSARY_INFERRED` requirements
  become mandatory nodes; suggestions are recorded on
  `EngineeringPlanDAG.optional_requirements`.

## 3. FinOps evidence

Every provider call in the live run is a settled reservation:

| Reservation | Purpose | Status |
| --- | --- | --- |
| `res_0f2d5a02fd6f` | `node_task_req_001` | committed |
| `res_3ec9afb37258` | `node_task_req_002` | committed |
| `res_d94d8b0f6371` | `node_task_req_003` | committed |
| `res_921da3107e4c` | `repair_task_req_002` | committed |

`accounting.calls_count=4`, `settled=4`, `active=0`, `uncertain=0`,
`spent_inr=0.189584`, `input_tokens=4773`, `output_tokens=9066`, not breached.
Guard claims (4) equal settled calls (4). No retry, no failover.

## 4. Requirement verification evidence

`REQ-001` (module) → scoped `src/duration.py`, symbol `parse_duration`, executed
test `tests/test_duration.py::tests.test_duration` → **FAILED** (the executed
test errored). The other mandatory requirement (tests artifact) was also
unverified by execution. Optional suggestions (`REQ-004`/`REQ-005`) were
`NOT_APPLICABLE` and did not block the gate. Completion was refused with
`verification verdict is FAILED`.

## 5. Live acceptance result

All UI/bridge/guard/financial gates passed. The artifact failed independently:

- `src/duration.py` implements a `timedelta` API with units `d/w`, an `exactly`
  constant, and rejects `'1h30m'`; the user contract requires an `int` and units
  `h/m/s`.
- `tests/test_duration.py` imports `from duration import …` (not
  `from src.duration import …`), so pytest stopped at collection.
- The engine classified this correctly as a generated-test contract defect,
  dispatched one repair, and the repaired test dropped three test functions.
  `TestIntegrityAuditor` refused the mutation, so no weakened suite entered the
  workspace.

The fail-closed behavior is the correct outcome; the acceptance itself did not
pass. **No second live run was performed** (the milestone authorizes exactly one,
and a failed result is not converted into a pass).

## 6. Root cause and post-run correction (not live-proven)

The planner assigned user-named files FIFO. In this run:

- `REQ-002` ("Supported units: h, m, s.") received `tests/test_duration.py`;
- `REQ-003` (the tests sentence) also resolved to that path;
- three implementation dispatches were spent on two files while the tests
  requirement did not drive the test file.

After the live run, file assignment was made role-aware (test-intent
requirements → test files, others → source files), same-target nodes are merged,
and every user-named file is guaranteed a node. Re-running the planner on the
exact live prompt now yields **2 dispatches**: module (`REQ-001`+`REQ-002`) and
tests (`REQ-003`). A regression test pins this. The repair prompt now requires
preserving every existing test function name and assertion.

This correction is covered offline only. It is not claimed as live-proven.

## 7. Remaining defects

1. **Generated artifacts can still violate the explicit contract** (timedelta vs
   int; extra APIs). A single repair may not be enough for a module built on a
   different model of the problem; the engine correctly fails rather than
   accepting it.
2. **Test-rewrite repairs can drop tests.** The integrity auditor catches it and
   refuses the mutation, but the loop then stops (one dispatch spent, no
   fallback). A mechanical import-path repair or a targeted patch would avoid
   this; that is the next improvement.
3. **No OS-level sandbox** for test execution (documented; provider keys are
   scrubbed).
4. **Semantic verification is test-anchored**, not a proof of every
   natural-language requirement.
5. **Planner conservatism**: `max_nodes - 1` coalescing can waste one dispatch
   slot at tiny budgets (it cannot exceed the budget).

## 8. Commit map

| Commit | Content |
| --- | --- |
| `180ccab4` | engine: in-turn test lifecycle, diagnosis, bounded repair, completion gate, semantic verification, analyzer discipline |
| `12694aff` | offline lifecycle + verdict-gate tests |
| `0a86cd65` | acceptance harness: duration task, in-turn evidence, P0.6.7 gates, pinned test interpreter |
| `6af918a7` | BASELINE + first OFFLINE_QUALIFICATION (247 passed) |
| `e60abead` | post-live planner role-assignment fix, repair-prompt hardening, updated qualification (248 passed) |
| this docs commit | this report, acceptance matrix, live7 evidence, SHA256SUMS |

Branch `feat/prompt-cache-stabilization`; local HEAD == origin verified after
push.
