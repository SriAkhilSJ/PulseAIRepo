# Offline Test Results — LIVE12 Preflight

All commands are provider-free. No network/provider call, no Electron acceptance
run, no benchmark. Date: 2026-11-08.

---

## 1. Live11 repair suite

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/test_live11_repair.py -q
```

```text
25 passed in 25.16s
```

Covers: one-submission-one-turn, duplicate IPC, duplicate session create,
cross-session replay, terminal finality, durable reload, concurrent claims,
new-session same-prompt rejection, existing-session repeat, reserved release,
in-flight uncertain, idempotent reconciliation, single settlement, forced
shutdown sweep, current-process sweep exclusion, invocation observability.

---

## 2. Generation boundary suite

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/test_generation_boundary.py -q
```

```text
15 passed in 36.17s
```

Includes the exact Live10 prompt replay and the finish-reason/requested-cap
assertions. Generation recovery remains unproven live.

---

## 3. Broad provider-free battery

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
  src/tests/test_live11_repair.py -q
```

```text
1 failed, 348 passed in 269.19s (0:04:29)
```

The one failure:

```text
test_bridge_transport.py::test_turn_done_survives_a_undrained_event_queue
AssertionError: 'undrained' not in
  'Agent Core evidence capture is degraded; the turn will continue, ...'
```

This is **not** counted as unrelated by assertion. The recorded baseline run
with `src/bridge/__main__.py` from `6959c862` reproduces the exact failure
(`baseline_bridge_failure.log`, 1 failed in 11.43s). The file was restored and
its SHA-256 verified. The failure is pre-existing evidence-capture ordering in
this large dirty checkout.

---

## 4. Desktop compilation

### Full build

```powershell
cd desktop\vscode
npm run compile
```

Result: **failed** after ~12 minutes. Pre-existing missing type packages:

```text
TS7016: Could not find a declaration file for module 'electron'
TS2503: Cannot find namespace 'Electron'
TS2503: Cannot find namespace 'DebugProtocol'
TS2304: Cannot find name 'TrustedHTML'
```

See `desktop_full_compile.log`.

### Targeted CrusorAI project check

```powershell
node node_modules/typescript/bin/tsc6 -p src/tsconfig.crusorai-check.json
```

Exits 2 on upstream type dependencies; **zero errors in `contrib/crusorai`
files** (see `desktop_crusorai_check.log`).

### Runtime artifact

- `desktop/vscode/.build/electron/CrusorAI.exe` present (221,944,832 bytes).
- `out/.../crusorAIRendererService.js` contains the submission fix.
- `node --check` on that file: exit 0.

The existing runtime artifact is ready to execute; a clean desktop rebuild is
**not verified** in this environment.

---

## 5. Integrity / hygiene

| Check | Result |
| --- | --- |
| Historical P0.6.9 checksums | **41/41** |
| Live11 run manifest | **48/48** |
| Live11 repair manifest | **19/19** |
| `git diff --check` on changed files | clean |
| Secret scan of changed files | clean except the pre-existing contextvar `token` false positive in `invocation_context.py` |
| Provider calls | **0** |
| Provider spend | **₹0.00** |
| Electron acceptance runs | **0** |
