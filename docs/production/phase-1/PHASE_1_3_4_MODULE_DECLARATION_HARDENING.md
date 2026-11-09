# Phase 1.3.4 - Module Declaration Integrity

**Scope:** static security checker and its tests. No Crusor product behaviour,
AppContainer policy, provider, database, Electron or ACL operation was changed.

> The checker is static AST analysis, not an OS sandbox. An import allowlist
> reduces declaration-time risk; it does not prove that an imported dependency
> is itself side-effect-free.

---

## 1. Baseline

| Item | Value |
|---|---|
| Repository | `SriAkhilSJ/PulseAIRepo` |
| Branch | `feat/prompt-cache-stabilization` |
| Expected start HEAD | `ba8c0c8b7306947089b1213d2b2b25872be1c170` |
| Actual start HEAD | identical |
| Origin at start | identical |
| Pre-existing dirty entries | 175 preserved (34 tracked + 141 untracked) |
| Checker | `src/tests/test_security_containment.py` |
| Previous suite size | 192 tests |

### Project-memory review

The following tracked documents were read at the starting commit:

`core.md`, `AGENT_HANDOFF.md`, `Agent work.md`,
`CRUSORAI_AGENT_CORE_ARCHITECTURE_AUDIT.md`,
`docs/CRUSOR_FULLSTACK_BENCHMARK.md`,
`docs/AGENT_CORE_DIAGNOSIS_AND_NEXTGEN_ARCHITECTURE.md`,
`docs/AGENT_CORE_COMPLETION_DISCIPLINE.md`,
`PHASE_11_0_PERSISTENT_KNOWLEDGE_MODEL.md`,
`PHASE_11_6_STRICT_COMPLETION_CONTRACT.md`,
`PHASE_11_7_FINAL_VERDICT.md`,
`PHASE_11_8_ARCHITECTURE_AUDIT.md`,
`PHASE_11_8_REMAINING_LIMITATIONS.md`.

Reconciliation of headline claims against detailed evidence:

| Claim | Scope | Evidence and limitation |
|---|---|---|
| `core.md`: "100% Full-Stack Pass" | GatePulse 16-test benchmark across three models | The same document says this "does **not** mean the failed application benchmark now passes". |
| `AGENT_HANDOFF.md`: 100% GatePulse | Agent Core benchmark | The same header preserves the honest full-stack **FAIL** (4/5; SQLite persistence) and says the repair has provider-free evidence only. |
| `Agent work.md`: "fully verified and production-hardened" | Milestone summary | `docs/CRUSOR_FULLSTACK_BENCHMARK.md` records no accepted website, 4/5 tests, and a persistence failure. |
| `CRUSORAI_AGENT_CORE_ARCHITECTURE_AUDIT.md` | Agent Core subsystem architecture | Not a desktop GUI, live-provider, or full-stack acceptance record. |
| `docs/AGENT_CORE_DIAGNOSIS_AND_NEXTGEN_ARCHITECTURE.md` | Target architecture | Its empirical basis is `budget_exhausted`; it is a design specification, not a pass. |
| `docs/AGENT_CORE_COMPLETION_DISCIPLINE.md` | Verification-to-final-response discipline | The live full-stack run remains failed and predates the follow-up. |
| `PHASE_11_6`: `AUTONOMOUS EXECUTION VERIFIED` | 15-stage orchestrator/delivery contract | Does not prove interactive desktop production readiness. |
| `PHASE_11_7`: `INDEPENDENT VERIFICATION VERIFIED` | Verification subsystem (44/44 adversarial, 415/415 milestone suites) | Does not prove live provider or GUI acceptance. |
| `PHASE_11_8`: `PRODUCTION READINESS VERIFIED` | Offline production-readiness analysis | `PHASE_11_8_REMAINING_LIMITATIONS.md` limits legal certification, offline CVE feeds, restore drills, and human deployment authorization. |

Conclusion: no headline PASS is treated here as complete desktop production
readiness. The live full-stack remains failed/unrevalidated, the interactive GUI
is unverified on this host, and provider execution is deterministic-only in the
Phase 12 record.

Tracked GitHub documents are distinguished from the uncommitted local memory
layer (`AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`,
`docs/DECISIONS.md`, `docs/BUGS_AND_LIMITATIONS.md`, `docs/ROADMAP.md`,
`docs/phases/PHASE_TRACKER.md`, `docs/handoffs/`). The local layer is not part of
this phase's commits.

## 2. Part A - Exact import manifest

The checker defines `_EXPECTED_IMPORTS` independently of the parsed source and
compares type, module, level, symbols, aliases, and order.

| # | Type | Module | Symbols | Level |
|---|---|---|---|---|
| 1 | from | `__future__` | `annotations` | 0 |
| 2 | import | - | `ctypes` | 0 |
| 3 | import | - | `os` | 0 |
| 4 | import | - | `re` | 0 |
| 5 | import | - | `shlex` | 0 |
| 6 | import | - | `shutil` | 0 |
| 7 | import | - | `subprocess` | 0 |
| 8 | import | - | `sys` | 0 |
| 9 | import | - | `threading` | 0 |
| 10 | import | - | `time` | 0 |
| 11 | import | - | `uuid` | 0 |
| 12 | from | `ctypes` | `wintypes` | 0 |
| 13 | from | `pathlib` | `Path` | 0 |
| 14 | from | `typing` | `Any`, `Dict`, `List`, `Optional`, `Tuple` | 0 |
| 15 | from | `src.security.contracts` | `ExecutionMode`, `ExecutionRequest`, `SAFE_ENVIRONMENT_KEYS`, `SENSITIVE_SECRET_PATTERNS`, `SandboxBackendType`, `SecurityViolationType` | 0 |
| 16 | from | `src.security.sandbox.base` | `BaseSandboxManager` | 0 |

Rejected: additional imports, star imports, unexpected aliases, duplicate
imports, changed sources, changed levels, and unapproved from-imports.

## 3. Part B - Module declaration manifest

`_EXPECTED_DECLARATIONS` pins the full 62-entry module body in order:

1. module docstring,
2. 16 approved imports,
3. four canonical WinDLL declarations (`_kernel32`, `_advapi32`, `_userenv`,
   `_user32`),
4. 27 approved module constants with exact integer values,
5. eleven `ctypes.Structure` classes in the documented order,
6. `_winsta_desktop_granted = False`,
7. `_ensure_windowstation_desktop_access`,
8. `WindowsSandboxManager`.

Every entry is checked for category, identity, type, and order. The declaration
count must match exactly, so additional executable module-level expressions or
declarations fail closed.

## 4. Part C - Module-level function manifest

The only approved standalone helper is:

```python
def _ensure_windowstation_desktop_access() -> bool:
```

Required:

- exactly one declaration,
- synchronous `FunctionDef` (async rejected),
- no decorators,
- no type parameters or type comment,
- zero positional, positional-only, keyword-only, vararg or kwarg parameters,
- no defaults,
- return annotation exactly `bool`.

The nested `_grant_to_object` remains governed by the Phase 1.3.2 exact
eighteen-statement whitelist, unchanged.

## 5. Part D - WindowsSandboxManager method manifest

`WindowsSandboxManager` must have exactly one base, `BaseSandboxManager`, no
class keywords, no decorators, one exact docstring, and only the following
thirteen methods in this order:

| Method | Decorators | Parameters (name: annotation = default) | Returns |
|---|---|---|---|
| `__init__` | none | `self`; `use_appcontainer: bool = True` | `None` |
| `backend_type` | `property` | `self` | `SandboxBackendType` |
| `appcontainer_sid_str` | `property` | `self` | `Optional[str]` |
| `get_capabilities` | none | `self` | `Dict[str, bool]` |
| `initialize` | none | `self`; `request: ExecutionRequest`; `staging_dir: Path` | `None` |
| `_sanitize_environment` | none | `self`; `request: ExecutionRequest`; `staging_dir: Path` | `Dict[str, str]` |
| `_inspect_filesystem_safety` | none | `self`; `request: ExecutionRequest`; `staging_dir: Path` | `Tuple[bool, Optional[str]]` |
| `execute` | none | `self`; `request: ExecutionRequest`; `staging_dir: Path`; `abort_event: Optional[Any] = None` | `Dict[str, Any]` |
| `_execute_appcontainer` | none | `self`; `request: ExecutionRequest`; `staging_dir: Path`; `cwd: str`; `env: Dict[str, str]`; `abort_event: Optional[Any]` | `Dict[str, Any]` |
| `_execute_job_object_fallback` | none | same as `_execute_appcontainer` | `Dict[str, Any]` |
| `_query_job_counters` | none | `self` | `None` |
| `terminate` | none | `self` | `None` |
| `cleanup` | none | `self`; `staging_dir: Path` | `str` |

Rejected: additional or duplicate manager classes, duplicate or additional
methods, executable decorators, non-literal defaults, class-level assignments,
nested classes, and parameter/annotation drift. Method bodies are deliberately
not whitelisted; implementation remains outside this phase's declaration check.

## 6. Part E - Structure completeness

`_EXPECTED_STRUCTURES` contains the eleven exact ordered field layouts:
`IO_COUNTERS`, `JOBOBJECT_BASIC_LIMIT_INFORMATION`,
`JOBOBJECT_EXTENDED_LIMIT_INFORMATION`,
`JOBOBJECT_CPU_RATE_CONTROL_INFORMATION`, `SECURITY_ATTRIBUTES`,
`SECURITY_CAPABILITIES`, `STARTUPINFOW`, `STARTUPINFOEXW`,
`PROCESS_INFORMATION`, `TRUSTEE_W`, `EXPLICIT_ACCESS_W`.

In full-module mode, `discovered_structures` must equal the expected set
exactly. Missing, duplicate, unexpected, reordered, changed-base, changed-layout
or otherwise modified structures fail closed. Each class body must contain
exactly one `_fields_` assignment; extra expressions or methods are rejected.

## 7. Adversarial tests

The suite grew from 192 to **223 tests** (+31). New coverage:

| Category | Tests |
|---|---|
| Import manifest: arbitrary, star, alias, duplicate, changed source, changed level, unapproved from-import | 7 |
| Additional module function, duplicate helper, decorated helper, decorator call, executable default, async helper, changed signature | 7 |
| Additional/duplicate manager class, duplicate initialize, extra method, executable decorator, executable default, class assignment, nested class | 8 |
| Missing/duplicate structure, changed order, changed fields, extra structure, changed base, class expression, class method | 8 |
| Full-module positive control on the real `windows.py` | 1 |

All negative tests mutate the real sandbox module through the AST, unparse it,
and assert `_security_call_lines(sample, full_module=True) == set()`. The
positive control asserts the real file remains allowlisted.

## 8. Local verification

Commands were run from the repository root with
`.\.venv\Scripts\python.exe` (Python 3.14.4) and a clean CI-parity venv
(Python 3.14.4 plus the workflow dependency set).

| Check | Result | Exit |
|---|---|---|
| AST validation | `AST OK` | 0 |
| Import manifest subset | **7 passed** | 0 |
| Module declaration subset | **7 passed** | 0 |
| Function declaration subset | **6 passed** | 0 |
| Manager method subset | **8 passed** | 0 |
| Structure completeness subset | **8 passed** | 0 |
| Full static security scan | **161 passed** | 0 |
| Full `test_security_containment.py` | **220 passed, 3 skipped** in 23.47 s | 0 |
| Full guarded import | **1 passed** in 8.84 s | 0 |
| Standalone agent-core checkup | **57 pass, 5 warn, 0 fail** | 0 |
| Agent-core checkup tests | **19 passed** in 66.72 s | 0 |
| CI-parity clean 3.14 venv | **220 passed, 3 skipped** in 15.99 s | 0 |

Skips on Windows: `os.fork`, external-directory `os.open(dir_fd=...)`,
`os.fchdir`. The five checkup warnings are the known design observations; no
FAIL.

## 9. CI results

Workflow `Security guard`, commit `ac52ad26411aa1fda7b657b09aea8763258f933b`,
run `42574847574`, **success**:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129020138381` | 219 passed, 4 skipped in 9.23 s |
| Security containment (windows-latest) | Windows | `129020138103` | 217 passed, 6 skipped in 13.86 s |
| Security containment (macos-latest) | macOS | `129020138297` | 219 passed, 4 skipped in 12.36 s |

All three jobs ran Python 3.14.10. Ubuntu/macOS skip the four Windows-only or
drive-letter probes; Windows additionally skips three cross-drive probes
because the checkout is on `D:` and temp is on `C:`. No test failed and no
platform was skipped wholesale.

**Skipped coverage:** Windows CPython 3.11 import compatibility is not proven.
`src/runtime/windows_shell.py` calls `platform.system()` at import time, and
CPython <= 3.12 on Windows spawns `cmd /c ver`; the guard job therefore runs
3.14. The 3.14 results are not evidence of 3.11 Windows coverage.

## 10. Remaining limitations

- Static AST validation only. It cannot stop generated code, native extensions,
  direct OS calls, a different file, or a compromised interpreter.
- The import allowlist bounds declaration-time imports but does not prove the
  imported modules are side-effect-free.
- The structure map, constant values, declaration order and manager manifest
  duplicate the real source; any legitimate change requires an audited update
  and a fresh positive control.
- Only the named module-level declarations are accepted. New module-level
  functions or classes fail closed by design.
- Method bodies are not validated; only declarations are pinned.
- Python 3.11 on Windows remains unproven for the import guard.
- Machine-level WindowStation/Desktop ACL recovery remains unresolved.

## 11. Explicit non-actions

No production sandbox behaviour, AppContainer permission policy, Windows ACL,
WindowStation/Desktop permission, `repair_winsta` script, `runner.exe`, Electron
launch, paid provider call, financial reservation, database write or migration
was performed. No unrelated agent-core architecture was modified.

## 12. Evidence logs

```text
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_3_4_20261108_223933\
  01_ast.log
  02_import_manifest.log
  03_module_declarations.log
  04_function_declarations.log
  05_manager_methods.log
  06_structure_completeness.log
  07_static_scan.log
  08_full_security.log
  09_guarded_import.log
  10_checkup.log
  11_checkup_tests.log
  12_ci_parity.log
```

## 13. Phase 1.3.4R correction

**Starting HEAD:** `00eabb3d8bffa652e2c5e4eb4e3c32f7027d9c17`

### Finding 1 - helper body was not validated

Phase 1.3.4 validated the declaration and signature of
`_ensure_windowstation_desktop_access()` but not its body. Additional executable
statements or nested declarations could therefore be inserted inside the helper.

**Correction.** `_helper_body_ok()` now pins the exact eleven-statement body:

1. non-empty docstring,
2. `global _winsta_desktop_granted`,
3. `if _winsta_desktop_granted: return True`,
4. `if not _advapi32 or not _user32 or not _kernel32: return False`,
5. the nested `def _grant_to_object(handle) -> bool:`,
6. `hwinsta = _user32.GetProcessWindowStation()`,
7. `hdesk = _user32.GetThreadDesktop(_kernel32.GetCurrentThreadId())`,
8. `ok1 = _grant_to_object(hwinsta) if hwinsta else False`,
9. `ok2 = _grant_to_object(hdesk) if hdesk else False`,
10. `_winsta_desktop_granted = ok1 and ok2`,
11. `return _winsta_desktop_granted`.

The checks pin the early-return conditions, the dependency check, the nested
grant declaration, handle acquisition, both grant calls, the state update and
the return. Any extra statement, nested declaration, changed handle, changed
condition, changed call target or changed state expression fails closed.

### Finding 2 - grant ownership was not enforced

`_security_call_lines()` discovered `_grant_to_object` with a whole-tree search,
so a grant defined in another function or class was still accepted.

**Correction.** In full-module mode the checker now:

- requires exactly one module-level
  `_ensure_windowstation_desktop_access`,
- requires exactly one `_grant_to_object` declaration in the whole tree,
- requires that declaration to be a direct child of the helper's body.

Relocation into `WindowsSandboxManager` methods, another module-level function,
another nested function/class, or duplication in another scope is rejected. The
existing exact eighteen-statement grant body remains mandatory.

### Adversarial tests

Eleven new AST-only regressions were added (suite 223 -> 234):

| Test | Mutation |
|---|---|
| extra helper call | `evil()` inserted into the helper |
| extra helper nested function | `def extra(): pass` inserted into the helper |
| grant moved into manager | grant removed from helper, appended to `WindowsSandboxManager.execute` |
| grant moved into another function | grant moved to a new module-level function |
| duplicate grant in manager | grant deep-copied into `WindowsSandboxManager.execute` |
| missing grant | nested grant removed from the helper |
| missing handle assignment | `hwinsta` assignment removed |
| changed early return | one dependency term removed from the `not ... or ...` check |
| changed state update | `_winsta_desktop_granted = ok1 and ok2` changed to `ok1` |
| changed handle acquisition | `GetProcessWindowStation()` replaced with `GetThreadDesktop(GetCurrentThreadId())` |
| swapped grant-call handles | `ok1`/`ok2` call arguments swapped |

The mutations are parsed and unparsed; no inserted call is executed and no
Windows ACL operation is performed. The positive control on the real
`src/security/sandbox/windows.py` still passes.

### Local verification

| Check | Result | Exit |
|---|---|---|
| AST validation | `AST OK` | 0 |
| Helper ownership subset | **11 passed** | 0 |
| Full static security scan | **172 passed** | 0 |
| Full security suite | **231 passed, 3 skipped** in 90.28 s (234 collected) | 0 |
| Full guarded import | **1 passed** in 31.32 s | 0 |
| Standalone agent-core checkup | **57 pass, 5 warn, 0 fail** | 0 |
| Agent-core checkup tests | **19 passed** in 204.89 s | 0 |
| CI-parity clean 3.14 venv | **231 passed, 3 skipped** in 64.67 s | 0 |

### CI results

Workflow `Security guard`, correction commit
`3cc3c3743561b636a6eb3c7fd2637363a9720e0b`, run `42583627343`, **success**:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129048047073` | 230 passed, 4 skipped in 9.13 s |
| Security containment (windows-latest) | Windows | `129048047146` | 228 passed, 6 skipped in 14.03 s |
| Security containment (macos-latest) | macOS | `129048046882` | 230 passed, 4 skipped in 10.87 s |

All three jobs ran Python 3.14.10. Ubuntu/macOS skip the four Windows-only or
drive-letter probes; Windows additionally skips three cross-drive probes. No
test failed and no platform was skipped wholesale.

### Residual limitations

- Static AST validation only; it is not an OS sandbox and does not prove
  production readiness.
- The helper body, import/declaration manifests, structure map, constants and
  manager method signatures duplicate the real source; legitimate changes
  require an audited update and a fresh positive control.
- Manager method bodies remain unvalidated; only declarations are pinned.
- Python 3.11 Windows guard coverage remains unproven because the CI job runs
  3.14 and `platform.system()` spawns `cmd /c ver` on 3.11.
- Machine-level WindowStation/Desktop ACL recovery remains unresolved.

### Evidence logs

```text
C:\Users\Administrator\AppData\Local\Temp\crusor_phase1_3_4r_20261108_235705\
  01_ast.log
  02_helper_ownership.log
  03_static_scan.log
  04_full_security.log
  05_guarded_import.log
  06_checkup.log
  07_checkup_tests.log
  08_ci_parity.log
```
