# Phase 1 — Security Containment

**Status:** source containment complete. Machine-level ACL recovery is **not**
complete and is explicitly out of scope for this source phase.

---

## 1. Baseline

| Item | Value |
|---|---|
| Repository | `SriAkhilSJ/PulseAIRepo` |
| Branch | `feat/prompt-cache-stabilization` |
| Expected start HEAD | `a6455e2576d2ee7f8bdb518b40d8289af5c62037` |
| Actual start HEAD | identical |
| Origin at start | identical |
| Pre-existing dirty entries | 175, preserved |
| Worktree isolation | not required; target files were clean |

---

## 2. Source files changed

| File | Change |
|---|---|
| `src/context/vector_memory.py` | Replaced the repair payload with the pure compatibility facade |
| `src/context/context_engine.py` | Removed `_diag_pid()`, its import-time call, the ACL code, `runner.exe`, and unused `ast`/`os`/`sys` imports |
| `src/context/engine.py` | `sanitize_memory_context()` is text-only and fail-closed; no Win32, no diagnostics file |
| `src/context/summarizer.py` | Removed import-time `_do_winsta_repair()` and the `runner.exe` call in `summarize_message` |
| `src/context/compaction.py` | Removed the `runner.exe` call from `HistoryCompactor.prune()` |
| `src/runtime/status_contract.py` | Removed import-time `_repair_desktop_permissions()` and its Win32 block |
| `scripts/agent_core_checkup.py` | Import-safety hygiene check now runs in a guarded child process |

## 3. Scripts deleted

```text
scripts/repair_winsta.py
scripts/repair_winsta.ps1
```

Both were tracked; both are removed. They were **not executed** during this
phase.

---

## 4. Repository-wide static scan

Scope: `src/`, `scripts/`, `benchmarks/`,
`desktop/vscode/src/vs/workbench/contrib/crusorai/` — 973 Python files, AST +
string matching, no application imports.

### Findings and classification

| Finding | Classification | Disposition |
|---|---|---|
| `vector_memory._trigger_repairs` + repair scripts | **Confirmed dangerous (P0)** | Removed (this phase) |
| `context_engine._diag_pid` + `runner.exe` | **Confirmed dangerous (P0)** | Removed |
| `engine.sanitize_memory_context` Win32 block | **Confirmed dangerous (P0)** | Removed |
| `summarizer._do_winsta_repair` (import-time) | **Confirmed dangerous (P0)** | Removed |
| `summarizer.summarize_message` `runner.exe` | **Confirmed dangerous (P0)** | Removed |
| `compaction.prune` `runner.exe` | **Confirmed dangerous (P0)** | Removed |
| `status_contract._repair_desktop_permissions` (import-time) | **Confirmed dangerous (P0)** | Removed |
| `src/security/sandbox/windows.py` `SetSecurityInfo` | **Benign startup behaviour** | Retained: narrow `ALL APPLICATION PACKAGES` grant required for AppContainer; no `Everyone`/`WD`, no import-time call |
| `scripts/run_phase_9_4_3_least_privilege_suite.py` WindowStation reads | **Suspicious but unproven** | Audit script; reads handles, does not mutate; not runtime |
| 11 hardcoded `C:\Users\Administrator\...` paths in standalone `scripts/` | **Suspicious (P1)** | Reported, not fixed; not import-time runtime payloads |
| `os.system` occurrences in tests | **Test-only** | Not runtime |

After cleanup, a focused grep of runtime `src/` (excluding tests and the
sandbox) returns **zero** hits for:

```text
repair_winsta, _trigger_repairs, _diag_pid, runner.exe,
WD)(A;OICI;GA, -ExecutionPolicy Bypass, C:\Users\Administrator\Downloads\CRUSORAI
```

Import-time Win32 imports: **zero** (the previous
`context_engine`/`engine`/`status_contract` hits are gone).

---

## 5. Import-time side effects removed

| Before | After |
|---|---|
| `vector_memory` import → PowerShell + Python repair subprocess | pure facade import |
| `context_engine` import → ACL change + `runner.exe` attempt | pure import |
| `summarizer` import → ACL change | pure import |
| `status_contract` import → ACL change | pure import |
| `engine.sanitize_memory_context` → ACL change + external log write | text-only, fail-closed |
| `compaction.prune` / `summarizer.summarize_message` → `runner.exe` | removed |

`engine.sanitize_memory_context()` now raises `RuntimeError` if the redactor is
unavailable; it never returns the original unsanitized text.

---

## 6. New regression tests

`src/tests/test_security_containment.py` (9 tests):

1. **Static guard** — scans runtime source and the checkup for the Everyone/GA
   SDDL, `SetSecurityInfo` (outside the documented sandbox allowlist),
   `repair_winsta`, `runner.exe`, `-ExecutionPolicy Bypass`, `_trigger_repairs`,
   `_diag_pid`, old developer paths and import-time `win32security`.
2. **Deleted scripts** — asserts both repair scripts are absent.
3. **Import purity** — imports `src.context.vector_memory` and
   `src.context.context_engine` in a fresh guarded process; blocks
   `subprocess.run/Popen`, `os.system`, `os.popen`, Win32-security imports and
   external writes; asserts zero violations.
4. **Sanitization** — secret redaction, URL-credential redaction, truncation,
   fail-closed redactor failure, no Win32 calls.
5. **Checkup safety** — the guarded probe catches a deliberately bad
   subprocess package, a `win32security` import package, and an external-write
   package. No real repair script is used as a fixture.

The checkup's `check_hygiene()` now calls
`run_guarded_import_probe()`, which spawns a child process with the guards
installed before any repository import. Violations are `FAIL`; import errors are
`WARN` with the module named.

---

## 7. Test commands and actual results

| Command | Result |
|---|---|
| AST parse of the 8 changed Python files | **OK** |
| `pytest src/tests/test_security_containment.py -q` | **9 passed** in 4.61 s |
| `pytest src/tests/test_agent_core_checkup.py src/tests/test_compaction.py src/tests/test_context_budget.py src/tests/test_p0_6_9_universal_finops.py src/tests/test_live11_repair.py -q` | **117 collected: 115 passed, 2 failed**, 1 warning, 386.92 s |
| `pytest src/tests/test_context_engine_parity.py src/tests/test_memory_package.py src/tests/test_vector_memory.py src/tests/test_status_contract.py src/tests/test_live12_readiness.py -q` | **48 collected: 46 passed, 2 failed** |

### The two failures are pre-existing, not Phase 1 regressions

```text
ImportError: cannot import name 'compact_assistant_tool_call_arguments'
  at src/context/history_shaper.py:159
```

`git show HEAD:src/context/compaction.py` does **not** define that symbol, and
`history_shaper.py` at HEAD already imports and calls it. The Phase 1 diff to
`compaction.py` only removes the five-line `runner.exe` block. This is a
baseline defect recorded for a later phase, not caused by the security cleanup.

## 8. Tests intentionally not run

```text
full pytest suite
standalone python scripts/agent_core_checkup.py
CrusorAI.exe / Electron / CDP
npm install / npm ci / npm run compile
provider calls or reservations
database writes or migrations
ACL restoration or permission changes
```

The full suite was not run because the baseline is known to contain unrelated
failures and this phase is scoped to security containment. The standalone
checkup was not run; its probes were exercised through the targeted pytest
suite instead.

---

## 9. External `runner.exe`

| Field | Value |
|---|---|
| Path | `C:\Users\Administrator\Downloads\CRUSORAI\runner.exe` |
| Size | 296,600 bytes |
| SHA-256 | `9D1BAAC106BBBE26AB85365C591A6C4CF6CF688FB034EEC3BC39B8EAD11636D7` |
| Executed in this phase | **NO** |
| Deleted in this phase | **NO** |
| Disposition | external artifact requiring separate review/removal by the owner |

The source references that could launch it are removed.

## 10. Machine-level ACL recovery

```text
STATUS: NOT PERFORMED
```

Source cleanup does **not** restore the WindowStation/Default Desktop ACLs.
Prior evidence (`repair_exec.log`) proves the Python repair path applied the
Everyone/GA DACL (`SetSecurityInfo = 0`, 626 success lines). Restoring the OS
default SDDL is a separate administrative action that must be performed
deliberately and verified. No default SDDL was guessed and no ACL was modified
in this phase.

The external diagnostic logs under
`C:\Users\Administrator\Downloads\CRUSORAI\` remain on disk; they are evidence,
not source.

---

## 11. Remaining blockers

1. Machine-level WindowStation/Desktop ACL restoration is unresolved.
2. `runner.exe` remains on disk (not executed, not deleted).
3. Pre-existing `compact_assistant_tool_call_arguments` import failure.
4. Pre-existing 11 hardcoded developer paths in standalone `scripts/`.
5. No full-suite run in this phase.
6. No Electron launch / live acceptance was performed.

```text
PHASE_1_SOURCE_CONTAINMENT: COMPLETE
PHASE_1_HOST_SECURITY: NOT CLAIMED
```
