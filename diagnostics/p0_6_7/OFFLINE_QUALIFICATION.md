# P0.6.7 — Offline Qualification

Run date: 2026-11-07 (local) · Branch `feat/prompt-cache-stabilization`
Baseline: `fa4d265c` (P0.6.6 closed) · Implementation commits:
`180ccab4` (engine), `12694aff` (tests), `0a86cd65` (acceptance harness).

No live provider was called during this phase.

## 1. Exact command

```powershell
.\.venv\Scripts\python.exe -m pytest `
  src/tests/test_p0_6_7_autonomous_closure.py `
  src/tests/test_p0_6_6_execution_reliability.py `
  src/tests/test_p0_6_5_live_acceptance.py `
  src/tests/test_p0_6_4_desktop_observability.py `
  src/tests/test_p0_6_4_1_acceptance_retry_clamp.py `
  src/tests/test_p0_5_1_output_integrity.py `
  src/tests/test_p0_3_orchestrator_integration.py `
  src/tests/test_planner_phatic_gate.py `
  src/tests/test_phase_9_7_enterprise_finops.py `
  src/tests/test_phase_12_1_1_identity_finops_production.py `
  src/tests/test_bridge_protocol_v2.py `
  src/tests/test_bridge_runtime_protocol.py `
  src/tests/test_bridge_orchestrator_protocol.py `
  src/tests/test_bridge_transport.py `
  src/tests/test_bridge_workspace_routing.py `
  src/tests/test_bridge_stall_watchdog.py `
  src/tests/test_run_bridge_turn.py `
  src/tests/test_live_revision_and_bridge_contract.py -q
```

## 2. Result

**247 passed, 0 failed, 0 skipped in 204.31 s.**

Per-suite collection (verified with `--collect-only`):

| Suite | Tests | Result |
| --- | --- | --- |
| `test_p0_6_7_autonomous_closure.py` (new) | 23 | passed |
| `test_p0_6_5_live_acceptance.py` (P0.6.7 verdict gates) | 31 | passed |
| `test_p0_6_6_execution_reliability.py` | 27 | passed |
| `test_p0_6_4_desktop_observability.py` | 31 | passed |
| `test_p0_6_4_1_acceptance_retry_clamp.py` | 11 | passed |
| `test_p0_5_1_output_integrity.py` | 11 | passed |
| `test_p0_3_orchestrator_integration.py` | 7 | passed |
| `test_planner_phatic_gate.py` | 18 | passed |
| `test_phase_9_7_enterprise_finops.py` | 20 | passed |
| `test_phase_12_1_1_identity_finops_production.py` | 5 | passed |
| bridge suites (8 files) | 63 | passed |
| **Total** | **247** | **247 passed** |

The previous P0.6.6 baseline was 220; the delta is +23 new lifecycle tests, +4
net verdict-gate tests (P0.6.5 file 27 → 31), and no removed tests.

## 3. What the new tests prove

Lifecycle (executed with a scripted provider double carrying authentic usage
receipts; priced provider `groq` / `qwen/qwen3.6-27b`):

- real pytest execution over the task workspace: counts, exit code, JUnit
  report, stdout/stderr, artifact hashes, persisted evidence;
- a buggy module + correct tests produces `FAILURES_CLASSIFIED`
  (IMPLEMENTATION_DEFECT) and exactly one `REPAIR_DISPATCHED`, then
  `TESTS_REEXECUTED` with 4/4 passing and `COMPLETED`;
- every dispatch (2 implementation + 1 repair) is reserved and settled:
  `calls_count=3`, `settled=3`, `active=0`, `uncertain=0`;
- a failed repair cannot complete; budget exhaustion stops before/after the
  last authorized repair; cancellation stops the loop before a repair dispatch;
- a test repair that empties/weakens a test is rejected by
  `TestIntegrityAuditor` before mutation;
- discovery refuses a path outside the workspace; timeouts are classified as
  infrastructure, not code defects; third-party `ModuleNotFoundError` is an
  environment failure; a generated test with an invalid import path is a test
  defect; a syntax-invalid generated test is a test defect.

Semantic verification and completion:

- with tests required, an existing parsed file with no executed test is
  `NOT_VERIFIED` and the gate returns `FAILED`;
- a failed executed test fails the requirement; a passing executed test
  verifies it; runner errors yield `INCONCLUSIVE` and the gate returns
  `BLOCKED`;
- optional analyzer suggestions are `NOT_APPLICABLE` and cannot block a
  user-scoped task.

Analyzer discipline: `src/slugify.py` survives sentence splitting intact, and a
`REASONABLE_DEFAULT` requirement never becomes a plan node (it is recorded in
`EngineeringPlanDAG.optional_requirements`).

## 4. Failures found and fixed while qualifying

1. **JUnit `classname` was not a path** (`tests.test_slugify`), so a failing
   test could not be mapped to `src/slugify.py` and no repair was selected.
   Normalized dotted names (and collection pseudo-tests) to workspace paths.
2. **Summary-only collection errors lost the diagnosis evidence.** The
   classifier now falls back to the runner stream when a case has no
   traceback, and classifies a generated test's invalid project import as a
   test-expectation defect.
3. **Optional requirements blocked completion** (`NOT_IMPLEMENTED` for
   "secure credential storage"). Optional suggestions are now `NOT_APPLICABLE`
   and excluded from the completion total.
4. **The task budget did not decrement offline.** `_remaining_dispatch_budget`
   now subtracts the governor's real reservation count when no acceptance guard
   is active, so a repair cannot exceed `CRUSORAI_ACCEPTANCE_MAX_DISPATCHES` or
   `ExecutionLimits.max_dispatch_budget`.
5. **Planner coalescing reserved a dispatch for the free verification node**,
   producing a one-file plan at budget 2. The conservative P0.6.6 `-1` was kept
   (its tests pin it); the exhaustion test uses budget 3 instead, and every
   dispatch is counted against the real reservation total.

## 5. Changed files (implementation commit `180ccab4`)

New: `src/orchestration/test_execution.py`.

Modified: `src/orchestration/orchestrator.py`, `model_adapter.py`, `models.py`,
`planner.py`; `src/intelligence/requirement_extractor.py`;
`src/verification/models.py`, `requirement_verifier.py`, `engine.py`,
`completion_gate.py`.

Tests commit `12694aff`: new
`src/tests/test_p0_6_7_autonomous_closure.py`; updated
`src/tests/test_p0_6_5_live_acceptance.py`.

Harness commit `0a86cd65`: `benchmarks/crusor_desktop_acceptance/live_acceptance.py`,
`live_turn.py`, `__main__.py`.

## 6. Invariant 7

`check_invariant7('.')`: **maintained** — 0 changed files in `desktop/vscode`,
0 drift, 0 undeclared changes.

## 7. Secret scan

`scripts/secret_scan_p0_6_6.py` over every changed source and harness file:

- **0 real hits.**
- 1 reviewed false positive: `src/orchestration/orchestrator.py:577`
  `token = self.supervision_gate.grant_approval(...)` — an in-memory approval
  token object, not a credential. No key, bearer token, private key or secret
  assignment exists in the changed tree.

## 8. Known limitations (carried into the live report)

1. **No OS-level sandbox.** Test processes run with the workspace as cwd and a
   scrubbed environment (provider keys and acceptance bookkeeping removed), but
   there is no network/namespace isolation. A malicious test could still make
   network calls. This is documented, not claimed as containment.
2. **Repair is implementation-first.** Only generated tests that contradict the
   explicit contract are eligible for a test edit, and only through the
   integrity auditor. User-authored tests are never edited.
3. **One runner family per language.** pytest/unittest/npm test are supported;
   other toolchains return `NO_RUNNER` and block completion when testing is
   required.
4. **Semantic verification is test-anchored, not proof of every natural-language
   requirement.** Optional suggestions are explicitly non-blocking.
5. **The planner keeps the conservative `max_nodes - 1` coalescing rule** from
   P0.6.6 even though the verification node costs no dispatch. It can waste one
   dispatch slot for tiny budgets; it cannot exceed the budget.
