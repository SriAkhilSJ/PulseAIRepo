# Phase 1.3 — Final Guard Hardening

**Scope:** close the remaining Python-level import-safety gaps: CWD changes,
filesystem mutations, descriptor writes, and strict AppContainer allowlisting.
No Crusor product behaviour, provider, database, Electron or ACL operation was
changed.

> The guarded import process is **regression instrumentation**, not an OS-level
> sandbox. Native extensions and direct OS calls remain outside its reach.

---

## 1. Baseline

| Item | Value |
|---|---|
| Repository | `SriAkhilSJ/PulseAIRepo` |
| Branch | `feat/prompt-cache-stabilization` |
| Expected start HEAD | `38f06d8fa4673658879da9923d993e6aef17879e` |
| Actual start HEAD | identical |
| Origin at start | identical |
| Pre-existing dirty entries | 175, preserved |

## 2. Vulnerabilities addressed

| # | Vulnerability | Previous behavior |
|---|---|---|
| 1 | CWD escape | `_inside_root()` joined relative paths against `_root`, but the OS resolves them against the actual CWD. A module could `os.chdir(external)` and then write `escape.txt` outside. |
| 2 | Directory creation | `os.mkdir`, `os.makedirs`, `Path.mkdir` were unguarded. |
| 3 | Deletion | `os.unlink`/`remove`/`rmdir`/`removedirs`, `Path.unlink`/`rmdir` were unguarded. |
| 4 | Truncation | `os.truncate`/`os.ftruncate` were unguarded. |
| 5 | Descriptor wrapping | writable `os.fdopen` was unguarded. |
| 6 | Weak sandbox allowlist | the AST accepted the documented values if they appeared anywhere; it did not reject a second assignment, changed flags/arguments, a broken `SetEntriesInAclW`/`p_new_dacl` flow, or an extra mutation. |

## 3. Changes

`scripts/agent_core_checkup.py`

- `os.chdir`, `os.fchdir` (where available) and `os.chroot` (where available)
  are blocked during the import probe. CWD changes are unnecessary for the
  probe.
- `_inside_root()` resolves relative paths with `os.path.realpath()` against
  the **actual CWD**, matching OS resolution. Containment remains canonical and
  fail-closed.
- Guarded path mutations:
  - `os.mkdir`, `os.makedirs`, `pathlib.Path.mkdir`
  - `os.unlink`, `os.remove`, `os.rmdir`, `os.removedirs`,
    `pathlib.Path.unlink`, `pathlib.Path.rmdir`
  - `os.truncate` (path or descriptor)
  - `os.ftruncate`
- Writable `os.fdopen` is rejected; read-only `os.fdopen` remains allowed.
- `dir_fd`/`src_dir_fd`/`dst_dir_fd` writes continue to be rejected.
- The probe redirects `HOME`, `USERPROFILE`, `HOMEDRIVE`, `HOMEPATH`, `TMP`,
  `TEMP` and `TMPDIR` into a repository-local scratch directory. Benign
  import-time cache directory creation (for example `~/.crusorai`) is therefore
  contained, while writes to the real user profile remain blocked.
- `PYTHONDONTWRITEBYTECODE=1` remains set.

`src/tests/test_security_containment.py`

- `_security_call_lines()` now requires exactly one assignment for each of:
  `grfAccessPermissions=GENERIC_ALL`, `grfAccessMode=GRANT_ACCESS`,
  `grfInheritance=NO_INHERITANCE`, `TrusteeForm=TRUSTEE_IS_NAME`,
  `TrusteeType=TRUSTEE_IS_WELL_KNOWN_GROUP`,
  `ptstrName="ALL APPLICATION PACKAGES"`.
- Exactly one `SetEntriesInAclW` call, assigned to `ret2`, with the documented
  four arguments.
- Exactly one `p_new_dacl = ctypes.c_void_p()` assignment, exactly one
  `LocalFree(p_new_dacl)`, and the `SetSecurityInfo` call inside `if ret2 == 0:`.
- The exact seven `SetSecurityInfo` arguments are required:
  `handle`, `SE_WINDOW_OBJECT`, `DACL_SECURITY_INFORMATION`, `None`, `None`,
  `p_new_dacl`, `None`.
- Any second assignment, changed value, changed argument, extra security
  mutation, or broken flow returns an empty allowlist so the scanner rejects it.

## 4. Synthetic coverage

CWD:

- `os.chdir` escape, with no external file created.
- `os.fchdir` escape where available.
- Relative `os.replace`, `os.rename`, `os.symlink` escape paths.

Filesystem mutations:

- external directory creation (`os.mkdir`, `os.makedirs`, `Path.mkdir`)
- external file deletion (`os.unlink`, `os.remove`, `Path.unlink`)
- external directory deletion (`os.rmdir`, `os.removedirs`, `Path.rmdir`)
- external path truncation (`os.truncate`)
- descriptor truncation (`os.ftruncate`)
- writable descriptor wrapping (`os.fdopen`)
- legitimate repository-local create/write/unlink/rmdir

Every attack asserts the external target is unchanged or absent. Only temporary
test directories are used.

Allowlist mutations:

- trustee reassignment to Everyone
- permission reassignment
- trustee-type reassignment
- changed `DACL_SECURITY_INFORMATION` flags
- changed owner/group/DACL/SACL arguments
- extra `SetNamedSecurityInfoW` mutation
- broken `SetEntriesInAclW` flow
- missing `LocalFree(p_new_dacl)`
- missing `ret2 == 0` guard

## 5. Actual results

| Command | Result | Exit |
|---|---|---|
| AST validation | `AST OK` | 0 |
| Static scan subset | **15 passed** | 0 |
| CWD escape subset | **4 passed, 1 skipped** | 0 |
| Filesystem mutation subset | **13 passed** | 0 |
| Allowlist mutation subset | **12 passed** | 0 |
| Full `test_security_containment.py` | **72 passed, 3 skipped** in 42.80 s | 0 |
| Full guarded-import test | **1 passed** in 21.32 s | 0 |
| Standalone agent-core checkup | **57 pass, 5 warn, 0 fail** | 0 |
| Agent-core checkup tests | **19 passed** in 171.75 s | 0 |

Skips:

- `test_process_guard_blocks_fork` — `os.fork` is POSIX-only.
- `test_dir_fd_external_directory_rejected` — `os.open(dir_fd=...)` is not
  supported on Windows.
- `test_fchdir_escape_blocked` — `os.fchdir` is not available on Windows.

The 5 checkup WARNs are pre-existing design observations (optional
`hermes_state`/`agent.errors` guards, key presence, tool-result token bound,
cost leg, compaction/cache interaction). No FAIL.

## 6. CI results

Phase 1.2 implementation commit `c32582db`:

| Workflow | Platform / jobs | Result |
|---|---|---|
| Agent-core body checkup | `ubuntu-latest` | **success** |
| Host compatibility | `windows-latest`, `macos-latest`, `ubuntu-latest` | **success** (all three) |

Phase 1.3 CI is triggered by the delivery commit and is not claimed until the
push completes; the final report records the observed result.

## 7. Residual limitations

- Native C extensions and direct OS calls are not contained.
- `os.write`/`os.pwrite` descriptor writes, `os.sendfile`, and
  `os.copy_file_range` are not intercepted; descriptor truncation and writable
  `os.fdopen` are.
- The ctypes security guard covers the listed mutation names only.
- `multiprocessing` guards `Process.start`; bespoke native launchers are not
  covered.
- Static scanning is Python-source oriented; binaries and third-party internals
  are out of scope.
- The AppContainer allowlist depends on the exact `_grant_to_object` shape; any
  change fails closed and requires an explicit audit update.
- Machine-level WindowStation/Desktop ACL recovery remains separate and
  unresolved.
- No host-level or live desktop security is claimed.

## 8. Explicit non-actions

No Windows ACL change, repair script, `runner.exe`, Electron/CrusorAI launch,
provider call, reservation, database write or migration was performed during
this phase.

## 9. Evidence logs

```text
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_3_final_20261108_192435\
  01_ast.log
  02_static.log
  03_cwd.log
  04_fs_mutations.log
  05_allowlist_mutations.log
  06_full_security.log
  07_full_guarded_import.log
  08_standalone_checkup.log
  09_checkup_tests.log
```

These are outside the repository; no existing evidence file was overwritten.
