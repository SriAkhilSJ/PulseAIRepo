# P0.6.8 — Offline Qualification

Baseline `1beced7d` · branch `feat/prompt-cache-stabilization`.
No live provider was called during this phase. All executions below use the
real engine, real pytest subprocesses and a scripted provider double with
authentic usage receipts (priced model `groq`/`qwen/qwen3.6-27b`).

## 1. Exact command

```powershell
.\.venv\Scripts\python.exe -m pytest `
  src/tests/test_p0_6_8_contract_first.py `
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

**293 passed, 0 failed, 0 skipped in 225.13 s.**

| Suite | Tests | Result |
| --- | --- | --- |
| `test_p0_6_8_contract_first.py` (new) | 44 | passed |
| `test_p0_6_7_autonomous_closure.py` | 24 | passed |
| `test_p0_6_6_execution_reliability.py` | 27 | passed |
| `test_p0_6_5_live_acceptance.py` | 32 | passed |
| `test_p0_6_4_desktop_observability.py` | 31 | passed |
| `test_p0_6_4_1_acceptance_retry_clamp.py` | 11 | passed |
| `test_p0_5_1_output_integrity.py` | 11 | passed |
| `test_p0_3_orchestrator_integration.py` | 7 | passed |
| `test_planner_phatic_gate.py` | 18 | passed |
| `test_phase_9_7_enterprise_finops.py` | 20 | passed |
| `test_phase_12_1_1_identity_finops_production.py` | 5 | passed |
| bridge suites (8 files) | 63 | passed |
| **Total** | **293** | **293 passed** |

The P0.6.7 final baseline was 247; P0.6.8 adds 44 contract/planner/cross-file/
repair/isolation tests and 2 net acceptance-gate tests (P0.6.5 31 → 32).

## 3. Exact historical reproduction

- Prompt source: `diagnostics/p0_6_7/live7/evidence.json` (read at test time).
- SHA-256 asserted: `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8`.
- Contract: 2 components — SOURCE `src/duration.py` (REQ-001, REQ-002), TEST
  `tests/test_duration.py` (REQ-003); no ambiguities.
- Plan: 2 work units, demand 2, all ids preserved, role-correct.
- Scripted provider reproduces the P0.6.7 class of artifacts: bare
  `from duration import`, `timedelta` return, `exactly` constant, tests calling
  `total_seconds()`.
- Engine result: mechanical import rewrite (no dispatch) removes the invented
  `exactly`; static checks flag `return_contract_violation` and
  `forbidden_float`; tests fail; source repaired; the test’s `total_seconds()`
  expectation is classified as a contract contradiction and repaired under the
  inventory audit; final pytest 6/6; cross-file clean; `COMPLETED`.
- Provider dispatches: 4 (2 implementation + 2 repairs), all settled; 0 active,
  0 uncertain.
- Journal contains `CONTRACT_EXTRACTED`, `FILES_ASSIGNED`, `PLAN_VALIDATED`,
  `CROSS_FILE_VALIDATED`, `TEST_REPAIR_APPLIED` (dispatch=false),
  `REPAIR_DISPATCHED`, `TESTS_REEXECUTED`, `COMPLETION_EVALUATED`.

## 4. Adversarial planner coverage

42 tests across six classes: contract extraction (6), role assignment and the
16 required scenarios (11), plan validation (7), cross-file consistency (9),
repair integrity (7), historical lifecycle + contract gate (2). See
`PLANNER_ADVERSARIAL_RESULTS.md` and `CONTRACT_REGRESSION_RESULTS.md`.

## 5. Financial results (offline)

- Historical lifecycle: `calls_count=4`, `settled=4`, `active=0`,
  `uncertain=0`; duplicate settlement and released-hold behavior remain covered
  by the P0.6.6/6.7 suites.
- Contract gate case (tests pass, contract violated, no repair allowed): 2 calls,
  2 settled, verdict `FAILED`, no hidden dispatch.
- No provider call occurs during contract extraction or plan validation: both
  run before `PLAN_VALIDATED`, and a rejected plan journals `PLAN_REJECTED`.

## 6. Changed files

New: `src/orchestration/contract.py`,
`src/tests/test_p0_6_8_contract_first.py`,
`diagnostics/p0_6_8/` (this report, baseline, adversarial/regression results).

Modified: `src/orchestration/planner.py`, `orchestrator.py`, `model_adapter.py`,
`models.py`, `test_execution.py`; `src/verification/engine.py`,
`requirement_verifier.py`; `benchmarks/crusor_desktop_acceptance/__main__.py`,
`live_acceptance.py`, `live_turn.py`; `src/tests/test_p0_6_5_live_acceptance.py`.

## 7. Invariant 7

`check_invariant7('.')`: **maintained** — 0 changed files in `desktop/vscode`,
0 drift, 0 undeclared changes.

## 8. Secret scan

`scripts/secret_scan_p0_6_6.py` over every changed file: **0 real hits.**
1 reviewed false positive: `orchestrator.py` `token =
self.supervision_gate.grant_approval(...)` — an in-memory approval token, not a
credential.

## 8b. Acceptance isolation (added after the live run)

The one live acceptance exposed a real accounting gap: the session auto-titler
called the auxiliary model (`qwen/qwen3.7-flash`) inside the acceptance turn.
The acceptance guard counted that call (3 claims) but no task FinOps reservation
settled it (2 settlements). The task itself passed 10/10 tests.

Committed fix:

- `build_acceptance_env` sets `CRUSORAI_AUTOTITLE=off`;
- `BridgeServer._auxiliary_llm_allowed()` refuses auxiliary model calls whenever
  `CRUSORAI_ACCEPTANCE_RUN_ID` is set, independent of the env flag;
- two tests pin the env value and the bridge refusal.

This is offline-proven only (no second live run was authorized).

## 9. Known limitations

1. **Static consistency is not semantic proof.** `validate_cross_file` checks
   AST shape (imports, symbols, parameters, annotations, extra public API,
   timedelta/float usage). Behavior is proven only by executed tests; the report
   says so explicitly.
2. **No OS-level sandbox** for test execution (provider keys and acceptance
   bookkeeping are scrubbed from the subprocess env).
3. **Test repair remains prompt-driven** when a behavioral expectation must
   change; the inventory audit guarantees no test/assertion/parameter loss, but
   the provider must still produce a valid rewrite. Mechanical import repair is
   deterministic and dispatch-free.
4. **Multiple source components share one contract field set** parsed from the
   user prompt. A prompt that assigns different return types to different files
   would need per-file contract blocks; the current validator would flag the
   mismatch rather than guess.
5. **Planner conservatism** for non-contract fallbacks remains (`max_nodes - 1`),
   but the contract path measures demand as unique target files.
