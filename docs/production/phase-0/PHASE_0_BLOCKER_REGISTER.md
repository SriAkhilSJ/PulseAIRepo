# Phase 0 — Blocker Register

**Phase 0 does not fix anything.** This register is the ordered list of what
must be fixed before production use, with evidence and the regression tests that
must exist. IDs are stable for later phases.

Legend: **P0** stop-ship; **P1** must fix before live/external use; **P2**
engineering debt.

---

## P0 — stop-ship

### BLK-01 — Import-time WindowStation/Desktop ACL weakening

| Field | Value |
|---|---|
| Severity | **P0** |
| Evidence | `src/context/vector_memory.py:14-36`; `scripts/repair_winsta.py:22-71`; `trigger_debug.log` (314 calls); `repair_exec.log` (626 successes, `SetSecurityInfo = 0`) |
| Classification | **PROVEN** |
| Impact | Grants Everyone (`WD`) generic-all on the interactive WindowStation/desktop on every import; local boundary broken |
| Fix | Remove the import-time call and the scripts; restore default ACLs; if a service fix is truly needed, admin-only CLI with a narrow ACL |
| Regression | Import purity test; static `WD`/`GA`/`SetSecurityInfo` guard; Windows DACL assertion |

### BLK-02 — Import-time `runner.exe` launch capability

| Field | Value |
|---|---|
| Severity | **P0** |
| Evidence | `src/context/context_engine.py:21-62` (binary at `:55`); `runner.exe` SHA-256 `9D1BAAC1…36D7`, 296,600 bytes |
| Classification | **PROVEN execution of the function; UNPROVEN binary launch** (fails earlier on `win32security.GetProcessWindowStation`; `win32api` not imported) |
| Impact | Latent arbitrary executable launch on import with an unknown binary |
| Fix | Delete `_diag_pid` and the binary; no absolute paths outside the repo |
| Regression | Import purity; static scan for `runner.exe` and absolute `C:\Users` paths |

### BLK-03 — Hot-path ACL attempt in `sanitize_memory_context`

| Field | Value |
|---|---|
| Severity | **P0** |
| Evidence | `src/context/engine.py:27-68`; `diag_pid.log` has 38 `sanitize_memory_context error` entries |
| Classification | **PARTIALLY PROVEN** (function runs; ACL call fails on this pywin32) |
| Impact | Per-turn file writes and Windows security calls; latent ACL weakening |
| Fix | Remove the win32 block; make the function pure |
| Regression | Purity test; no file/win32 calls |

### BLK-04 — Committed repair scripts with Everyone/GA

| Field | Value |
|---|---|
| Severity | **P0** |
| Evidence | `scripts/repair_winsta.ps1:50-76`; `scripts/repair_winsta.py:22-71` |
| Classification | **PROVEN** |
| Impact | Same as BLK-01; the Python script is the one that succeeded |
| Fix | Remove from runtime/repo; restore ACLs |
| Regression | Static guard; Windows DACL assertion |

### BLK-05 — Unknown `runner.exe` provenance

| Field | Value |
|---|---|
| Severity | **P0 capability** |
| Evidence | `C:\Users\Administrator\Downloads\CRUSORAI\runner.exe` (outside repo) |
| Classification | **UNPROVEN** (not executed in observed logs) |
| Impact | Supply-chain / arbitrary code risk |
| Fix | Delete; if legitimate, bring into repo, pin hash, document, require explicit user action |
| Regression | No out-of-repo executable references |

### BLK-06 — Desktop launch is not hermetic

| Field | Value |
|---|---|
| Severity | **P0** |
| Evidence | `diagnostics/live12_run_20261108_085953/evidence.json` (`P0.6.6_LIVE_FAILED`); `logs/electron.stderr.log` (policy-watcher bindings); `NATIVE_MODULE_REPAIR.md` |
| Classification | **FAILED** (first launch); repair **PARTIALLY PROVEN** (modules load under Node, not under a workbench launch) |
| Impact | The qualified executable could not start after `npm ci --ignore-scripts`; a compile+hash gate did not catch it |
| Fix | Hermetic dependency restore with native builds (`npm ci` under a supported toolchain) or check in approved prebuilds; add build→launch→ready smoke |
| Regression | CI/Windows: launch to ready workbench; assert every required `.node` loads; fail on missing bindings |

### BLK-07 — No completed live acceptance

| Field | Value |
|---|---|
| Severity | **P0** |
| Evidence | P0.6.9 `ACCEPTANCE_FAILED`; Live11 duplicate + uncertain hold; LIVE12 attempt 1 launch failure |
| Classification | **FAILED / UNPROVEN** |
| Impact | Exactly-once, financial lifecycle and visual rendering are not proven in the real desktop |
| Fix | After BLK-01..06, run one authorized LIVE12 session and audit it |
| Regression | One session, one submission, one turn, all calls settled, zero title calls |

### BLK-08 — Acceptance harness is task-specific

| Field | Value |
|---|---|
| Severity | **P0** (for any non-duration benchmark) |
| Evidence | `benchmarks/crusor_desktop_acceptance/live_acceptance.py:562-563` (`duration.py`, `test_duration.py`); `:668` (`work_units == 2`) |
| Classification | **PROVEN** |
| Impact | A correct app of any other shape is marked failed; the harness cannot judge ProjectFlow or a general task |
| Fix | Add a task profile with declarative artifacts, commands and success criteria; keep the duration profile as one instance |
| Regression | Harness test with a non-duration task profile; correct pass and correct fail |

---

## P1 — must fix before live/external use

### BLK-09 — Multiple money sources of truth

| Field | Value |
|---|---|
| Severity | **P1** |
| Evidence | canonical `financial_reservations`; `provider_invocations.jsonl`; `*_finops.json`; workspace aggregate |
| Classification | **PROVEN** (design) |
| Impact | Drift between settlement, task aggregate and invocation ledger |
| Fix | One authoritative store with derived views; migration plan |
| Regression | Invariant: guard claims == invocations == settlements == aggregate |

### BLK-10 — Time-heuristic reconciliation

| Field | Value |
|---|---|
| Severity | **P1** |
| Evidence | `src/finops/recovery.py:28-92` (`_PROCESS_START`, `force=True`); `finops_governor.py:776` |
| Classification | **PROVEN** |
| Impact | Multi-process or clock-skew cases can reconcile the wrong hold |
| Fix | Lease/fencing token per reservation; owner PID + start time; no timestamp-only ownership |
| Regression | Two-process simulation with overlapping reservations |

### BLK-11 — Visual tool-card rendering unproven

| Field | Value |
|---|---|
| Severity | **P1** |
| Evidence | Live11 screenshots (5) show no tool card; LIVE12 sampler not run |
| Classification | **UNPROVEN** |
| Impact | Backend tool events may not be visible to the user |
| Fix | Run the repaired LIVE12 and require `tool_rows > 0` + screenshot + trace agreement |
| Regression | Mid-turn DOM/screenshot test in a real session |

### BLK-12 — Token economics and 24 h stamina unknown

| Field | Value |
|---|---|
| Severity | **P1** |
| Evidence | `AGENT_CORE_FULL_AUDIT_2026-11-01.md` (716k/925k-token turns); no soak |
| Classification | **UNKNOWN** |
| Impact | ₹50 can be consumed quickly; long-run behavior unproven |
| Fix | Bounded per-turn budgets, compaction metrics, 24 h soak with cost/token trace |
| Regression | Soak: token/cost ceiling, no duplicate submission, no unaccounted call |

### BLK-13 — Test slice is not the full suite

| Field | Value |
|---|---|
| Severity | **P1** |
| Evidence | 366 selected tests; historical full suite had 67 failures (`AGENT_CORE_FULL_AUDIT_2026-11-01.md`) |
| Classification | **PARTIALLY PROVEN** |
| Impact | Unrelated regressions can hide outside the slice |
| Fix | Restore the full suite to green or document a quarantined set |
| Regression | Full-suite CI with an explicit quarantine list |

### BLK-14 — Monolithic runtime files

| Field | Value |
|---|---|
| Severity | **P1** (maintainability) |
| Evidence | `src/bridge/__main__.py` ~166 KB; `model_adapter.py` ~66 KB; `finops_governor.py` ~44 KB |
| Classification | **PROVEN** |
| Impact | Review, test isolation and safe change are harder |
| Fix | Extract session/submission guard, turn runner and reconciliation into modules with tests |
| Regression | No behavior change; existing contract tests |

### BLK-15 — Readiness docs overstated

| Field | Value |
|---|---|
| Severity | **P1** (process) |
| Evidence | `ACCEPTANCE_MATRIX.md` originally said `LIVE12_READY_FOR_EXPLICIT_AUTHORIZATION` without a launch smoke test |
| Classification | **PROVEN** |
| Impact | A green offline report hid a non-starting app |
| Fix | Readiness gate must include a launch-to-ready workbench and import purity |
| Regression | Readiness script fails if launch/import smoke fails |

---

## P2 — engineering debt

| ID | Item | Evidence |
|---|---|---|
| BLK-16 | Protocol schema is not validated at runtime on both ends | `protocol_v2.json` + generator; tests only |
| BLK-17 | `load_dotenv()` at import | `src/context/engine.py:13-17` |
| BLK-18 | Hardcoded developer paths | `context_engine.py:22,55`; `vector_memory.py:15,19,28`; `engine.py:28` |
| BLK-19 | Unbounded subprocess calls (no timeout) | `vector_memory.py:20,29` |
| BLK-20 | Logs written outside repo without rotation | `diag_pid.log`, `trigger_debug.log`, `repair_*.log` |

---

## Go / No-Go

```text
PHASE_0_GO_NO_GO: NO-GO
```

Order of work:

1. **BLK-01..05** — remove the import-time Windows payloads and restore ACLs.
2. **BLK-06** — hermetic build + launch-to-ready smoke.
3. **BLK-08** — generic acceptance profile.
4. **BLK-07** — one authorized LIVE12 session.
5. **BLK-09..10** — single money store + fencing.
6. **BLK-11..12** — visual proof + 24 h soak.
7. **BLK-13..15** — full suite, decomposition, honest readiness gates.

No item above was implemented in Phase 0.
