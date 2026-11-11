# Test Results — Live11 Repair

All tests are provider-free. No network, no Electron, no paid calls.

---

## 1. New deterministic suite

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/test_live11_repair.py -q
```

Result:

```text
25 passed
```

Coverage:

### Submission lifecycle
- one `session_create` + one `prompt` starts one turn;
- duplicate prompt claim accepts exactly once;
- duplicate `session_create` returns the original session;
- cross-session replay is refused;
- terminal state is final (completed cannot become a new turn);
- durable reload keeps completed/running state;
- 8 concurrent claims accept exactly one;
- restart marks `running` as `failed` (no replay);
- legacy no-id replay is blocked only for another session / window;
- a brand-new session replaying the same prompt with a new id is blocked;
- the same prompt in an existing session is allowed as a deliberate repeat;
- distinct submissions create distinct turns.

### Financial lifecycle
- `reserved` (never dispatched) -> released;
- `in_flight` -> uncertain and the hold is retained;
- reconciliation is idempotent;
- a startup sweep skips reservations created by the current process;
- uncertain + authentic usage settles once, never double-charges;
- workspace sweep resolves the durable `in_flight` file and writes
  `lifecycle.jsonl`;
- restart reconciliation marks an abandoned submission failed;
- invocation records carry `finish_reason`, requested cap, response timestamp
  and usage-receipt presence.

### Bridge dispatch integration
The bridge tests drive the real `BridgeServer.handle()` boundary with a fake
turn starter (no provider):
- one logical submission -> one session, one turn;
- duplicate IPC delivery -> no second worker;
- duplicate `session_create` -> no second session;
- cross-session replay -> error, no dispatch;
- distinct submission -> second turn;
- no-id legacy replay for another session -> blocked.

---

## 2. Original generation-boundary suite

```text
src/tests/test_generation_boundary.py    15 passed
```

The generation recovery suite is unchanged and still passes, including the
exact Live10 prompt replay and its three-call accounting assertions.

---

## 3. Broader offline gate

The P0.6.9 historical battery plus the new suite was run. Results:

```text
348 collected: 347 passed, 1 failed in 609.49s
```

The single failure is `test_bridge_transport.py::test_turn_done_survives_a_undrained_event_queue`.
It fails because `TurnEvidenceRecorder` emits an evidence-degraded
`runtime_degraded` frame before the strand frame in this large dirty checkout;
the same failure reproduces with the **baseline** `src/bridge/__main__.py`, so it
is pre-existing and unrelated to the Live11 repair. It is reported, not hidden.

The new suite was subsequently extended with one additional startup-sweep test
and re-run standalone: **25/25 passed**. The battery above collected the 24-test
version; the added test is in the same suite and passes.

---

## 4. Desktop typecheck

`npm run compile` (gulp -> tsc) did **not** complete in this environment:

```text
TS2503: Cannot find namespace 'Electron'
TS7016: Could not find a declaration file for module 'electron'
```

These errors are in upstream/Electron-typed files and test harnesses, not in the
changed files (`crusorAIRendererService.ts`, `crusorAIProtocol.ts`). The
`node_modules/electron` type bundle is incomplete in this checkout. The changed
files produce no reported type errors. This is an environment limitation, not a
claim that the desktop compiled green.

---

## 5. Compile / import

```text
compileall on all changed Python files: OK
imports of bridge, submission ledger, recovery, governor, adapter: OK
```

---

## 6. History / hygiene

- Historical `diagnostics/p0_6_9/SHA256SUMS.txt`: **41/41 verified**.
- Live9/Live10/Live11 evidence: not modified.
- `git diff --check` on the changed files: clean.
- Secret scan: run before commit; no real secrets.

---

## 7. Classification

| Result | Classification |
| --- | --- |
| Submission idempotency | offline tested |
| Duplicate bridge dispatch prevention | offline tested |
| Orphan reservation transitions | offline tested |
| Shutdown/restart reconciliation | simulated |
| Desktop renderer compile | environment-blocked (pre-existing missing Electron typings); no errors in changed files |
| Live acceptance | **not performed** |
| Generation recovery live proof | **not performed** |
