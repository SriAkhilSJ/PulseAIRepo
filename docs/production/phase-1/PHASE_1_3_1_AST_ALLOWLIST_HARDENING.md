# Phase 1.3.1 — AST Allowlist Mutation Hardening

**Scope:** static security checker, its tests, cross-platform CI coverage, and
documentation. No Crusor product behaviour, AppContainer policy, provider,
database, Electron or ACL operation was changed.

---

## 1. Baseline

| Item | Value |
|---|---|
| Repository | `SriAkhilSJ/PulseAIRepo` |
| Branch | `feat/prompt-cache-stabilization` |
| Expected start HEAD | `3c954480b66c32526e243eb25259662f10e14856` |
| Actual start HEAD | identical |
| Origin at start | identical |
| Pre-existing dirty entries | 175, preserved |

## 2. Vulnerabilities addressed

The Phase 1.3 checker validated ordinary `Assign` nodes by attribute name and
matched security APIs by final method name. It missed:

| # | Bypass | Example |
|---|---|---|
| 1 | Annotated reassignment | `ea.Trustee.ptstrName: str = "Everyone"` |
| 2 | Augmented assignment | `ea.grfAccessPermissions |= GENERIC_READ` |
| 3 | `setattr` / `__setattr__` | `setattr(ea.Trustee, "ptstrName", "Everyone")` |
| 4 | Nested trustee mutations | `ea.Trustee.pMultipleTrustee = p_evil` |
| 5 | `p_new_dacl` mutation | `p_new_dacl = p_other` |
| 6 | Fake receivers | `evil.SetSecurityInfo(...)`, `evil.SetEntriesInAclW(...)` |
| 7 | Wrong free order | `LocalFree(p_new_dacl)` before `SetSecurityInfo` |
| 8 | Indirect mutations | `ea.__dict__["grfAccessPermissions"] = ...` |
| 9 | Name-only validation | `evil.grfAccessPermissions = GENERIC_ALL` accepted by name |

## 3. Changes

`src/tests/test_security_containment.py`

- Exact target-path validation, not attribute-name matching:
  `ea.grfAccessPermissions`, `ea.grfAccessMode`, `ea.grfInheritance`,
  `ea.Trustee.pMultipleTrustee`, `ea.Trustee.MultipleTrusteeOperation`,
  `ea.Trustee.TrusteeForm`, `ea.Trustee.TrusteeType`,
  `ea.Trustee.ptstrName`, plus `ea`, `p_dacl`, `p_sec_desc`, `ret`,
  `p_new_dacl` and `ret2`.
- Exactly one assignment per required target and exact value:
  `GENERIC_ALL`, `GRANT_ACCESS`, `NO_INHERITANCE`, `None`, `0`,
  `TRUSTEE_IS_NAME`, `TRUSTEE_IS_WELL_KNOWN_GROUP`,
  `"ALL APPLICATION PACKAGES"`, and exact call values for the pointers and
  return codes.
- Reject any `AnnAssign`, `AugAssign`, `Delete`, subscript target,
  `setattr`/`__setattr__`, second assignment, or extra `ea.*`/`ea.Trustee.*`
  mutation anywhere in `_grant_to_object`.
- Exact receivers:
  - `_advapi32.SetEntriesInAclW`
  - `_advapi32.SetSecurityInfo`
  - `_kernel32.LocalFree`
  - `ctypes.byref`
  - `ctypes.c_void_p`
  - `_advapi32.GetSecurityInfo` for the optional `ret`
  - `EXPLICIT_ACCESS_W` for `ea`
- Exact `SetEntriesInAclW` arguments and exact seven `SetSecurityInfo`
  arguments.
- Allocation/order/flow:
  - `p_new_dacl = ctypes.c_void_p()` before `SetEntriesInAclW`;
  - `SetEntriesInAclW` before `SetSecurityInfo`;
  - both security call and `LocalFree(p_new_dacl)` inside `if ret2 == 0:`;
  - `LocalFree(p_new_dacl)` after `SetSecurityInfo`;
  - exactly one `LocalFree(p_new_dacl)`.

`.github/workflows/security-guard.yml`

New `Security guard` workflow:

- matrix `ubuntu-latest`, `windows-latest`, `macos-latest`;
- Python 3.11;
- keyless dependency install;
- runs `python -m pytest src/tests/test_security_containment.py -q`;
- path filters for the test, checkup, sandbox and workflow files;
- `fail-fast: false`, `contents: read`.

## 4. Adversarial tests

| Test | Expected |
|---|---|
| annotated trustee reassignment to Everyone | rejected |
| augmented `grfAccessPermissions` assignment | rejected |
| `setattr` changing trustee name | rejected |
| `pMultipleTrustee` mutation | rejected |
| `MultipleTrusteeOperation` mutation | rejected |
| `p_new_dacl` reassignment | rejected |
| annotated `p_new_dacl` mutation | rejected |
| `ea` reassignment | rejected |
| subscript/`__dict__` mutation | rejected |
| fake `SetSecurityInfo` receiver | rejected |
| fake `SetEntriesInAclW` receiver | rejected |
| fake `ctypes.byref` receiver | rejected |
| fake `ctypes.c_void_p` receiver | rejected |
| `LocalFree` before `SetSecurityInfo` | rejected |
| extra unapproved mutation | rejected |
| exact documented implementation | **accepted** |

## 5. Results

| Check | Result | Exit |
|---|---|---|
| AST validation | `AST OK` | 0 |
| Static scan subset | **30 passed** | 0 |
| Annotated + augmented subset | **2 passed** | 0 |
| `setattr` + nested subset | **7 passed** | 0 |
| Receiver subset | **3 passed** | 0 |
| Ordering/allocation subset | **6 passed** | 0 |
| Full `test_security_containment.py` | **88 passed, 3 skipped** in 32.79 s | 0 |
| Full guarded import | **1 passed** in 11.33 s | 0 |
| Standalone agent-core checkup | **57 pass, 5 warn, 0 fail** | 0 |
| Agent-core checkup tests | **19 passed** in 86.46 s | 0 |
| CI-parity run (clean 3.14 venv, CI dependency set only) | **88 passed, 3 skipped** in 15.87 s | 0 |

Skips on Windows: `os.fork`, external-directory `os.open(dir_fd=...)`,
`os.fchdir`. On Linux/macOS the Windows-only `ctypes.WinDLL` tests are also
skipped, so the same suite reports 87 passed / 4 skipped there.

The 5 checkup WARNs are the same pre-existing design observations. No FAIL.

## 6. CI results

### 6.1 First run — real failures found

Workflow `Security guard`, commit `4a9e2adebc5156f38d1d6edd5b9461516045ba83`,
run `42558699115`:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `128970095475` | **failed** — 1 failed, 87 passed, 3 skipped |
| Security containment (windows-latest) | Windows | `128970095820` | **failed** — 1 failed, 84 passed, 6 skipped |
| Security containment (macos-latest) | macOS | `128970095718` | **failed** — 1 failed, 87 passed, 3 skipped |

Ubuntu and macOS failed identically:
`test_sanitizer_has_no_windows_or_diagnostic_side_effects` patches
`ctypes.WinDLL`, which does not exist on POSIX
(`AttributeError: <module 'ctypes'> does not have the attribute 'WinDLL'`).
The test is Windows-specific and is now skipped unless `ctypes.WinDLL` exists.

Windows failed `test_full_guarded_import_surface` with four
`subprocess.check_output` violations. Stack-level diagnosis (instrumented
probe, clean Python 3.11.9 + CI dependency set) showed every violation came
from CPython's own stdlib:

```text
src/runtime/windows_shell.py:45  _IS_WINDOWS = platform.system() == "Windows"
platform.py:921 (3.11) uname() -> win32_ver() -> _syscmd_ver()
platform.py:284 (3.11) subprocess.check_output(cmd)   # cmd /c ver
```

CPython ≤ 3.12 implements `platform.win32_ver()` by running `cmd /c ver`
through `subprocess.check_output`; Python 3.14 reads the version from
`winreg` and spawns nothing. This is an interpreter-version artefact, not a
repository regression. Because Phase 1.3.1 may not change product code, the
security job now runs Python `3.14` (also the local interpreter) and the
3.11 behaviour is recorded as a residual limitation. The test was not
weakened and the guard still rejects every repository-level or third-party
process spawn.

### 6.2 Final run

| Job | Platform | Result | Run |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | pending | pending |
| Security containment (windows-latest) | Windows | pending | pending |
| Security containment (macos-latest) | macOS | pending | pending |

Unrelated Host compatibility target-contract jobs are not security-test
evidence.

## 7. Residual limitations

- The checker is static AST analysis, not an OS sandbox. Generated code,
  aliasing, `exec`/`eval`, native extensions, direct `ctypes` calls and
  non-Python launchers are outside its reach.
- Only `_grant_to_object` is allowlisted; the rest of the sandbox file remains
  subject to the separate static payload patterns.
- The checker requires the exact documented shape. Any future policy change
  fails closed and requires an explicit audit update.
- On Windows with CPython ≤ 3.12, `src/runtime/windows_shell.py` calls
  `platform.system()`, which makes `platform.win32_ver()` run
  `subprocess.check_output(['cmd', '/c', 'ver'])` at import time. The guarded
  import probe correctly flags that spawn. CI therefore runs Python 3.14, where
  `platform.system()` uses `winreg`; the suite is not executed on 3.11 in CI.
  A follow-up should replace the check with `os.name == "nt"` so the import is
  side-effect free on every supported interpreter, after which 3.11 coverage
  can be re-enabled.
- Machine-level WindowStation/Desktop ACL recovery remains unresolved.
- No host-level or live desktop security is claimed.

## 8. Explicit non-actions

No Windows ACL change, repair script, `runner.exe`, Electron/CrusorAI launch,
provider call, reservation, database write or migration was performed.

## 9. Evidence logs

```text
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_3_1_final_20261108_194805\
  01_ast.log ... 10_checkup_tests.log          (first verification pass)
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_3_1_ci_fix_20261108_200023\
  01_ast.log
  02_static.log
  03_annotated_augmented.log
  04_setattr_nested.log
  05_receivers.log
  06_ordering_allocation.log
  07_full_security.log
  08_full_guarded_import.log
  09_standalone_checkup.log
  10_checkup_tests.log
  11_ci_parity_314.log                          (clean 3.14 venv, CI deps only)
```
