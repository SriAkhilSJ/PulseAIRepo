# Phase 1.4 - Windows Runtime Security Qualification

**Scope:** actual Windows runtime behavior of the Crusor sandbox, read-only
machine ACL inspection, Python 3.11/3.14 compatibility, and one confirmed
runtime defect fix.

**Final verdict:** **PARTIAL**

A static AST pass is not a runtime pass. This phase does not certify the whole
Crusor product as production-ready.

---

## 1. Baseline and host

| Item | Value |
|---|---|
| Repository | `SriAkhilSJ/PulseAIRepo` |
| Branch | `feat/prompt-cache-stabilization` |
| Starting HEAD | `831e608532fc8c269daf1eed97e9084416511ca3` |
| Remote HEAD at start | identical |
| OS | Microsoft Windows 11 Pro, version 10.0.26200, build 26200, 64-bit |
| Session | 2 (RDP/interactive) |
| Local Python | 3.14.4 (`PulseAIRepo/.venv`) |
| Python 3.11 | 3.11.9 (`%TEMP%\opencode\venv311_ci`) |
| Token | `desktop-1ulgf16\administrator`, medium integrity, UAC-filtered |
| Privileges | No `SeTcbPrivilege` |
| Pre-existing dirty entries | 175 preserved (34 tracked + 141 untracked) |

The security suite and Python 3.11 compatibility were run in disposable venvs;
the developer's interpreter was not changed.

## 2. Machine ACL investigation (read-only)

Method: `GetProcessWindowStation`, `GetThreadDesktop`,
`GetUserObjectInformationW(UOI_NAME)`, `GetSecurityInfo` with
`SE_WINDOW_OBJECT`, and
`ConvertSecurityDescriptorToStringSecurityDescriptorW`. No
`SetSecurityInfo`, `icacls`, `takeown`, repair script, or ACL write was used.

### WindowStation `WinSta0`

```text
Owner: BA (BUILTIN\Administrators)
Group: SY (NT AUTHORITY\SYSTEM)
DACL:
  (A;OICI;0xf037f;;;WD)   Everyone              full WindowStation rights
  (A;OICI;0xf037f;;;SY)   SYSTEM                full WindowStation rights
  (A;OICI;0xf037f;;;BA)   Administrators        full WindowStation rights
  (A;OICI;0xf037f;;;IU)   Interactive Users     full WindowStation rights
```

### Desktop `Default`

```text
Owner: BA (BUILTIN\Administrators)
Group: SY (NT AUTHORITY\SYSTEM)
DACL:
  (A;OICI;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;WD)   Everyone          full desktop rights
  (A;OICI;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;SY)   SYSTEM            full desktop rights
  (A;OICI;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)   Administrators    full desktop rights
  (A;OICI;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;IU)   Interactive Users full desktop rights
```

### Findings

- The observed DACL is the standard broad Windows 11 default: Everyone and
  Interactive Users have full WindowStation/Desktop rights.
- **ALL APPLICATION PACKAGES (`S-1-15-2-1`, SDDL `AC`) is absent** from both
  objects.
- The production `_ensure_windowstation_desktop_access()` helper would add
  ALL APPLICATION PACKAGES to both objects. That is a machine-level ACL
  modification and was **not executed** on the developer's normal desktop.
- No repair or rollback was attempted. If an ACL change is ever required, the
  precise proposal is to add a narrowly scoped `ALL APPLICATION PACKAGES` ACE to
  the specific WindowStation/Desktop used by the sandbox, with a documented
  rollback; that proposal was not applied.

## 3. Environment safety assessment

The production AppContainer initialization calls
`_ensure_windowstation_desktop_access()`, which writes DACLs on the current
WindowStation and Desktop. Running it on the normal desktop would violate the
phase's no-machine-ACL-modification rule.

Attempted isolation: create a disposable WindowStation and Desktop in a child
process. `CreateWindowStationW` failed with **WinError 5 (access denied)**. The
token has no `SeTcbPrivilege`, so the disposable-object route is unavailable.
No ACL was changed by this attempt.

Therefore AppContainer runtime tests were run with the ACL helper
**monkeypatched to a no-op** in the child process. This is explicit
instrumentation, not a production run of that helper. The AppContainer token,
process creation, Job membership, and DACL enforcement remain genuine.

## 4. Runtime tests executed

New harness: `src/tests/test_windows_sandbox_runtime.py` (Windows-only;
AppContainer tests opt-in via `CRUSOR_RUN_APPCONTAINER_RUNTIME=1`).

### AppContainer

| Check | Result | Evidence |
|---|---|---|
| Profile creation + SID | PASS | backend `windows_appcontainer_job_object`; SID `S-1-15-2-...` |
| Process launch | PASS | `cmd.exe /c echo` returned `APPCONTAINER_RUNTIME_OK` |
| Token is AppContainer | PASS | parent-inspected token: `TokenIsAppContainer = True` |
| Integrity level | PASS | `S-1-16-4096` (Low Mandatory Level) |
| Administrators deny-only | PASS | group `S-1-5-32-544`, attributes `0x10` |
| Job membership | PASS | `IsProcessInJob` returned true |
| Timeout termination | PASS | execute returned `exit_code=124`, `timed_out=True`, job handle closed |
| DACL read denial | PASS | disposable denied dir: `type secret.txt` → `Access is denied`, secret absent |
| DACL write denial | PASS | disposable denied dir: `echo POISON > poison.txt` → `Access is denied`, target absent |
| `whoami /groups` inside AC | NOT RUN / FAILED TO START | `0xC0000142` when ACL helper skipped |
| PowerShell inside AC | NOT RUN / FAILED TO START | `0xC0000142` when ACL helper skipped |
| Network denial | **NOT RUN** | could not start a network-capable AppContainer binary; no conclusion |
| Production ACL-grant branch | **NOT RUN / BLOCKED** | disposable WindowStation creation denied (WinError 5, no SeTcbPrivilege) |

The `whoami`/PowerShell failures are consistent with the ACL helper being
required for some Win32 binaries to initialize. They are not evidence that the
ACL helper is safe or that it was validated; that branch remains unexecuted.

### Job Object (AppContainer disabled)

| Check | Result | Evidence |
|---|---|---|
| Limits configured | PASS | flags `8712`; active process limit, job memory, kill-on-close; CPU flags `5`, rate `8000` |
| Active process limit 1 | PASS | grandchild denied `OSError [WinError 1816]` with the real base interpreter |
| Job memory limit 64 MB | PASS | 128 MB allocation raised `MemoryError` |
| Memory accounting | CAVEAT | `PeakJobMemoryUsed` reported ~140 MB under a 64 MB limit; hard-cap accounting needs review |
| Environment sanitization | PASS | `OPENAI_API_KEY`/`AWS_SECRET_ACCESS_KEY` absent; `CRUSOR_SANDBOX=1` |
| Staging TMP (fallback) | PASS | child observed `TMP`/`TEMP` under the staging directory |
| Workspace traversal preflight | PASS | exit 126, `WORKSPACE_TRAVERSAL`, command did not run |
| Credential path preflight | PASS | exit 126, `CREDENTIAL_ACCESS_ATTEMPT` |
| Output cap | **DEFECT FIXED** | before: a single 2 MB line yielded `stdout_bytes=2000000`; after: `1048576` with truncation marker |
| Process termination | PASS | sleeper exited, Job handle closed, `poll()` non-null |
| Cleanup | PASS | `CLEANUP_SUCCESS`, staging removed |

### Confirmed defect and fix

`_execute_job_object_fallback()`'s line reader appended a whole line even when
it exceeded the 1 MB per-stream cap. A single 2 MB line bypassed the cap. The
minimal fix caps each line at the remaining budget and drains the rest. A
Windows-only regression test asserts `stdout_bytes <= 1 MB` and the truncation
marker. No other production behavior changed.

### AppContainer environment caveat

With the ACL helper skipped, the AppContainer child observed `TMP` under its
package profile (`...\Packages\crusor.sandbox.*\AC\Temp`), not the staging
directory set in the environment block. Secrets were still absent. The staging
TMP contract is therefore not observed for AppContainer; the package-local
temp is still isolated. Recorded as a contract mismatch, not a security
weakening.

## 5. Python compatibility

| Python | Security suite | Full guarded import | Notes |
|---|---|---|---|
| 3.14.4 | 232 passed, 3 skipped | 1 passed | Local venv |
| 3.11.9 | 231 passed, 3 skipped (full import excluded) | **1 failed** | 4 `subprocess.check_output` violations from `platform.system()` → `cmd /c ver` on Windows CPython 3.11 |

Python 3.11 security coverage is therefore **partial**: all tests except the
full guarded-import surface pass. The known `platform.system()` import-time
spawn remains unresolved in `src/runtime/windows_shell.py`; this phase did not
change it. Python 3.14 is the CI baseline.

## 6. Commands and exit codes

Environment: Windows 11 build 26200; local Python 3.14.4; Python 3.11.9 venv.

| Command | Result | Exit |
|---|---|---|
| `python -m pytest src/tests/test_security_containment.py -q` | 232 passed, 3 skipped in 80.07 s | 0 |
| `python -m pytest src/tests/test_security_containment.py -q -k "static or sandbox or scripts_have or known_p1"` | 173 passed in 18.57 s | 0 |
| `python -m pytest ...::test_full_guarded_import_surface -q` | 1 passed in 22.94 s | 0 |
| `python scripts/agent_core_checkup.py` | 57 pass, 5 warn, 0 fail | 0 |
| `python -m pytest src/tests/test_agent_core_checkup.py -q` | 19 passed in 156.96 s | 0 |
| `python -m pytest src/tests/test_windows_sandbox_runtime.py -q` | 6 passed, 2 skipped (AppContainer opt-in off) | 0 |
| `CRUSOR_RUN_APPCONTAINER_RUNTIME=1 python -m pytest src/tests/test_windows_sandbox_runtime.py -q` | 8 passed in 8.74 s | 0 |
| Python 3.11 containment (excluding full import) | 231 passed, 3 skipped in 40.82 s | 0 |
| Python 3.11 full guarded import | 1 failed in 11.02 s | 1 |

## 7. CI results

Workflow `Security guard`, commit
`838857eeaa09288a51c37b846ffd4f76a303332a`, run `42618095589`, **success**:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129162931614` | 231 passed, 4 skipped in 12.59 s |
| Security containment (windows-latest) | Windows | `129162931217` | 229 passed, 6 skipped in 13.79 s |
| Security containment (macos-latest) | macOS | `129162931678` | 231 passed, 4 skipped in 10.37 s |

All three jobs ran Python 3.14.10. The new runtime harness is local-only and
Windows-only; it is not part of this CI job.

## 8. Acceptance criteria

| ID | Status | Evidence |
|---|---|---|
| W1 ACL state inspected and recorded | PASS | WinSta0/Default SDDL, owner, ACEs above |
| W2 No unapproved machine ACL modification | PASS | read-only probe; production helper not executed; only a disposable temp-dir deny ACE was added |
| W3 AppContainer runtime exercised safely | PASS (bounded) | profile, process, token, integrity, job membership, DACL denial; ACL-grant branch NOT RUN |
| W4 Job Object restrictions and cleanup exercised | PASS | limits, active-process denial, memory denial, termination, cleanup |
| W5 Filesystem isolation and environment restrictions | PASS (with caveat) | DACL deny read/write; secret stripping; AppContainer TMP mismatch recorded |
| W6 Python 3.11 and 3.14 recorded separately | PARTIAL | 3.14 clean; 3.11 full guarded import fails as documented |
| W7 Existing security-containment tests passing | PASS on 3.14 | 232 passed, 3 skipped |
| W8 Limitations/skips disclosed | PASS | this document |

Overall: **PARTIAL**. The runtime evidence is genuine but bounded; the
production ACL-grant branch and network isolation remain unproven, and Python
3.11's full guarded import still fails.

## 9. Production source changes

| File | Change | Rationale |
|---|---|---|
| `src/security/sandbox/windows.py` | Cap each stream line to the remaining 1 MB budget in `_execute_job_object_fallback()` | A single oversized line bypassed the stated output cap |
| `src/tests/test_windows_sandbox_runtime.py` | New Windows-only runtime harness | Reproducible regression and runtime evidence |

No AppContainer policy, ACL, provider, database, Electron, or unrelated Agent
Core change was made.

## 10. Remaining limitations

- The production WindowStation/Desktop ACL-grant helper was not executed; its
  machine-level effect is unproven. Disposable WindowStation creation is blocked
  by the missing `SeTcbPrivilege` / access denied on this host.
- Network isolation inside AppContainer was not proven because `whoami` and
  PowerShell failed to initialize under the no-ACL-helper condition.
- `whoami /groups` and PowerShell inside AppContainer fail with `0xC0000142`
  when the ACL helper is skipped; the ACL-granted production path remains
  unverified.
- AppContainer `TMP` is the package temp, not the staging directory; the
  staging-TMP contract is not observed for AppContainer.
- The 64 MB Job memory limit produced a `MemoryError`, but
  `PeakJobMemoryUsed` reported ~140 MB; hard-cap accounting needs review.
- Python 3.11 full guarded import fails on the known `platform.system()` spawn.
- Static AST validation remains static validation, not an OS sandbox.
- Machine-level WindowStation/Desktop ACL recovery remains unresolved.
- This phase does not establish whole-product production readiness.

## 11. Explicit non-actions

No machine-level ACL modification, `SetSecurityInfo` against existing objects,
`icacls`/`takeown` repair, `repair_winsta` script, `runner.exe`, Electron
launch, paid provider call, financial reservation, database write or migration
was performed. The only ACL write was a deny ACE on a disposable test directory
under `%TEMP%`, removed with the directory.

## 12. Evidence

```text
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_4_verify_20261109_042540\
  01_guarded_import_314.log
  02_checkup.log
  03_checkup_tests.log
  04_security_314.log
  05_security_311_subset.log
  06_security_311_full_import.log
  07_runtime_no_appcontainer.log
  08_runtime_with_appcontainer.log
```

ACL probe, Job Object probe, AppContainer token probe, and isolated-object
attempt were run as bounded temp scripts; their exact JSON outputs are retained
in the session evidence and summarized above.

## 13. Final verdict

**PARTIAL.**

The Windows sandbox demonstrably creates a genuine AppContainer token at low
integrity, places the process in a Job Object, enforces a disposable DACL deny,
sanitizes secrets, enforces Job process/memory limits, caps output after the
fix, and cleans up. It does not yet have proof for the machine ACL-grant branch,
AppContainer network denial, Python 3.11 full guarded import, or the AppContainer
staging-TMP contract.

## 14. Corrective follow-up - bounded output and test integrity

**Starting HEAD:** `7e0b83ff6fb4aa58f2dfef0677c6cfcc414e9128`

### Findings

1. **AppContainer output was not genuinely bounded.** The AppContainer path
   wrote stdout/stderr to temporary files, then called `read_bytes()` and
   truncated the returned string. A child could grow the temp files without a
   retention bound, and the parent could allocate the whole file in memory.
2. **Fallback output used `readline()`.** The retention cap was applied only
   after an arbitrarily large line had already been materialized in the parent.
3. **The DACL test could pass on process-start failure.** It asserted only
   "non-zero exit" for the denied operation.
4. **The process-limit test accepted any exception**, not the specific Windows
   denial.
5. **The memory test did not distinguish job-limit denial from unrelated
   failure**, and did not record peak memory.

### Corrections

`src/security/sandbox/windows.py`

- AppContainer now uses anonymous pipes created with `CreatePipe`, not temp
  files. Only the child-side write handles are inheritable; the parent read
  handles are non-inheritable.
- Two reader threads drain stdout/stderr with 64 KiB `ReadFile` chunks. They
  retain at most **1 MiB per stream**, continue draining excess, and record
  retained and total bytes separately.
- The parent decodes retained UTF-8 bytes once at the end, so chunk boundaries
  cannot split a sequence incorrectly. Truncation markers name the exact cap.
- The fallback now uses binary `Popen` pipes and fixed 64 KiB `.read()` chunks.
  It never calls `readline()` and never materializes an unbounded line.
- Both streams have independent 1 MiB retention budgets; excess is drained so
  the child cannot block on a full pipe.
- No temporary output files are created by either backend.

`src/tests/test_windows_sandbox_runtime.py`

- DACL test now proves the AppContainer child **started** (`APPCONTAINER_STARTED`
  baseline), then asserts the denied operation returned exit code 1 with
  "Access is denied" and no spawn failure. The secret is not disclosed and the
  write target is not created.
- Process-limit test asserts `OSError` with **WinError 1816** specifically.
- Memory test first proves a 128 MB allocation succeeds under a 512 MB job
  limit, then proves it raises `MemoryError` under a 64 MB limit. Configured
  limit and observed peak are recorded; no strict peak claim is made.
- Added output-bound tests for both backends: one enormous line without a
  newline, multiple lines, separate stdout/stderr overflow, UTF-8 at the cap
  boundary, and continuous output until timeout.
- Added fallback and opt-in AppContainer cancellation tests.

### Verification

| Check | Result | Exit |
|---|---|---|
| AST validation | `AST OK` | 0 |
| Full security suite | 232 passed, 3 skipped in 22.75 s | 0 |
| Full static security scan | 173 passed in 5.52 s | 0 |
| Full guarded import | 1 passed in 10.28 s | 0 |
| Agent-core checkup | 57 pass, 5 warn, 0 fail | 0 |
| Agent-core checkup tests | 19 passed in 63.25 s | 0 |
| Windows runtime harness (AppContainer opt-in) | **19 passed in 15.44 s** | 0 |
| Python 3.11 containment subset | 231 passed, 3 skipped in 13.97 s | 0 |
| Python 3.11 full guarded import | 1 failed in 2.89 s | 1 |

The 3.11 failure is the known `platform.system()` → `cmd /c ver` spawn, not a
regression in this correction.

### Acceptance criteria

| ID | Status | Evidence |
|---|---|---|
| C1 AppContainer retention bounded | PASS | 1 MiB per pipe, 64 KiB chunks |
| C2 AppContainer temp storage bounded | PASS | no temp files; pipes only |
| C3 Fallback enormous lines bounded | PASS | binary fixed-chunk reader |
| C4 Independent stream limits | PASS | separate stdout/stderr budgets |
| C5 DACL denial proof | PASS | baseline start + exit 1 + Access denied |
| C6 Process-limit denial | PASS | WinError 1816 asserted |
| C7 Memory evidence classified | PASS | 512 MB control vs 64 MB MemoryError; peak recorded |
| C8 Timeout/cancellation/cleanup | PASS | output timeout, fallback + AC cancellation, cleanup |
| C9 Security suite | PASS | 232 passed, 3 skipped |
| C10 Limitations disclosed | PASS | Phase 1.4 limitations retained below |

### CI results

Workflow `Security guard`, correction commit
`3cc8c78072cc6ee52f52d5108f80363065634e6e`, run `42646010564`, **success**:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129259325291` | 231 passed, 4 skipped in 8.19 s |
| Security containment (windows-latest) | Windows | `129259325696` | 229 passed, 6 skipped in 15.07 s |
| Security containment (macos-latest) | macOS | `129259325512` | 231 passed, 4 skipped in 8.68 s |

All three jobs ran Python 3.14.10. The runtime harness remains Windows-only and
local; it is not part of this CI job.

### Remaining Phase 1.4 limitations

- Production WindowStation/Desktop ACL-grant branch: **NOT RUN** (WinError 5,
  no `SeTcbPrivilege`; no machine ACL modified).
- AppContainer network denial: **NOT RUN** (network-capable binaries fail to
  initialize with `0xC0000142` when the ACL helper is skipped).
- AppContainer TMP is package-local, not staging; contract mismatch.
- Job memory peak accounting reported ~140 MB under a 64 MB limit; behavioral
  `MemoryError` observed, hard-cap accounting needs review.
- Python 3.11 full guarded import still fails on `platform.system()`.
- Static AST validation is not an OS sandbox.

**Phase 1.4 verdict remains PARTIAL** because the production ACL-grant branch
and AppContainer network denial remain unproven. This correction closes the
output-bound and test-integrity findings (C1-C8).
