# P0.6.7 — Phase A Forensic Baseline

Repository state inspected at `fa4d265c` (local == origin, branch
`feat/prompt-cache-stabilization`). Everything below is read from the code in
this repository, not from earlier milestone prose.

## 1. Current execution sequence

`EngineeringExecutionOrchestrator.run_task` → `_run_task_impl`
(`src/orchestration/orchestrator.py`):

| # | Stage | State | What actually happens |
| --- | --- | --- | --- |
| 1 | USER_REQUEST | — | task id created, journal `TASK_INITIALIZED` |
| 2 | REQUEST_UNDERSTANDING | UNDERSTANDING | `RequirementIntelligenceSystem.analyze` |
| 3 | PROJECT_DISCOVERY | DISCOVERY | repository intelligence persisted |
| 4 | REQUIREMENT_VALIDATION | SPECIFICATION_READY | requirement alignment |
| 5 | ARCHITECTURE_VALIDATION | ARCHITECTURE_REVIEW | blueprint + ADRs |
| 6 | ENGINEERING_PLAN | PLANNING | `EngineeringTaskPlanner.build_plan(max_nodes, requested_files, task_prompt)`; dispatch demand counted in files |
| 7 | CHANGE_IMPACT_ANALYSIS | IMPACT_ANALYSIS | impact report |
| 8 | TEST_BASELINE | BASELINE_TESTING | `TestBaselineManager.capture_baseline` (**no process spawned**, see §2) |
| 9 | APPROVAL_AND_PERMISSION_CHECK | READY_TO_IMPLEMENT | supervision gate |
| 10 | IMPLEMENTATION | IMPLEMENTING | `DependencyAwareScheduler.execute_plan` → `ModelExecutionAdapter.execute_node` per target file |
| 11 | BUILD_AND_TEST_EXECUTION | BUILDING → TESTING | "post" baseline captured (**again no process**), regression gate compares two filename lists |
| 12 | FAILURE_DIAGNOSIS | FAILURE_DIAGNOSIS | only if the synthetic gate reports a regression |
| 13 | BOUNDED_CORRECTION | CORRECTING | records a correction attempt; **does not dispatch or re-implement anything** |
| 14 | REGRESSION_VERIFICATION | VERIFYING | `IndependentVerificationEngine.verify_task` with `test_exec_map` |
| 15 | FINAL_DELIVERY | COMPLETED/FAILED | `DeliveryContract`, journal `TASK_DELIVERED` |

**The lifecycle ends after code generation.** The first real test process in a
desktop turn is the acceptance harness's own `pytest` after the turn is over.

## 2. Existing test execution capabilities

- `src/regression/baseline.py::discover_test_suites` walks the workspace and
  returns filenames matching `test_*`, `*_test.py`, `*.test.*`, `*.spec.*`.
- `capture_baseline` then **synthesizes a `TestCaseResult` marked
  `TestStatus.PASSING` with `duration_seconds=0.01` for every discovered file**.
  It never spawns a test process.
- `RegressionPreventionEngine.evaluate_and_enforce_regression_gates` receives
  `post_change_results` from the caller. The orchestrator passes
  `post_baseline.test_cases`, i.e. a second synthesized list from the same
  discovery function (orchestrator lines 547–556). The "regression gate" has
  therefore never executed a test.
- `src/runtime/verification_contracts.py` *can* run a shell command with a
  timeout (`_execute_command`, `subprocess.run(..., shell=True)`), but it is
  contract-driven, has no test discovery, no output parsing, and is not wired
  into the orchestrator.
- `src/runtime/reliability_metrics.py` contains a pytest/unittest output
  counter; it is not used by the orchestrator.
- `src/regression/integrity.py::TestIntegrityAuditor.audit_test_modification`
  detects test deletion, skip insertion and xfail conversion. It is available
  but the orchestrator never proposes test edits, so it is never consulted.

Result: `test_exec_map` in stage 14 is `{"test_baseline": "PASS"}` when the
synthetic summaries are empty (orchestrator line 599–600). Requirement
verification is told that a test named `test_baseline` passed.

## 3. Missing integration points

1. No execution after `IMPLEMENTATION_DONE`. The state machine has no
   `DISCOVERING_TESTS` / `EXECUTING_TESTS` / `REPAIRING` states.
2. No test-runner abstraction (discovery, interpreter selection, command
   construction, timeout, output capture, structured parsing).
3. No structured failure model. `FailureDiagnosisEngine`
   (`src/regression/diagnosis.py`) classifies a `TestCaseResult` produced by the
   synthetic baseline, not a real traceback.
4. No repair dispatch path in `ModelExecutionAdapter`. The only provider call
   is `_call_model_for_implementation`, which always writes a complete file from
   a plan node objective; there is no "here is the failing test and the current
   code, fix it" prompt.
5. No completion gate that can refuse completion on test evidence. `is_clean`
   only looks at `VerificationReport.verdict`.
6. No test evidence in `DeliveryContract` (no command, exit code, counts,
   report path, hashes).

## 4. Dispatch accounting behavior

- One provider dispatch per **target file** (`execute_node` loops
  `node.target_files`).
- `_call_model_for_implementation` (adapter lines 920–1103):
  verified pricing → prompt token upper bound → `finops.reserve` →
  client construction → token-ceiling enforcement → `mark_in_flight` →
  exactly one `llm.invoke` → authentic usage extraction → verified cost →
  `commit_reservation` → completion/extraction validation.
- `RetryLLMProxy` is forced to one attempt inside the adapter; the acceptance
  guard additionally claims a dispatch immediately before `invoke`.
- `Orchestrator._remaining_dispatch_budget()` = `min(ExecutionLimits.
  max_dispatch_budget, AcceptanceGuard.remaining)`.
- The planner counts files, not nodes (`_validate_plan_budget`), so the plan
  cannot exceed the budget before the first call.
- Any repair work must reuse this path, otherwise it becomes an unmetered
  provider execution path.

## 5. Financial settlement behavior

`OrchestrationFinOpsGovernor` persists `active`, `uncertain`, `settled`
reservations plus accounting to
`<workspace>/.crusorai/finops/<task>_finops.json` and the canonical SQLite
store (`<workspace>/.crusorai/sessions.db`).

- `commit_reservation` is idempotent per reservation id (duplicate = no-op).
- `release_reservation` is terminal; a released hold cannot be charged later.
- `mark_uncertain` retains the hold; `run_task`'s wrapper
  (`_finalize_finops_after`) releases lingering ACTIVE holds at task exit and
  **never** releases UNCERTAIN holds.
- Pre-dispatch refusals (`AcceptanceBudgetExceeded`, `TurnCancelledError`) are
  classified pre-dispatch and released.

## 6. Completion-state transition logic

- Stage 14 sets `is_clean = verdict in {VERIFIED, VERIFIED_WITH_LIMITATIONS}`.
- `verdict = TaskVerdict.COMPLETED if is_clean else FAILED`.
- Bridge: `task_completed = delivery.verdict == TaskVerdict.COMPLETED`
  (`src/bridge/__main__.py` line 1271); `turn_done` carries `completed`.
- There is no check for artifacts, test execution, unresolved mandatory
  requirements, mutation scope, or financial reconciliation before COMPLETED.
- `TaskVerdict` already has `BLOCKED`, `NOT_VERIFIED`,
  `COMPLETED_WITH_KNOWN_LIMITATIONS`; the bridge only treats `COMPLETED` as
  success.

## 7. Relevant files and functions

| Concern | File / function |
| --- | --- |
| Lifecycle | `src/orchestration/orchestrator.py` (`run_task`, `_run_task_impl`) |
| States / transitions | `src/orchestration/models.py` (`TaskExecutionState`, `VALID_TRANSITIONS`), `state_machine.py` |
| Stages | `src/orchestration/lifecycle.py`, `models.py` (`TaskLifecycleStage`) |
| Plan | `src/orchestration/planner.py` (`build_plan`, `merge_requirement_nodes`, `absorb_requirement_nodes`) |
| Provider | `src/orchestration/model_adapter.py` (`execute_node`, `_call_model_for_implementation`) |
| Mutations | `src/workspace/mutation_broker.py` (`create_file`, `modify_file`), `src/orchestration/implementation_engine.py` |
| FinOps | `src/orchestration/finops_governor.py`, `run_task` wrapper |
| Baseline/regression | `src/regression/baseline.py`, `engine.py`, `detector.py`, `diagnosis.py`, `integrity.py` |
| Verification | `src/verification/engine.py`, `requirement_verifier.py`, `completion_gate.py` |
| Requirements | `src/intelligence/requirement_extractor.py`, `requirement_models.py` |
| Bridge completion | `src/bridge/__main__.py` (`_run_turn`, orchestrator block) |
| Acceptance harness | `benchmarks/crusor_desktop_acceptance/live_acceptance.py`, `live_turn.py` |

## 8. Analyzer inflation (observed in live6)

`RequirementExtractor.extract` adds domain-template requirements
(`classification=REASONABLE_DEFAULT`, `status=PROPOSED`) for any detected domain
in addition to the explicit sentences. The planner consumes
`specification.all_requirements()` without filtering classification or status, so
a one-file prompt became a six-requirement, multi-file plan. The user-named file
guard mitigated the output but the root cause is that optional suggestions are
indistinguishable from mandatory work.

## 9. Risks introduced by the proposed repair lifecycle

1. **Arbitrary code execution.** Running project tests runs project code. A test
   file is executable input. The runner must be workspace-scoped, list-based
   (no `shell=True`), time-bounded, output-bounded, and must refuse paths outside
   the workspace. OS-level network isolation is not available in this
   environment; that is a documented limitation, not a claim of sandboxing.
2. **Unbounded cost.** A repair loop is a new provider-dispatch source. It must
   claim the same acceptance guard slot, reserve/settle through the same
   governor, and stop on `min(task limit, guard remaining)`.
3. **Test tampering.** The cheapest way to make tests pass is to weaken or
   delete them. Repair must default to the implementation; test edits are only
   allowed when the test contradicts the explicit contract, and every proposed
   test change must pass `TestIntegrityAuditor`.
4. **Flaky / environment failures.** Retrying a flaky test can burn the dispatch
   budget. Failures must be classified; infrastructure failures stop the loop
   rather than trigger a paid repair.
5. **Output explosion.** A full pytest traceback on a large suite can exceed
   prompt bounds; capture must be capped and redacted before being sent to a
   provider.
6. **State-machine drift.** Adding states without updating
   `VALID_TRANSITIONS` raises `InvalidTransitionError` mid-turn; transitions and
   tests must be added together.
7. **False completion.** If requirement verification treats "test file exists"
   as "behavior verified", the new gate becomes the old fiction. Verification
   must consume executed test outcomes, and a missing test must produce
   `NOT_VERIFIED`, not `VERIFIED`.

## 10. Baseline conclusion

The P0.6.6 live failure was not an LLM accident. The engine had no path from a
generated test file to an executed test, no way to diagnose a failure, and no
way to spend an authorized dispatch on a repair. P0.6.7 adds exactly that path
and refuses completion without its evidence.
