# Phase 1.4 - Windows Runtime Security Qualification

**Scope:** actual Windows runtime behavior of the Crusor sandbox, read-only
machine ACL inspection, Python 3.11/3.14 compatibility, and one confirmed
runtime defect fix.

**Final verdict:** **WINDOWS SECURITY QUALIFIED** (see sections 15-16; the
interim PARTIAL findings are retained below as historical evidence).

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

## 13. Interim verdict (superseded by sections 15-16)

**PARTIAL at the time of the first runtime pass.**

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

At the time of the output-bound correction, Phase 1.4 remained PARTIAL. The
ACL architecture and network proof in sections 15-16 supersede that interim
verdict; this correction closed the output-bound and test-integrity findings
(C1-C8).

## 15. Final closure decisions and evidence

### A. WindowStation/Desktop ACL architecture

**Decision:** remove the automatic ACL grant from production initialization.
`initialize()` no longer calls `_ensure_windowstation_desktop_access()`.

- The AppContainer worker is exercised without changing any WindowStation or
  Desktop DACL.
- The runtime tests replace the helper with a function that raises if called;
  all AppContainer tests pass, proving the production path does not invoke it.
- On a host whose existing WindowStation/Desktop does not permit
  `ALL APPLICATION PACKAGES`, process creation fails closed with the normal
  `CreateProcessW` error. It does not rewrite machine ACLs.
- `_ensure_windowstation_desktop_access()` remains defined for audited,
  explicit operator provisioning only. It is never called automatically.

This is the verified alternative to the unsafe global permission change. The
developer's normal `WinSta0`/`Default` objects are untouched.

### B. AppContainer network isolation

A native Winsock probe (`src/tests/native/net_probe.c`) was compiled with MinGW
`gcc` and tested in two steps:

1. **Control:** a normal process connected to a disposable `127.0.0.1` TCP
   listener; the probe printed `CONNECT_OK` and the listener accepted.
2. **AppContainer:** the same probe ran inside the AppContainer with zero
   capabilities; it printed `CONNECT_TIMEOUT` after a 3-second nonblocking
   connect, and the listener had no pending connection.

The OS did **not** return a Winsock access-denied code for loopback TCP; it
silently dropped the connection. A supplemental UDP probe also returned
`UDP_SENT=1` from `sendto`, but the listener received no datagram. The denial is
therefore silent kernel-level dropping, not an application-level check.

The runtime test asserts:

- the control connection succeeded,
- the AppContainer process actually started,
- no `CONNECT_OK` came from the AppContainer,
- the result was `CONNECT_TIMEOUT` or an allowed denial code,
- the listener never became readable.

### C. Python compatibility

**Decision:** Python 3.11 remains supported (`requires-python >=3.11`).

- `src/runtime/windows_shell.py` and `src/tools/terminal_tools.py` used
  `platform.system()` at import time. Both now use `os.name == "nt"`.
- Python 3.11.9: full security suite **232 passed, 3 skipped**.
- Python 3.14.4: full security suite **232 passed, 3 skipped**.
- Full guarded import passes on both versions.

No packaging metadata change was needed.

### D. AppContainer temporary directory

**Decision:** package-local temporary storage is the intended AppContainer
contract. The package `AC\Temp` directory is isolated per AppContainer profile
and removed with the profile. Staging remains the file-delivery root; it is not
the AppContainer `TMP`.

A runtime test (`test_appcontainer_tmp_is_package_local`) asserts the child sees
`\Packages\...\AC\Temp`. The fallback backend continues to use the staging
directory. The previous assumption that `TMP` must equal staging is removed.

### E. Job Object memory accounting

- The flag is `JOB_OBJECT_LIMIT_JOB_MEMORY` (`0x200`); `JobMemoryLimit` is in
  bytes.
- Control: a 128 MB allocation succeeds under a 512 MB job limit.
- Limited: the same allocation raises `MemoryError` under a 64 MB limit.
- `PeakJobMemoryUsed` still reported ~140 MB under the 64 MB limit.

The behavioral denial is real, but the peak field does not agree with the
configured limit. The cause is not established. The limitation is retained:
**do not claim a hard 64 MB peak-memory bound**; claim only the observed
allocation denial under the configured job limit.

### Final acceptance

| Criterion | Status |
|---|---|
| 1 ACL architecture approved/safely qualified | PASS - automatic ACL change removed; fail-closed alternative verified |
| 2 AppContainer network isolation runtime evidence | PASS - control success, AppContainer timeout, no listener accept |
| 3 Every declared Python version passes guarded import | PASS - 3.11 and 3.14 |
| 4 TMP contract documented and tested | PASS - package-local AC temp |
| 5 Memory enforcement understood or bounded | PASS (bounded) - denial observed; peak accounting limitation retained |
| 6 Existing security tests passing | PASS - 232 passed, 3 skipped on 3.11 and 3.14 |
| 7 CI evidence for exact commit | PASS - security run `42654054565`, Windows runtime run `42654054623` |
| 8 Limitations disclosed | PASS |

Runtime harness: **21 passed** with AppContainer opt-in.

### CI evidence for the final closure commit

Commit `0bf14d9c7500714b5f2c4fb663a22219adff5e39`.

**Security guard** run `42654054565`, Python 3.14.10:

| Platform | Job ID | Result |
|---|---|---|
| Ubuntu | `129287687682` | 231 passed, 4 skipped in 8.17 s |
| Windows | `129287687039` | 229 passed, 6 skipped in 14.63 s |
| macOS | `129287687623` | 231 passed, 4 skipped in 8.09 s |

**Windows runtime qualification** run `42654054623`, job
`Windows sandbox runtime` `129287686824`, Python 3.14.10:

```text
collected 21 items
21 passed in 27.93s
```

This CI job ran the actual runtime harness with
`CRUSOR_RUN_APPCONTAINER_RUNTIME=1`, including the native network probe (the
GitHub Windows runner supplied `gcc`), the AppContainer token/DACL tests, Job
Object limits, output bounds, cancellation and cleanup. No runtime test was
skipped.

### Release decision

**WINDOWS SECURITY QUALIFIED** for the declared Windows 11 + Python 3.11/3.14
contract, with the documented memory-accounting limitation and the silent-drop
network behavior. This is not whole-product production readiness.

## 16. Fail-closed startup and capability-reporting correction

### Process creation is fail-closed

`_execute_appcontainer()` now checks every security-critical step:

1. `InitializeProcThreadAttributeList` sizing and initialization.
2. `UpdateProcThreadAttribute` for `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`.
3. `UpdateProcThreadAttribute` for `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`.
4. `CreateProcessW` (created suspended).
5. `AssignProcessToJobObject` before resumption.
6. `ResumeThread`, requiring previous suspend count exactly 1.

Any failure returns exit code 127 with a specific stderr reason, terminates the
suspended process, closes the pipes/read handles, deletes the attribute list and
closes the Job Object. `ResumeThread` is never called after Job assignment
fails. A failed or unexpected resume terminates the process and joins the
reader threads. Handle-close paths avoid double-closing when `terminate()` has
already closed the process handles.

### No silent security downgrade

When `use_appcontainer=True`:

- AppContainer provisioning failure raises `RuntimeError` by default.
- The Job Object-only path is available only with
  `CRUSOR_ALLOW_JOB_OBJECT_FALLBACK=1`.
- In degraded mode, `get_capabilities()` reports
  `appcontainer_isolation=false`, `kernel_network_isolation=false`,
  `kernel_filesystem_dacl_isolation=false`, `network_denial=false`,
  `low_integrity_restricted_token=false`.
- Job Object capabilities (`process_tree_termination`,
  `job_object_resource_limits`, `active_process_limit`, `memory_limit`,
  `environment_sanitization`, `filesystem_staging`) remain true.

Proxy environment variables are not reported as kernel network isolation.

### Deterministic failure-injection tests

Six new tests were added (runtime harness now 27 tests):

- Job assignment failure prevents `ResumeThread`.
- `ResumeThread` failure terminates and cleans up.
- Security-capabilities attribute failure prevents `CreateProcessW`.
- AppContainer provisioning failure fails closed by default.
- Degraded fallback is explicit opt-in and reports false AC/network/
  low-integrity capabilities.
- Capability reporting differs correctly between AppContainer and Job
  Object-only backends.

A narrow `_Kernel32Proxy` / `_UserenvProxy` test double overrides only the
specific API result; no machine ACL or destructive operation is involved.

### TMP/TEMP reconciliation

The source sets `TMP`/`TEMP` to staging for the environment block, but Windows
AppContainer overrides them with package-local `AC\Temp`. The committed runtime
test asserts the package-local contract; the fallback backend uses staging. The
source behavior is unchanged, and the previous “staging must appear” assumption
was wrong.

### Network evidence scope

The committed native test proves **TCP loopback denial**:

- control process connected successfully,
- AppContainer `connect()` timed out,
- the listener never accepted,
- denial was a silent kernel drop, not a Winsock error.

A supplemental UDP probe was run locally (`sendto` returned success, no datagram
was received) but is **not committed and not CI evidence**. This phase does not
claim UDP, DNS, or non-loopback coverage.

### Python compatibility and CI

`requires-python` remains `>=3.11`. Full guarded import and the full security
suite pass on 3.11.9 and 3.14.4. The dedicated Windows runtime workflow now uses
a Python 3.11/3.14 matrix, so both declared versions execute the runtime
harness.

### Local verification

| Check | Result |
|---|---|
| Security suite, 3.14 | 232 passed, 3 skipped |
| Security suite, 3.11 | 232 passed, 3 skipped |
| Guarded import, 3.14 / 3.11 | 1 passed each |
| Runtime harness, 3.14 | 27 passed |
| Runtime harness, 3.11 | 27 passed |
| Static security scan | 173 passed |
| Agent-core checkup | 57 pass, 5 warn, 0 fail |
| Checkup tests | 19 passed |

### CI results

Security guard run `42661726444` on `5a51897c`, Python 3.14.10:

| Platform | Job ID | Result |
|---|---|---|
| Ubuntu | `129314746085` | 231 passed, 4 skipped in 10.03 s |
| Windows | `129314746216` | 229 passed, 6 skipped in 14.79 s |
| macOS | `129314746483` | 231 passed, 4 skipped in 9.35 s |

Windows runtime qualification run `42661726660` on `5a51897c`:

| Job | Python | Job ID | Result |
|---|---|---|---|
| Windows sandbox runtime (Python 3.14) | 3.14.10 | `129314745800` | 27 passed in 24.16 s |
| Windows sandbox runtime (Python 3.11) | 3.11.9 | `129314746236` | 27 passed in 24.54 s |

No runtime test was skipped. The 3.11/3.14 matrix continuously exercises the
declared Python contract.

### Final verdict

**WINDOWS SECURITY QUALIFIED** for the declared Windows 11 + Python 3.11/3.14
contract. AppContainer startup is fail-closed, silent security downgrades are
removed, capability reporting is accurate, and the failure-injection tests pass
in CI on both Python versions.

This is not whole-product production readiness. The TCP-loopback network denial
is silent (no Winsock error), UDP/DNS/non-loopback is not claimed, and Job
Object peak-memory accounting remains a documented limitation.

### Remaining limitations

- TCP loopback denial is silent (timeout); no Winsock error code is returned.
  UDP/DNS/non-loopback isolation is not claimed.
- Job Object `PeakJobMemoryUsed` accounting still disagrees with the 64 MB
  configured limit; behavioral `MemoryError` is observed, but no hard peak
  memory bound is claimed.
- AppContainer TMP is package-local, not staging.
- This is not whole-product production readiness.
