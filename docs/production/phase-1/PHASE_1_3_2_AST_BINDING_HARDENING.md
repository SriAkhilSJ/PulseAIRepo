# Phase 1.3.2 - AST Binding and Alias Hardening

**Scope:** static security checker and its tests. No Crusor product behaviour,
AppContainer policy, provider, database, Electron or ACL operation was changed.

> The checker is static AST analysis, not an OS sandbox. It validates the
> exact shape and bindings of `_grant_to_object`; it does not make a malicious
> runtime object safe.

---

## 1. Baseline

| Item | Value |
|---|---|
| Repository | `SriAkhilSJ/PulseAIRepo` |
| Branch | `feat/prompt-cache-stabilization` |
| Expected start HEAD | `b72d04c57fd7b807df78234923e2a8b51cdce042` |
| Actual start HEAD | identical |
| Origin at start | identical |
| Pre-existing dirty entries | 175, preserved |
| Checker | `src/tests/test_security_containment.py` |
| Previous suite size | 93 tests |

## 2. Bypasses addressed

Phase 1.3.1 validated exact targets and values but still traversed the function
permissively. The following were still accepted or not explicitly rejected:

| # | Bypass | Example |
|---|---|---|
| 1 | Trustee alias mutation | `trustee = ea.Trustee; trustee.ptstrName = "Everyone"` |
| 2 | Alias of `ea` | `ea_alias = ea; ea_alias.Trustee.ptstrName = ...` |
| 3 | Receiver rebinding | `_advapi32 = evil` before the approved calls |
| 4 | `ctypes` rebinding | `ctypes = evil`; `ctypes.byref(...)` now calls evil |
| 5 | Constructor shadowing | nested `def EXPLICIT_ACCESS_W(): ...` |
| 6 | Constant rebinding | `GENERIC_ALL = 0`, `SE_WINDOW_OBJECT = 0` |
| 7 | Tuple destructuring | `ea.Trustee.ptstrName, = ("Everyone",)` |
| 8 | List destructuring | `[ea.Trustee.ptstrName] = ["Everyone"]` |
| 9 | Walrus assignment | `(ea := evil)`, `(ret2 := 0)` |
| 10 | Loop target | `for ea in [evil]: ...` |
| 11 | Context-manager target | `with x as ctypes: ...` |
| 12 | Import alias shadowing | `import evil as ctypes`, `from evil import _advapi32` |
| 13 | Nested function shadowing | `def _advapi32(): ...` in the enclosing scope |
| 14 | Nested class shadowing | `class ctypes: ...` in the enclosing scope |
| 15 | Attribute monkeypatching | `ctypes.byref = evil`, `del ctypes.byref`, `setattr(...)` |
| 16 | Partial API contracts | only call counts/selected arguments were checked |

## 3. Implementation

`src/tests/test_security_containment.py`

### 3.1 Exact structural whitelist

`_security_call_lines()` no longer walks the function looking for suspicious
nodes. It requires the exact documented structure:

- exactly one `FunctionDef` named `_grant_to_object` in the file,
- signature `(handle)` with no decorators, defaults, varargs, kwargs, posonly or
  kwonly args, and no argument annotation (return `bool` optional),
- a body of exactly **eighteen** statements, in order:
  1. `ea = EXPLICIT_ACCESS_W()`
  2-9. the eight `ea`/`ea.Trustee` assignments with exact values,
  10. `p_dacl = ctypes.c_void_p()`
  11. `p_sec_desc = ctypes.c_void_p()`
  12. `ret = _advapi32.GetSecurityInfo(...)` with all eight arguments,
  13. `if ret != 0: return False`
  14. `p_new_dacl = ctypes.c_void_p()`
  15. `ret2 = _advapi32.SetEntriesInAclW(...)` with all four arguments,
  16. `if ret2 == 0:` containing exactly `SetSecurityInfo(...)` then
      `LocalFree(p_new_dacl)`,
  17. `LocalFree(p_sec_desc)`,
  18. `return ret2 == 0`.

Any extra statement, missing statement, changed branch, changed return, changed
argument, changed receiver or changed order fails closed. This is deliberately
stricter than "no known bad node".

### 3.2 Protected names

The checker treats these as protected:

`_advapi32`, `_kernel32`, `ctypes`, `EXPLICIT_ACCESS_W`, `GENERIC_ALL`,
`GRANT_ACCESS`, `NO_INHERITANCE`, `TRUSTEE_IS_NAME`,
`TRUSTEE_IS_WELL_KNOWN_GROUP`, `SE_WINDOW_OBJECT`,
`DACL_SECURITY_INFORMATION`.

Binding detection covers:

- ordinary, annotated, augmented and deleted assignments,
- tuple/list/starred destructuring,
- `for`/`async for` targets,
- `with`/`async with` optional variables,
- `import` and `from ... import` aliases,
- nested `def`/`async def`/`class` declarations,
- `global`/`nonlocal`,
- exception handler names,
- named expressions (`:=`),
- comprehension targets,
- function parameters,
- `match` capture/rest patterns.

### 3.3 Scope rules

- **Module scope:** only the documented canonical bindings are allowed:
  - `import ctypes` (plain, once),
  - `_kernel32`/`_advapi32` assigned exactly once from
    `ctypes.WinDLL("kernel32"/"advapi32", use_last_error=True)` (with the
    documented `None` fallback),
  - `EXPLICIT_ACCESS_W` defined once as a `ctypes.Structure` subclass,
  - constants bound once with the exact documented numeric values.
  A second binding, a different value, a function/class shadow, or an import
  alias fails closed.
- **Enclosing and sibling scopes:** any protected binding in any function or
  class scope fails closed, including parameters and nested declarations.
- **Module shape:** only a docstring, imports, simple (non-attribute,
  non-subscript) assignments, class definitions and function definitions are
  allowed at module level. Top-level expression calls and attribute/subscript
  assignments fail closed.
- **Attribute mutation:** assignments, augmented assignments, annotations or
  `del` on an attribute/subscript rooted at `ctypes`, `_advapi32`, `_kernel32`
  or `EXPLICIT_ACCESS_W` fail closed, as does any `setattr`/`__setattr__` call
  anywhere in the file.

### 3.4 Full API contracts

- `GetSecurityInfo` must have exactly eight arguments:
  `handle`, `SE_WINDOW_OBJECT`, `DACL_SECURITY_INFORMATION`, `None`, `None`,
  `ctypes.byref(p_dacl)`, `None`, `ctypes.byref(p_sec_desc)`.
- `SetEntriesInAclW` must have exactly four arguments:
  `1`, `ctypes.byref(ea)`, `p_dacl`, `ctypes.byref(p_new_dacl)`.
- `SetSecurityInfo` must have exactly seven arguments:
  `handle`, `SE_WINDOW_OBJECT`, `DACL_SECURITY_INFORMATION`, `None`, `None`,
  `p_new_dacl`, `None`.
- `LocalFree` must be called exactly twice: `LocalFree(p_new_dacl)` after
  `SetSecurityInfo` inside the success branch, and `LocalFree(p_sec_desc)`
  after that branch.
- Failure branch: `if ret != 0:` must return `False`.
- Success branch: exactly the two documented calls under `if ret2 == 0:`.
- Return: `return ret2 == 0`.

## 4. Adversarial tests

The suite grew from 93 to **161 tests** (+68). New coverage:

| Category | Tests |
|---|---|
| Aliases of `ea`, `ea.Trustee`, `_advapi32`, `_kernel32`, `ctypes`, `p_new_dacl` | 6 |
| Receiver rebinding (`_advapi32`, `_kernel32`, `ctypes`) | 3 |
| Constructor/constant rebinding (8 protected names) | 8 |
| Nested constructor, function, class shadowing | 3 |
| Module receiver/constant/`ctypes` rebinding | 3 |
| Import alias shadowing (local and module) | 3 |
| Tuple/list destructuring | 4 |
| Named expressions, including in the success test | 4 |
| Loop and context-manager targets | 2 |
| All eight changed `GetSecurityInfo` arguments | 8 |
| Wrong first/second `LocalFree` argument | 2 |
| Changed failure branch | 2 |
| Changed success branch | 1 |
| Changed return behavior | 2 |
| Allocation order | 1 |
| Signature, decorator, duplicate function | 3 |
| Module function/class shadowing | 4 |
| Attribute monkeypatching (`ctypes.byref`, `ctypes.c_void_p`, receiver methods, `del`, `setattr`, `globals()`) | 7 |
| Attribute monkeypatch in a sibling scope | 1 |
| Any extra statement | 1 |
| Positive control | 1 existing |

All negative tests assert `_security_call_lines(sample) == set()`. The positive
test asserts the genuine implementation (and the real
`src/security/sandbox/windows.py`) remains accepted.

## 5. Verification

Commands were run from the repository root with
`.\.venv\Scripts\python.exe` (Python 3.14.4) and a clean CI-parity venv
(Python 3.14.4 plus the workflow dependency set).

| Check | Result | Exit |
|---|---|---|
| AST validation | `AST OK` | 0 |
| Static security scan subset | **100 passed** | 0 |
| Alias/binding/shadowing subset | **37 passed** | 0 |
| Alternative-assignment subset | **11 passed** | 0 |
| API contract subset | **21 passed** | 0 |
| Full `test_security_containment.py` | **158 passed, 3 skipped** in 48.01 s | 0 |
| Full guarded import | **1 passed** in 22.15 s | 0 |
| Standalone agent-core checkup | **57 pass, 5 warn, 0 fail** | 0 |
| Agent-core checkup tests | **19 passed** in 77.56 s | 0 |
| CI-parity clean 3.14 venv | **158 passed, 3 skipped** in 12.62 s | 0 |

Skips on Windows: `os.fork`, external-directory `os.open(dir_fd=...)`,
`os.fchdir`. The 5 checkup warnings are the known pre-existing design
observations; no FAIL.

## 6. CI results

Workflow `Security guard`, commit `6c55f35021bf358186c76f9e4cd28ae86970c2b7`,
run `42563557065`, **success**:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `128985028576` | 157 passed, 4 skipped in 10.21 s |
| Security containment (windows-latest) | Windows | `128985028853` | 155 passed, 6 skipped in 10.04 s |
| Security containment (macos-latest) | macOS | `128985028790` | 157 passed, 4 skipped in 8.01 s |

All three jobs ran Python 3.14.10. Ubuntu/macOS skip the four Windows-only or
drive-letter probes; Windows additionally skips three cross-drive probes
because the checkout is on `D:` and temp is on `C:`. No test failed and no
platform was skipped wholesale.

The Python 3.11 Windows `platform.system()` issue remains a separate documented
limitation; the 3.14 results are not evidence of 3.11 Windows coverage.

## 7. Residual limitations

- Static AST validation only. It cannot stop generated code, native extensions,
  direct OS calls, a different file, or a compromised interpreter.
- The exact eighteen-statement whitelist fails closed on any legitimate future
  change to `_grant_to_object`; such a change requires an explicit audit update
  and a new positive control.
- The checker validates shape and binding, not the provenance of `handle` or the
  runtime implementation of the imported ctypes/Advapi32 functions.
- Module constants are validated only when bound in the scanned file; the
  canonical values are duplicated in the checker and must move with the policy.
- Python 3.11 on Windows still spawns `cmd /c ver` through `platform.system()`;
  the security CI runs 3.14, so 3.11 Windows guard coverage is not claimed.
- Machine-level WindowStation/Desktop ACL recovery remains unresolved.

## 8. Explicit non-actions

No Windows ACL change, repair script, `runner.exe`, Electron launch, provider
call, reservation, database write or migration was performed. No product source
module changed.

## 9. Evidence logs

```text
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_3_2_20261108_204006\
  01_ast.log
  02_static_scan.log
  03_alias_binding.log
  04_alternative_forms.log
  05_api_contract.log
  06_full_security.log
  07_guarded_import.log
  08_checkup.log
  09_checkup_tests.log
  10_ci_parity.log
```
