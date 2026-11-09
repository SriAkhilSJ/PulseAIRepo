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
| Full `test_security_containment.py` | **88 passed, 3 skipped** in 18.90 s | 0 |
| Full guarded import | **1 passed** in 10.26 s | 0 |
| Standalone agent-core checkup | **57 pass, 5 warn, 0 fail** | 0 |
| Agent-core checkup tests | **19 passed** in 62.65 s | 0 |

Skips: `os.fork` (Windows), external-directory `os.open(dir_fd=...)`
(Windows), `os.fchdir` (Windows).

The 5 checkup WARNs are the same pre-existing design observations. No FAIL.

## 6. CI results

Workflow `Security guard`, Phase 1.3.1 delivery commit:

| Job | Platform | Result | Run |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | pending | pending |
| Security containment (windows-latest) | Windows | pending | pending |
| Security containment (macos-latest) | macOS | pending | pending |

The run IDs are recorded after the delivery push. Unrelated Host compatibility
target-contract jobs are not security-test evidence.

## 7. Residual limitations

- The checker is static AST analysis, not an OS sandbox. Generated code,
  aliasing, `exec`/`eval`, native extensions, direct `ctypes` calls and
  non-Python launchers are outside its reach.
- Only `_grant_to_object` is allowlisted; the rest of the sandbox file remains
  subject to the separate static payload patterns.
- The checker requires the exact documented shape. Any future policy change
  fails closed and requires an explicit audit update.
- Machine-level WindowStation/Desktop ACL recovery remains unresolved.
- No host-level or live desktop security is claimed.

## 8. Explicit non-actions

No Windows ACL change, repair script, `runner.exe`, Electron/CrusorAI launch,
provider call, reservation, database write or migration was performed.

## 9. Evidence logs

```text
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_3_1_final_20261108_194805\
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
```
