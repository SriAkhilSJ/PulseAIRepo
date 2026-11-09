# Phase 1.3.3 - Class Body and Module Initialization Hardening

**Scope:** static security checker and its tests. No Crusor product behaviour,
AppContainer policy, provider, database, Electron or ACL operation was changed.

> The checker is static AST analysis, not an OS sandbox. It validates the
> exact class layouts and module initialization of the Windows sandbox file.

---

## 1. Baseline

| Item | Value |
|---|---|
| Repository | `SriAkhilSJ/PulseAIRepo` |
| Branch | `feat/prompt-cache-stabilization` |
| Expected start HEAD | `385925bfafa66eacd7779b3e0adc32eacbda45a4` |
| Actual start HEAD | identical |
| Origin at start | identical |
| Pre-existing dirty entries | 175, preserved |
| Checker | `src/tests/test_security_containment.py` |
| Previous suite size | 161 tests |

## 2. Gaps addressed

Phase 1.3.2 validated the grant function and protected-name bindings but left
three structural gaps:

| # | Gap | Risk |
|---|---|---|
| 1 | `EXPLICIT_ACCESS_W` was checked by name and base only | A class body could execute code, add methods, change `_fields_` order/types, or introduce descriptors. |
| 2 | Other `ctypes.Structure` classes and module classes were not validated | An extra class with an executable body, or a modified `TRUSTEE_W`, could change runtime layout or run code at import. |
| 3 | `_canonical_windll()` accepted a direct call and only loosely checked the conditional | Arbitrary expressions, conditions, arguments or fallbacks could be embedded in the DLL initialization. |

## 3. Implementation

`src/tests/test_security_containment.py`

### 3.1 Exact structure layouts

`_EXPECTED_STRUCTURES` now records all eleven `ctypes.Structure` classes used by
the sandbox:

`IO_COUNTERS`, `JOBOBJECT_BASIC_LIMIT_INFORMATION`,
`JOBOBJECT_EXTENDED_LIMIT_INFORMATION`,
`JOBOBJECT_CPU_RATE_CONTROL_INFORMATION`, `SECURITY_ATTRIBUTES`,
`SECURITY_CAPABILITIES`, `STARTUPINFOW`, `STARTUPINFOEXW`,
`PROCESS_INFORMATION`, `TRUSTEE_W`, `EXPLICIT_ACCESS_W`.

Each entry is an ordered tuple of `(field_name, type_expression)`. The type
expression is normalized from the AST: names, dotted names, and calls such as
`ctypes.POINTER(wintypes.BYTE)`.

`_structure_body_ok()` requires:

- exactly one base: `ctypes.Structure`,
- no decorators or class keywords,
- a class body of exactly one statement,
- exactly one assignment to `_fields_` with a list value (not a tuple),
- exactly the expected number of fields,
- each field a two-element tuple with a string name and the exact type,
- exact order, exact names, exact types,
- no extra assignment, method, nested class, property, expression or call.

`_canonical_explicit_access()` now applies the same body check, so
`EXPLICIT_ACCESS_W` is validated structurally, not just by its header. Its
`Trustee` field must be exactly `TRUSTEE_W`, and `TRUSTEE_W` itself must match
its documented five-field layout.

### 3.2 Module class validation

`_module_classes_ok()` validates every module-level `ClassDef`:

- `ctypes.Structure` subclasses must be one of the eleven expected classes,
  appear at most once, and match the exact body.
- `WindowsSandboxManager` may contain a docstring and methods only. Class-level
  assignments, expressions, calls, nested classes or extra descriptors fail.
- Any other module-level class fails closed, including `class Evil: pass` and
  classes with executable bodies.

This rejects extra module-level classes, extra nested methods/classes, and
class-body execution.

### 3.3 Exact DLL initialization

`_canonical_windll_value()` now requires the complete documented expression:

```python
ctypes.WinDLL("<name>", use_last_error=True)
    if sys.platform == "win32"
    else None
```

Specifically:

- the value must be an `IfExp` (a direct call is rejected),
- the test must be exactly `sys.platform == "win32"` (a call or other expression
  is rejected),
- the receiver must be exactly `ctypes.WinDLL`,
- exactly one positional argument, a string equal to the variable name without
  its leading underscore (`_advapi32` -> `"advapi32"`),
- exactly one keyword argument: `use_last_error=True`,
- the fallback must be exactly `None`,
- no additional positional or keyword arguments.

`_module_assignment_value_ok()` restricts every module-level assignment to a
constant or one of these canonical WinDLL expressions. Arbitrary calls,
subscripts, aliases and other executable expressions are rejected.

### 3.4 Alias protection

`_protected_alias_ok()` rejects copying `ctypes`, `_advapi32`, `_kernel32` or
`EXPLICIT_ACCESS_W` into an untracked local name, including tuple/list
destructuring. This closes:

```python
c = ctypes
c.byref = evil

a = _advapi32
a.SetSecurityInfo = evil
```

Module-level aliases are also rejected by the module assignment rule; sibling
functions and methods are covered by the alias scan.

### 3.5 Retained checks

The Phase 1.3.2 exact eighteen-statement grant whitelist, protected-name binding
rules, local shadowing checks, attribute-mutation checks and full API contract
validation remain in force. No previous adversarial test was weakened.

## 4. Adversarial tests

The suite grew from 161 to **192 tests** (+31). New coverage:

| Category | Tests |
|---|---|
| Positive control with the genuine `TRUSTEE_W` and `EXPLICIT_ACCESS_W` classes | 1 |
| Executable class bodies: helper call, `exec`, aliased `setattr`, nested class, nested method, alias mutation | 6 |
| Reordered `EXPLICIT_ACCESS_W` fields | 1 |
| Changed field type | 1 |
| Extra field | 1 |
| Reordered `TRUSTEE_W` fields | 1 |
| Extra module-level classes (executable body, `exec`, `pass`) | 3 |
| Changed DLL initialization (condition, call, receiver, name, arguments, fallback, missing conditional) | 10 |
| Module aliases mutating `ctypes` / `_advapi32` | 2 |
| Sibling-scope aliases mutating `ctypes` / `_advapi32` | 2 |
| Executable module-level assignments | 3 |

Every negative test asserts `_security_call_lines(sample) == set()`. The
positive control asserts the genuine layouts are accepted and the real
`src/security/sandbox/windows.py` is still allowlisted.

## 5. Verification

Commands were run from the repository root with
`.\.venv\Scripts\python.exe` (Python 3.14.4) and a clean CI-parity venv
(Python 3.14.4 plus the workflow dependency set).

| Check | Result | Exit |
|---|---|---|
| AST validation | `AST OK` | 0 |
| Class structure subset | **8 passed** | 0 |
| Class-body mutation subset | **6 passed** | 0 |
| DLL initialization subset | **10 passed** | 0 |
| Module binding/alias subset | **7 passed** | 0 |
| Full static security scan | **130 passed** | 0 |
| Full `test_security_containment.py` | **189 passed, 3 skipped** in 20.37 s | 0 |
| Full guarded import | **1 passed** in 9.39 s | 0 |
| Standalone agent-core checkup | **57 pass, 5 warn, 0 fail** | 0 |
| Agent-core checkup tests | **19 passed** in 62.67 s | 0 |
| CI-parity clean 3.14 venv | **189 passed, 3 skipped** in 12.07 s | 0 |

Skips on Windows: `os.fork`, external-directory `os.open(dir_fd=...)`,
`os.fchdir`. The 5 checkup warnings are the known pre-existing design
observations; no FAIL.

## 6. CI results

Workflow `Security guard`, commit `1264d9904a78a53fa4b4d83bd46e035cf74dd909`,
run `42571837431`, **success**:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129010742092` | 188 passed, 4 skipped in 8.16 s |
| Security containment (windows-latest) | Windows | `129010742187` | 186 passed, 6 skipped in 12.30 s |
| Security containment (macos-latest) | macOS | `129010741861` | 188 passed, 4 skipped in 7.59 s |

All three jobs ran Python 3.14.10. Ubuntu/macOS skip the four Windows-only or
drive-letter probes; Windows additionally skips three cross-drive probes
because the checkout is on `D:` and temp is on `C:`. No test failed and no
platform was skipped wholesale.

The Python 3.11 Windows `platform.system()` issue remains a separate documented
limitation; the 3.14 results are not evidence of 3.11 Windows coverage.

## 7. Residual limitations

- Static AST validation only. It cannot stop generated code, native extensions,
  direct OS calls, a different file, or a compromised interpreter.
- The expected structure map duplicates the real `ctypes` layouts. Any
  legitimate layout change must update the map and the positive control in the
  same audited change.
- Only the named `ctypes.Structure` classes and `WindowsSandboxManager` are
  accepted at module scope. New module-level classes fail closed by design.
- The checker validates shape and bindings, not the runtime implementation of
  `ctypes`, `advapi32`, `kernel32` or the OS.
- Python 3.11 on Windows still spawns `cmd /c ver` through `platform.system()`;
  the security CI runs 3.14, so 3.11 Windows guard coverage is not claimed.
- Machine-level WindowStation/Desktop ACL recovery remains unresolved.

## 8. Explicit non-actions

No Windows ACL change, repair script, `runner.exe`, Electron launch, provider
call, reservation, database write or migration was performed. No product source
module changed.

## 9. Evidence logs

```text
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_3_3_20261108_221046\
  01_ast.log
  02_class_structure.log
  03_class_body_mutation.log
  04_dll_init.log
  05_module_binding.log
  06_static_scan.log
  07_full_security.log
  08_guarded_import.log
  09_checkup.log
  10_checkup_tests.log
  11_ci_parity.log
```
