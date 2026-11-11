# P0.6.9 — Offline Qualification

Baseline `a2e654c6` · branch `feat/prompt-cache-stabilization`.
No live provider was called in this phase.

## 1. Exact command

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
  src/tests/test_live_revision_and_bridge_contract.py -q
```

## 2. Result

**309 passed, 0 failed, 0 skipped in 257.45 s.**

| Suite | Tests | Result |
| --- | --- | --- |
| `test_p0_6_9_universal_finops.py` (new) | 15 | passed |
| `test_p0_6_8_contract_first.py` | 44 | passed |
| `test_p0_6_7_autonomous_closure.py` | 24 | passed |
| `test_p0_6_6_execution_reliability.py` | 27 | passed |
| `test_p0_6_5_live_acceptance.py` | 33 | passed |
| `test_p0_6_4_desktop_observability.py` | 31 | passed |
| `test_p0_6_4_1_acceptance_retry_clamp.py` | 11 | passed |
| `test_p0_5_1_output_integrity.py` | 11 | passed |
| `test_p0_3_orchestrator_integration.py` | 7 | passed |
| `test_planner_phatic_gate.py` | 18 | passed |
| `test_phase_9_7_enterprise_finops.py` | 20 | passed |
| `test_phase_12_1_1_identity_finops_production.py` | 5 | passed |
| bridge suites (8 files) | 63 | passed |
| **Total** | **309** | **309 passed** |

The P0.6.8 final baseline was 293; P0.6.9 adds 15 accounting tests and one net
acceptance-gate test.

## 3. Universal-accounting evidence

`TestGovernedGateway` (7):
- reserve → one invoke → authentic usage → verified cost → settle → ledger;
- priced-model guard: unknown pricing never invokes (client calls = 0) and is
  recorded `blocked`;
- post-dispatch timeout retains an `uncertain` hold and record (never free);
- client-construction failure is `released`;
- two calls produce two distinct settlements;
- zero budget refuses.

`TestAcceptanceProxyBoundary` (3):
- in acceptance, an unmanaged `RetryLLMProxy.invoke` raises
  `UnaccountedProviderCall` and the underlying client is never called;
- the same call inside `invocation_scope` executes normally;
- outside acceptance the scope requirement is a no-op.

`TestLedgerAndReconciliation` (3):
- ledger splits engineering vs session-titling cost and counts;
- aggregate FinOps sums task + auxiliary state files;
- the local title fallback is not a provider call.

`TestBridgeTitlingWiring` + `TestTitlingAccounting`:
- the bridge titler goes through the governed gateway, sets a title, emits
  `session_info`, and records a settled `session_titling` invocation with the
  session/run/turn ids.

P0.6.4.1 retry-clamp tests now run inside a reservation scope, proving the
transport clamp still works for a reserved caller.

## 4. Session titling

- Automatic titling is **enabled** for acceptance (the P0.6.8 suppression was
  removed).
- The call is routed through `GovernedProviderGateway` with a session-scoped
  governor, `max_attempts=1`, verified pricing and a 64-token output ceiling.
- It runs synchronously before `turn_done` during acceptance so the reservation
  and settlement exist before evidence capture and app shutdown.
- If accounting refuses, no provider call occurs; an explicit local fallback is
  used. If the provider call executed but returned no usable text, a local title
  is used while the settled invocation remains in the ledger.

## 5. FinOps invariants preserved

- Task reserve/settle path unchanged in behaviour, now with a ledger record and
  an invocation scope.
- Duplicate commit is idempotent (P0.6.6 tests).
- Pre-dispatch refusal releases; post-dispatch ambiguity retains uncertain.
- Unknown pricing and unenforceable ceilings prevent dispatch.
- No retries: task and auxiliary clients are pinned to one attempt; acceptance
  clamps every proxy.
- SQLite and JSON remain authoritative; the ledger references their ids.

## 6. Changed files

New: `src/finops/invocation_context.py`, `src/finops/governed.py`,
`src/tests/test_p0_6_9_universal_finops.py`, `diagnostics/p0_6_9/`.

Modified: `src/orchestration/model_adapter.py`, `src/llm/factory.py`,
`src/bridge/__main__.py`, `benchmarks/crusor_desktop_acceptance/live_acceptance.py`,
`live_turn.py`, `__main__.py`; `src/tests/test_p0_6_5_live_acceptance.py`,
`test_p0_6_4_1_acceptance_retry_clamp.py`,
`test_p0_6_8_contract_first.py`.

## 7. Invariant 7

`check_invariant7('.')`: **maintained** — 0 changed files in `desktop/vscode`,
0 drift, 0 undeclared changes.

## 8. Secret scan

`scripts/secret_scan_p0_6_6.py` over every changed source/test/harness file:
**0 real hits**. One reviewed false positive remains the in-memory approval
token variable in `orchestrator.py`.

## 8b. Post-live ordering fix (offline only)

The one live run (`live9`) left one auxiliary reservation `in_flight`: the
bridge finalized the evidence manifest before running the governed title call,
the harness treated the manifest as turn-terminal, stopped the app, and killed
the call mid-flight. Reservation-before-dispatch was correct; settlement never
happened.

Committed after the run:

- the governed title call now runs **before** `_finalize_evidence` in the main
  turn path, so the manifest cannot declare completion before accounting;
- the harness waits up to 90 s for a terminal auxiliary invocation record
  (`wait_for_auxiliary_accounting`) **before** stopping the app;
- a test covers the wait helper.

The final offline battery is **309 passed, 0 failed**. This fix is not
live-proven: no second live run was performed.

## 9. Known limitations

1. **Legacy chat/background lanes are not governed outside acceptance.** The
   chat graph, summarizer, compaction, self-curation, planner helpers, one-shot
   runner and inline completions are inventoried; they are refused in acceptance
   without a reservation, but production use still lacks a FinOps context. See
   `INVOCATION_COVERAGE.md`.
2. **No OS-level network sandbox.**
3. **Auxiliary budget is small and separate** (`CRUSORAI_AUX_BUDGET_INR`,
   default ₹0.50) but is part of the same canonical accounting store and the
   aggregate acceptance budget.
4. **Static consistency remains shape, not semantics** (P0.6.8 carry-over).
