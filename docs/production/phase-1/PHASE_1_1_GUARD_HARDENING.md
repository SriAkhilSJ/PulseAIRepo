# Phase 1.1 — Guard Hardening

**Scope:** regression protection for the import-safety guard. No application
behaviour, database, provider or Windows ACL operation was performed.

---

## 1. Baseline

| Item | Value |
|---|---|
| Repository | `SriAkhilSJ/PulseAIRepo` |
| Branch | `feat/prompt-cache-stabilization` |
| Expected start HEAD | `7a714e2496199b4d3925003bbb0a404a1ac6e31e` |
| Actual start HEAD | identical |
| Origin at start | identical |
| Pre-existing dirty entries | 175, preserved |

## 2. Files changed

```text
scripts/agent_core_checkup.py
src/tests/test_security_containment.py
docs/production/phase-1/PHASE_1_1_GUARD_HARDENING.md
```

No product module was modified.

---

## 3. Previously uncovered bypasses

| Bypass | Old state |
|---|---|
| `subprocess.check_call` / `check_output` | not patched |
| `os.exec*`, `os.spawn*`, `os.fork`, `os.forkpty`, `os.startfile` | only some `spawn*` and `startfile` patched; `exec*`/`fork*` open |
| `asyncio.create_subprocess_exec/shell`, `pty.spawn`, `multiprocessing.Process.start` | unguarded |
| `io.open`, `os.open`, `pathlib.Path.open`, `write_text`, `write_bytes` | only `builtins.open` guarded |
| Sibling-prefix paths | naive `startswith(root)` could accept `C:\repo_evil` |
| ctypes security mutation | only `win32security` imports blocked; `ctypes.WinDLL("advapi32").SetSecurityInfo` open |
| Crashed/interrupted child | `ok = not violations` ignored return code and JSON failure |
| Static scanner | excluded the whole `src/security/sandbox/windows.py`; did not scan `scripts/` |

## 4. New guard mechanisms

### Process execution

The child process now blocks:

```text
subprocess.run / Popen / call / check_call / check_output
os.system / os.popen / os.spawn* / os.exec* / os.fork / os.forkpty / os.startfile
asyncio.create_subprocess_exec / create_subprocess_shell
pty.spawn (where available)
multiprocessing.Process.start
```

`asyncio`, `pty` and `multiprocessing` are imported **before** `subprocess` is
patched, so the guard itself does not break their import. The parent checkup
still launches the guarded child normally; only the child is patched.

### External writes

The child now wraps:

```text
builtins.open
io.open
os.open (write flags only)
pathlib.Path.open
pathlib.Path.write_text
pathlib.Path.write_bytes
```

Containment is canonical, not string-prefix:

```python
target = normcase(realpath(path))
commonpath([root, target]) == root
```

A sibling such as `C:\...\PulseAIRepo_sibling` is rejected. The probe's
`TMP`/`TEMP`/`TMPDIR` are redirected to a repository-local scratch directory so
third-party temporary files do not masquerade as escapes; the scratch directory
is removed after the probe.

### Windows security APIs

`ctypes.WinDLL`, `CDLL`, `OleDLL`, `windll`, `oledll` and `cdll` now return a
guarded proxy. Accessing any of these names records a violation and raises
before the real function is returned:

```text
SetSecurityInfo
SetNamedSecurityInfoW / SetNamedSecurityInfoA
SetKernelObjectSecurity
SetUserObjectSecurity
NtSetSecurityObject
```

Non-security DLL attributes pass through unchanged, so
`src/security/sandbox/windows.py` still imports normally. The guard does not
call any real API; the test payload only accesses the attribute.

### Child result integrity

`run_guarded_import_probe()` now requires all of:

- child exit code `0`;
- a valid JSON result;
- no `violations`;
- no `probe_error` (unhandled child failure);
- `ok` is false for a crashed, interrupted or invalid child.

Import errors are still reported separately as `errors`; they do not turn a
security-clean import into a violation. `check_hygiene()` maps violations to
FAIL and import errors to WARN, preserving the optional-dependency distinction.

### Static scanner

- The broad sandbox file exclusion is removed.
- An AST helper (`_security_call_lines`) allows only `SetSecurityInfo` calls
  inside the documented `_grant_to_object` function, and only when the file
  contains `ALL APPLICATION PACKAGES` and no `WD`/`GA` SDDL.
- A call elsewhere in the sandbox file is still flagged.
- `scripts/` is scanned for repair payloads (`SetSecurityInfo`, Everyone/GA
  SDDL, `runner.exe`, `repair_winsta`, `-ExecutionPolicy Bypass`,
  `_trigger_repairs`, `_diag_pid`).
- The 11 known P1 standalone-script developer paths are recorded as an explicit
  set, not hidden by a directory exclusion.

---

## 5. Synthetic tests and results

`src/tests/test_security_containment.py` now has 35 tests:

| Area | Coverage |
|---|---|
| Process | run, Popen, call, check_call, check_output, os.system, os.popen, os.execv, os.spawnv, asyncio, multiprocessing; startfile (Windows), fork (POSIX) |
| Writes | `open`, `io.open`, `Path.write_text`, `os.open`, sibling prefix collision |
| Windows API | `SetSecurityInfo`, `SetNamedSecurityInfoW`, `SetUserObjectSecurity` via guarded ctypes |
| Child integrity | hard `os._exit(3)` is not successful; import error is non-security |
| Static scanner | narrow sandbox allowlist, calls elsewhere rejected, scripts scan, documented P1 set |
| Existing | import purity, full import, sanitizer, checkup guard |

```text
34 passed, 1 skipped (os.fork is POSIX-only) in 34.08 s
```

The skip is `test_process_guard_blocks_fork`; `os.fork` is unavailable on
Windows. All other synthetic guard tests executed.

## 6. Full guarded import

Default `run_guarded_import_probe()` against every configured core package:

```text
ok              True
violations      []
error_count     0
probe_error     (empty)
returncode      0
```

The complete configured surface imported in a fresh child with no process
launch, external write or Windows security API access.

## 7. Final validation (2026-11-08)

All four required commands were run from the project virtual environment on
HEAD `bb94f7409ca05c14507fe164ad8c6f5b11514170`. The expected baseline
`7a714e2496199b4d3925003bbb0a404a1ac6e31e` is the parent of this commit; no
history was rewritten.

| Command | Result | Exit |
|---|---|---|
| AST validation of changed Python files | `AST OK` | 0 |
| `pytest src/tests/test_security_containment.py -q` | **34 passed, 1 skipped** in 34.08 s | 0 |
| `python scripts/agent_core_checkup.py` | **57 pass, 5 warn, 0 fail, 3 noted** | 0 |
| `pytest src/tests/test_agent_core_checkup.py -q` | **19 passed** in 154.76 s | 0 |

The 5 checkup WARNs are pre-existing design observations (guarded imports of
missing optional `hermes_state`/`agent.errors`, key presence, tool-result token
bound, cost leg, compaction/cache interaction). No FAIL.

### Evidence logs

Unique directory:

```text
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_1_final_20261108_110636\
  01_ast.log
  02_security_tests.log
  03_standalone_checkup.log
  04_checkup_tests.log
```

These are outside the repository; no existing evidence file was overwritten.

## 8. Other verification

| Command | Result |
|---|---|
| AST parse of changed Python files | OK |
| `pytest test_agent_core_checkup.py test_memory_package.py test_vector_memory.py test_status_contract.py test_live12_readiness.py -q` | **47 passed** in 175.88 s |
| `python scripts/agent_core_checkup.py --json ... --md ...` | **57 pass, 5 warn, 0 fail**, exit 0 |

The standalone checkup's WARNs are pre-existing design observations (guarded
imports of missing optional `hermes_state`/`agent.errors`, key presence, tool
result token bound, cost leg, compaction/cache interaction). No FAIL.

## 9. CI results

**NOT RUN in CI.** All results above are local Windows, provider-free runs. No
CI job was triggered by this phase. The existing
`.github/workflows/agent-core-checkup.yml` will exercise the guarded checkup on
a future push; its result is not claimed here.

## 10. Remaining limitations and uncovered bypasses

- `os.replace` / `os.rename` destinations are not intercepted; a file created
  inside the repository could be moved outside by a payload that avoids
  `open`/`write`.
- `os.fdopen` on an already-open fd, `os.link`/`os.symlink`, and native C
  extension writes can bypass the Python-level write wrappers.
- The ctypes guard covers the listed security names only. A different API name
  or a direct native call in a prebuilt extension is not intercepted.
- `multiprocessing` guards `Process.start`; other process pools ultimately use
  it, but a bespoke native launcher is not covered.
- The static scanner is Python-source oriented; it does not inspect binaries or
  third-party package internals.
- The sandbox allowlist depends on the `_grant_to_object` function name; a
  rename would disable the exception and make the scanner fail closed (safe).
- The machine-level WindowStation/Desktop ACL recovery remains separate and
  unresolved.
- No Electron launch, provider call, database migration or ACL operation was
  performed.
