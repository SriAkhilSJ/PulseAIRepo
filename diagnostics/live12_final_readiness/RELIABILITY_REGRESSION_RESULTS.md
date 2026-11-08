# Reliability Regression Results

All runs are provider-free. Date: 2026-11-08.

## 1. Full provider-free battery

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
  src/tests/test_generation_boundary.py `
  src/tests/test_live11_repair.py `
  src/tests/test_live12_readiness.py -q
```

```text
366 collected, 366 passed in 678.32s (0:11:18)
```

Zero failures, zero errors, zero skipped. `reliability_battery.log` is the raw
output.

## 2. Targeted suites

| Suite | Result |
|---|---|
| `test_live12_readiness.py` | 17 passed |
| `test_p0_6_5_live_acceptance.py::TestVerdictGates` | 9 passed |
| `test_bridge_transport.py::test_turn_done_survives_a_undrained_event_queue` | 1 passed (17.78 s) |
| `test_generation_boundary.py` | 15 passed (36.17 s) |
| `test_live11_repair.py` | 25 passed |
| `test_p0_6_9_universal_finops.py` | 15 passed |
| `test_bridge_workspace_routing.py` | 12 passed (222.95 s standalone) |

## 3. Bridge transport resolution

The known failure was a test-selection defect: a legitimate evidence-degradation
`runtime_degraded` frame precedes the strand frame in this dirty checkout. The
baseline bridge file (`6959c862`) reproduces the same failure
(`baseline_bridge_failure.log`). The test now selects the strand frame by its
`undrained` reason; assertions are unchanged. It passes isolated and in the full
suite.

## 4. Desktop compile

See `DESKTOP_BUILD_REPORT.md`:

```text
tsc finished
resources copied: 731 files
Finished 'compile' after 13 min
exit 0
```

## 5. Integrity

- Historical checksums: P0.6.9 41/41; Live11 run 48/48; Live12 preflight 14/14.
  The Live11 repair manifest is 16/19 with three intentional source/artifact
  deltas documented in `HISTORICAL_MANIFEST_DELTAS.md`; the manifest itself was
  not rewritten.
- No provider calls and no Electron task session before the authorized attempt.
- The first authorized launch failed before the workbench on a missing native
  binding; see `LAUNCH_SMOKE_GAP.md` and
  `diagnostics/live12_run_20261108_085953/`. The compile suite does not start
  Electron, so it could not catch this.
- P2 roadmap unchanged.
