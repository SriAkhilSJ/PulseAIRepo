# Phase 1.2 — Filesystem Guard Hardening

**Scope:** close the identified guard bypasses. No Crusor product behaviour,
provider, database, Electron or Windows ACL operation was changed.

> The guarded import process is **regression instrumentation**, not an OS-level
> security sandbox. It raises the cost of an accidental or injected import-time
> side effect; it cannot contain a native extension or an arbitrary OS call.

---

## 1. Baseline

| Item | Value |
|---|---|
| Repository | `SriAkhilSJ/PulseAIRepo` |
| Branch | `feat/prompt-cache-stabilization` |
| Expected start HEAD | `2204e320c5f80b2fc46b1ba2e434f8d74c8029c8` |
| Actual start HEAD | identical |
| Origin at start | identical |
| Pre-existing dirty entries | 175, preserved |

## 2. Vulnerabilities found

| # | Vulnerability | Previous behavior |
|---|---|---|
| 1 | **Fail-open containment** | `_inside_root()` returned `True` when `os.fspath`/`realpath`/`commonpath` raised. An unresolvable path was permitted. |
| 2 | **Nested-write bypass** | A global `_write_depth` made nested wrapper calls skip validation. A custom `opener=` callback could call `os.open()` on an external path while the outer write was marked in progress. |
| 3 | **`dir_fd` escape** | `os.open("escaped.txt", O_CREAT|O_WRONLY, dir_fd=external_fd)` validated the relative string as if it resolved under the repo, then the OS resolved it under the external directory descriptor. |
| 4 | **Path-mutation APIs** | `os.replace`, `os.rename`, `os.link`, `os.symlink` were unguarded; a file inside the repository could be moved/linked outside, or an external file moved in. |
| 5 | **Broad sandbox allowlist** | `_security_call_lines()` allowed every `SetSecurityInfo` call inside `_grant_to_object`, so a second inserted mutation escaped inspection. |

## 3. Implementation changes

`scripts/agent_core_checkup.py`

- `_inside_root()` is **fail-closed**:
  - `os.fspath`/`realpath`/`commonpath` failures return `False`;
  - relative paths are resolved against the repository root, not the process
    CWD;
  - symlinked parents are resolved by `realpath`;
  - sibling-prefix collisions remain rejected by `commonpath`.
- `_write_depth` is removed. Every entry point independently validates:
  - `builtins.open`, `io.open`, `os.open` (write flags), `Path.open`,
    `Path.write_text`, `Path.write_bytes`.
- `os.open` write operations with `dir_fd`/`src_dir_fd`/`dst_dir_fd` are
  rejected. Read-only `os.open` with `dir_fd` remains allowed.
- New guards validate both sides of:
  - `os.replace`, `os.rename`, `os.link` (source and destination);
  - `os.symlink` (link destination and resolved target).
- `PYTHONDONTWRITEBYTECODE=1` is set for the probe so import machinery cannot
  create external `.pyc` files.
- The probe temp directory remains inside the repository and is removed after
  the run.

`src/tests/test_security_containment.py`

- `_security_call_lines()` now requires the documented AppContainer shape:
  `_grant_to_object`, `grfAccessPermissions = GENERIC_ALL`,
  `ptstrName = "ALL APPLICATION PACKAGES"`, `SetEntriesInAclW`, **exactly one**
  `SetSecurityInfo`, and the documented `handle` / `SE_WINDOW_OBJECT` /
  `p_new_dacl` arguments.
- A second `SetSecurityInfo` inside `_grant_to_object` makes the allowlist
  empty, so the scanner rejects it.
- Added scanner patterns for `SetNamedSecurityInfoW/A`,
  `SetKernelObjectSecurity`, `SetUserObjectSecurity`, `NtSetSecurityObject`.

## 4. New synthetic tests

| Test | Checks |
|---|---|
| `test_invalid_path_fails_closed` | `open(object(), "w")` is rejected |
| `test_different_drive_fails_closed` | Windows different-drive path rejected |
| `test_allowed_repository_local_write` | legitimate in-repo write succeeds |
| `test_relative_path_resolves_against_root` | relative path is contained by root |
| `test_custom_opener_nested_external_write_blocked` | opener callback's external `os.open` is blocked; neither file remains |
| `test_dir_fd_write_rejected` | write with `dir_fd` rejected; no file |
| `test_dir_fd_external_directory_rejected` | POSIX external dir-fd write blocked; POSIX-only |
| `test_external_replace_blocked` | external `os.replace` destination blocked |
| `test_external_rename_blocked` | external `os.rename` destination blocked |
| `test_external_link_blocked` | external hard link blocked |
| `test_external_symlink_blocked` | external symlink blocked |
| `test_external_source_move_into_repo_blocked` | external source moved into repo blocked |
| `test_sandbox_allowlist_rejects_second_mutation_inside_grant` | second mutation inside `_grant_to_object` rejected |
| `test_sandbox_allowlist_does_not_hide_calls_elsewhere` | calls outside the documented function are not hidden |

Every attack test asserts the external target does not exist afterwards. No
test writes to the user's real diagnostic directory.

## 5. Actual results

Verified on HEAD `2204e320` plus the Phase 1.2 working tree.

| Command | Result | Exit |
|---|---|---|
| AST validation | `AST OK` | 0 |
| Static scan subset (`-k "static or sandbox or scripts_have or known_p1"`) | **6 passed** | 0 |
| Filesystem bypass subset | **11 passed, 1 skipped** | 0 |
| Full `test_security_containment.py` | **46 passed, 2 skipped** in 45.49 s | 0 |
| Full guarded import probe | `ok=True`, `violations=[]`, `error_count=0`, `probe_error=""`, `returncode=0` | 0 |
| Standalone agent-core checkup | **57 pass, 5 warn, 0 fail, 3 noted** | 0 |
| Agent-core checkup tests | **19 passed** in 177.21 s | 0 |

Skips:

- `test_process_guard_blocks_fork` — `os.fork` is POSIX-only.
- `test_dir_fd_external_directory_rejected` — `os.open(dir_fd=...)` is not
  supported on Windows.

The 5 checkup WARNs are the pre-existing design observations (optional
`hermes_state`/`agent.errors` guards, key presence, tool-result token bound,
cost leg, compaction/cache interaction). No FAIL.

## 6. CI results

Phase 1.2 implementation commit `c32582db`:

| Workflow | Platform / jobs | Result | Run |
|---|---|---|---|
| Agent-core body checkup | `ubuntu-latest` (`checkup`) | **success** | 42515332263 |
| Host compatibility | `windows-latest`, `macos-latest`, `ubuntu-latest` (`Target contracts`) | **success** (all three) | 42515332279 |

Phase 1.1 implementation commit `bb94f740`:

| Workflow | Platform / jobs | Result | Run |
|---|---|---|---|
| Agent-core body checkup | `ubuntu-latest` (`checkup`) | **success** | 42512697497 |
| Host compatibility | `windows-latest`, `macos-latest`, `ubuntu-latest` | **success** (all three) | 42512697504 |

The docs-only commit `2204e320` did not trigger the path-filtered Agent-core
checkup; its Host compatibility run succeeded on all three platforms
(run 42513837736).

## 7. Remaining bypasses and limitations

> **Phase 1.3 update:** `os.chdir`/`os.fchdir`, directory creation/deletion,
> `os.truncate`/`os.ftruncate`, writable `os.fdopen`, and a strict AppContainer
> allowlist are now covered. See `PHASE_1_3_FINAL_GUARD_HARDENING.md`.

- Native C extensions and arbitrary OS calls are not contained. The guard only
  wraps Python-visible entry points.
- `os.write` / `os.pwrite` descriptor writes, `os.sendfile`, and native
  extension writes remain outside the Python-level guard.
- The ctypes guard covers the listed security mutation names; other native
  security APIs are not intercepted.
- `multiprocessing` guards `Process.start`; bespoke native launchers are not
  covered.
- Static scanning is Python-source oriented; binaries and third-party internals
  are out of scope.
- The sandbox allowlist depends on the `_grant_to_object` shape; any change
  fails closed (safe) and requires an explicit audit update.
- Machine-level WindowStation/Desktop ACL recovery remains separate and
  unresolved.
- No host-level security or live desktop security is claimed.

## 8. Evidence logs

```text
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_2_final_20261108_112203\
  01_ast.log
  02_static_scan.log
  03_filesystem_bypasses.log
  04_security_containment.log
  05_full_guarded_import.log
  06_standalone_checkup.log
  07_checkup_tests.log
```

These are outside the repository; no existing evidence file was overwritten.
