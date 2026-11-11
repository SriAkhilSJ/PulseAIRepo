# Offline Qualification

Status: **offline only**. No live provider, Electron acceptance run, paid
benchmark or title call was executed. External provider spend: **₹0.00**.

All tests use deterministic fake clients / scripted responses. No test opens a
network connection to a model provider.

---

## 1. Generation-boundary suite

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/test_generation_boundary.py -q
```

Result:

```text
15 passed in 30.79s
```

Run again after the final independent-smoke and two-file-mutation assertions were
added: **15 passed**.

| Group | Test | Result |
| --- | --- | --- |
| Finish reason | incomplete reasons (`length`, `max_tokens`, `max_output_tokens`, `token_limit`, `incomplete`) fail closed | pass |
| Finish reason | `stop`, `tool_calls`, missing reason pass | pass |
| Finish reason | malformed metadata does not crash | pass |
| Finish reason | unclosed fence is not extracted | pass |
| Ceiling | provider-aware effective cap reaches `invoke(max_tokens=...)` | pass |
| Ceiling | unknown model does not invent a cap | pass |
| Ceiling | complete first response does not recover | pass |
| Replay | Live10 truncation → recovery → complete artifact | pass |
| Replay | always truncated → fail, source never written | pass |
| Replay | recovery with invalid Python → no mutation | pass |
| Replay | recovery with malformed fence → no mutation | pass |
| Replay | recovery with missing usage → uncertain, not free | pass |
| Budget | acceptance guard at zero remaining blocks recovery | pass |
| Budget | cancellation stops before recovery | pass |
| Budget | recovery can be disabled with env `0` | pass |

The replay test also asserts:

- exact prompt SHA-256 `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8`;
- 3 physical invocations (source, recovery, tests), 3 distinct reservation ids;
- all 3 ledger records settled; totals reconcile with the governor;
- exactly 1 `operation_type="recovery"` record;
- `GENERATION_RECOVERIES` journal event present;
- 10/10 in-turn tests, 0 failed;
- cross-file validation `ok`;
- acceptance harness independent smoke **9/9**;
- only `src/duration.py` and `tests/test_duration.py` changed.

---

## 2. Broader regression battery (historical P0.6.9 command)

Command (same suites as `diagnostics/p0_6_9/OFFLINE_QUALIFICATION.md`, plus the
new suite):

```powershell
.\.venv\Scripts\python.exe -m pytest `
  src/tests/test_p0_6_9_universal_finops.py `
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
  src/tests/test_live_revision_and_bridge_contract.py `
  src/tests/test_generation_boundary.py -q
```

Result:

```text
324 passed in 524.59s (0:08:44)
```

= 309 historical tests + 15 new generation-boundary tests. Zero failed, zero
skipped.

---

## 3. Compile / import checks

```text
compileall on model_adapter.py, orchestrator.py, models.py,
test_generation_boundary.py: rc 0
import smoke of model_adapter, orchestrator, models: OK
DeliveryContract.generation_recoveries field present: True
```

---

## 4. Invariant 7

```python
check_invariant7(".")
# maintained=True
# changed_files=[], drift_files=[], undeclared_changes=[]
```

No file under `desktop/vscode` was touched.

---

## 5. Secret scan

`scripts/secret_scan_p0_6_6.py` over the four changed/new source and test files:

```text
SECRET SCAN: 1 potential hit(s)
  src/orchestration/orchestrator.py:662:
  secret_assignment: token = self.supervision_gate.grant_approval(...)
```

Reviewed **false positive**: an in-memory approval token variable that already
existed at baseline. `git diff` confirms the line is not part of this repair.
Zero real secrets.

---

## 6. Evidence checksums

`diagnostics/p0_6_9/SHA256SUMS.txt` re-verified against the working tree:

```text
checksums: 41 ok, 0 mismatched, 0 missing, total 41
```

This includes the 24 `live9` entries and the `live10` entries. No historical
file was modified.

---

## 7. Whitespace / diff hygiene

```text
git diff --check -- src/orchestration/model_adapter.py \
                    src/orchestration/orchestrator.py \
                    src/orchestration/models.py \
                    src/tests/test_generation_boundary.py
# clean
```

`git diff --check` over the whole tree reports 30 pre-existing "new blank line at
EOF" items in unrelated modified files under `apps/personal_finance/` and other
carried-over working-tree changes that are **not part of this task** and are not
committed by it.

---

## 8. Test isolation

- `ModelExecutionAdapter` is exercised with `ma.get_llm` patched to deterministic
  fakes for the lifetime of each test.
- No environment credential is read by the tests beyond the normal settings
  import.
- The historical replay runs in a temporary git workspace.
- No title/auxiliary provider path is invoked.
- The acceptance guard is exercised in-process only.

---

## 9. Classification

| Result | Classification |
| --- | --- |
| 15/15 generation-boundary tests | offline tested |
| 324/324 combined regression | offline tested |
| Live10 → recovery replay | simulated |
| 10/10 historical workload tests in replay | simulated |
| 9/9 independent smoke in replay | simulated |
| Live-model recovery effectiveness | **not proven** |
| P0.6.9 live acceptance | **unchanged, not accepted** |
