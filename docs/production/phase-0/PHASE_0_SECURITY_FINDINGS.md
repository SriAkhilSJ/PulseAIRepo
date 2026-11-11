# Phase 0 — Security Findings

**Scope:** the four named files plus every reachable importer, script and CI path.
**Method:** plain-text inspection and prior-log evidence. No module was executed
during Phase 0. The logs cited below were produced by earlier test/bridge runs,
not by this audit.

---

## 0. Executive summary

Three committed source files contain **import-time or hot-path code that
modifies Windows WindowStation/Desktop security descriptors to grant
`Everyone` (`WD`) generic-all access**, and one of them launches subprocesses
with absolute developer paths. One import path is proven to have executed,
because the repair script's own log records successful `SetSecurityInfo` calls.
A fourth file (`scripts/agent_core_checkup.py`) imports every module, so the
offline checkup and CI also execute the payloads.

This is a **P0 local security-boundary violation**, independent of the agent
logic. It must be removed before any production launch or provider spend.

---

## 1. Reachability graph (text inspection only)

```text
src/bridge/__main__.py:233
  -> src/graphs/chat_graph.py:44
     -> src/context/context_engine.py:62   _diag_pid()                 [import time]
     -> src/context/context_engine.py:103
        -> src/context/memory_manager.py:19
           -> src/context/vector_memory.py:36  _trigger_repairs()      [import time]
              -> powershell.exe -ExecutionPolicy Bypass -File <abs path>
              -> python.exe <abs path>

src/agents/planner.py:8
  -> src/context/context_engine.py (same two payloads)

src/context/cache_preservation.py:35
  -> src/context/context_engine.py (same two payloads)

scripts/agent_core_checkup.py:856-859
  -> importlib.import_module("src.*")
  -> every module above (same two payloads)

src/tests/* (many)
  -> src/context/context_engine.py / src/context/vector_memory.py
  -> same two payloads

src/context/engine.py:27  sanitize_memory_context()
  -> called during context construction (hot path), attempts the same DACL
```

`src/context/engine.py:13-17` also calls `load_dotenv()` at import time; that is
a benign side effect compared with the Windows code, but it is still an
import-time mutation.

---

## 2. Findings

### P0-SEC-01 — Import-time subprocess execution and WindowStation/Desktop ACL weakening

| Field | Value |
|---|---|
| Severity | **P0** |
| File | `src/context/vector_memory.py:14-36` (call at `:36`) |
| Classification | **PROVEN** |

**Explanation.** `_trigger_repairs()` runs at module import:

```python
res_ps = subprocess.run(
    ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", ps_path],
    capture_output=True, text=True,
)
res_py = subprocess.run([sys.executable, py_path], capture_output=True, text=True)
```

`ps_path` and `py_path` are hardcoded:
`c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\scripts\repair_winsta.{ps1,py}`.
Neither call has a timeout. The target scripts build this SDDL:

```text
D:(A;OICI;GA;;;WD)(A;OICI;GA;;;SY)(A;OICI;GA;;;BA)(A;OICI;GA;;;IU)
```

`WD` = Everyone, `GA` = generic all. `repair_winsta.py:23-71` applies it to the
process WindowStation, `WinSta0`, the thread desktop and `Default`.

**Reachability.** `context_engine.py:103` → `memory_manager.py:19` →
`vector_memory.py:36`; `chat_graph.py:44` imports the context engine; the bridge
imports the graph at `__main__.py:233`; the planner and every context test do the
same.

**Evidence (PROVEN).**

- `C:\Users\Administrator\Downloads\CRUSORAI\trigger_debug.log` — **314**
  `_trigger_repairs called` entries, each followed by `PS code: 0` and
  `PY code: 0`.
- `C:\Users\Administrator\Downloads\CRUSORAI\repair_exec.log` — 2,506 lines,
  **626** `SUCCESS` lines; `SetSecurityInfo hwinsta: 0`,
  `SetSecurityInfo h_winsta0: 0`, `SetSecurityInfo hdesk: 0`,
  `SetSecurityInfo h_desk0: 0` (0 = ERROR_SUCCESS).
- The Python repair script is therefore proven to have changed the live
  WindowStation/Desktop DACLs during prior runs.

**User impact.** Any local user or process can obtain full control of the
interactive WindowStation/desktop. That permits synthetic input, screen/content
capture and UI automation across the normal desktop boundary. It is a
persistence and attack-surface expansion, and it violates least privilege. On a
single-user admin laptop the practical exploitability is lower than on a
multi-user host, but the boundary is still broken.

**Reproduction.** Import `src.context.vector_memory` (not done in Phase 0). The
existing logs show the effect. No execution was performed by this audit.

**Remediation.**

1. Delete `_trigger_repairs()` and its call from `vector_memory.py`.
2. Remove `repair_winsta.ps1` / `repair_winsta.py` from the runtime and from the
   repository, or convert them into an explicit, documented, admin-only CLI
   that is never imported.
3. Never grant `WD`/`GA`. Use the minimum required ACEs (owner, SYSTEM, Built-in
   Administrators, INTERACTIVE) and only if a service-account launch genuinely
   requires it.
4. Remove `-ExecutionPolicy Bypass`; sign the script or use an approved policy.
5. Add subprocess timeouts and absolute-path validation if any repair remains.
6. Restore the default WindowStation/Default desktop ACLs on affected machines.

**Required regression tests.**

- Import `src.context.vector_memory` and `src.context.context_engine` with
  `subprocess.run`, `Popen`, `SetSecurityInfo` and `win32security` patched to
  raise; the import must succeed and make zero calls.
- Static test/CI guard: fail if `WD`/`GA` SDDL, `SetSecurityInfo`,
  `-ExecutionPolicy Bypass`, `runner.exe`, or `repair_winsta` appear in
  `src/` or runtime scripts.
- Integration test: starting the bridge must not spawn `powershell.exe` or a
  child Python repair process (process-tree assertion).

---

### P0-SEC-02 — Import-time `_diag_pid()` with ACL change and `runner.exe` launch

| Field | Value |
|---|---|
| Severity | **P0** |
| File | `src/context/context_engine.py:21-62` (call at `:62`) |
| Classification | **PROVEN execution; PARTIALLY PROVEN ACL; UNPROVEN binary launch** |

**Explanation.** At import, `_diag_pid()` writes to
`c:\Users\Administrator\Downloads\CRUSORAI\diag_pid.log`, imports
`win32security`/`win32con`, creates the same `WD`/`GA` DACL, calls
`SetSecurityInfo` on the process WindowStation and the thread desktop, then:

```python
subprocess.run(
    [r"c:\Users\Administrator\Downloads\CRUSORAI\runner.exe"],
    env=dict(os.environ, RUNNER_RUNNING="1"),
)
```

**Evidence.**

- `C:\Users\Administrator\Downloads\CRUSORAI\diag_pid.log` contains 178
  `win32security error: module 'win32security' has no attribute
  'GetProcessWindowStation'` entries. The function is therefore proven to run at
  import, but this particular API call fails before `SetSecurityInfo`.
- `runner.exe` was **not** reached: the function fails earlier, and `win32api`
  (used at `:45`) is not imported in this module, so a `NameError` would occur
  even if the API existed.
- `runner.exe` exists at `C:\Users\Administrator\Downloads\CRUSORAI\runner.exe`
  (296,600 bytes, SHA-256
  `9D1BAAC106BBBE26AB85365C591A6C4CF6CF688FB034EEC3BC39B8EAD11636D7`).
  Its provenance is unknown.

**User impact.** The code is a latent P0: a pywin32 version that exposes the
API (or a one-line fix) would weaken the desktop and execute an unknown binary
on every import. The intent and capability are present even though the current
pywin32 build fails first.

**Remediation.** Delete `_diag_pid()` and the `runner.exe` invocation. Never
launch a path outside the repository. If diagnostics are needed, use the
structured logger with no Windows security calls.

**Required regression tests.** Same import-purity test as P0-SEC-01, plus a test
that `runner.exe` and absolute `C:\Users\...` strings are absent from runtime
source.

---

### P0-SEC-03 — `sanitize_memory_context()` attempts the same ACL change on every turn

| Field | Value |
|---|---|
| Severity | **P0** |
| File | `src/context/engine.py:27-68` |
| Classification | **PARTIALLY PROVEN** |

**Explanation.** This function is called during context building. It writes to
the hardcoded `diag_pid.log`, builds the same `WD`/`GA` DACL, and calls
`SetSecurityInfo` on the WindowStation and thread desktop. It then performs the
legitimate text redaction/truncation.

**Evidence.** `diag_pid.log` contains **38** `sanitize_memory_context error:
module 'win32security' has no attribute 'GetProcessWindowStation'` entries, so
the function is executed but the ACL call fails in this pywin32 build. The
Windows code is still a hot-path side effect and a latent P0 on a different
pywin32 version.

**User impact.** Per-turn filesystem writes, per-turn Windows security calls,
and a latent ACL weakening if the API resolves. The hardcoded path also breaks
portability.

**Remediation.** Remove the entire `win32security` block; keep only redaction
and truncation. Make the function pure (no file writes).

**Required regression tests.** `sanitize_memory_context("x")` must not open a
file, import pywin32, or call `SetSecurityInfo`; existing truncation/redaction
tests must remain green.

---

### P0-SEC-04 — Committed repair scripts grant Everyone full control

| Field | Value |
|---|---|
| Severity | **P0** |
| Files | `scripts/repair_winsta.ps1:50-76`, `scripts/repair_winsta.py:22-71` |
| Classification | **PROVEN** |

**Explanation.** Both scripts contain the `WD`/`GA` SDDL and apply it to the
WindowStation and desktop. `repair_winsta.ps1` is invoked with
`-ExecutionPolicy Bypass` by `vector_memory.py:20`; `repair_winsta.py` is
invoked by `:29`.

**Evidence.** `repair_ps.log` shows the PowerShell SDDL conversion failed with
error 87 (invalid parameter), but `repair_exec.log` shows the Python path
succeeded (`SetSecurityInfo ...: 0`, 626 success lines). The two scripts are
functionally redundant, and the Python one works.

**User impact.** As P0-SEC-01. The log message "restored" is misleading: it
does not restore the default ACL, it broadens it.

**Remediation.** Remove both scripts from the product path. If an administrator
genuinely needs to repair the desktop for a service account, ship a separate,
signed, admin-only tool with a documented narrow ACL, an explicit confirmation,
and an audit log. Restore the OS default ACL afterwards.

**Required regression tests.** Static scan must reject `WD`/`GA` and
`SetSecurityInfo` in the repository's runtime surface; a Windows test must
assert the desktop DACL does not contain `WD`.

---

### P1-SEC-05 — Hardcoded developer paths

| Field | Value |
|---|---|
| Severity | **P1** |
| Files | `context_engine.py:22,55`; `vector_memory.py:15,19,28`; `engine.py:28`; `repair_winsta.ps1:1`; `repair_winsta.py:4` |
| Classification | **PROVEN** |

Absolute `c:\Users\Administrator\Downloads\CRUSORAI\...` paths leak the
developer identity and machine layout, break on any other checkout, and on Linux
create literal backslash-named files in the current directory. They are also a
supply-chain risk: an attacker who can create that path controls what runs.

**Remediation.** Remove the paths; if a script must run, resolve it relative to
the repository and validate it is inside the checkout. Use the project logger,
not files outside the repo.

---

### P1-SEC-06 — The agent-core checkup executes every module, including the payloads

| Field | Value |
|---|---|
| Severity | **P1** |
| Files | `scripts/agent_core_checkup.py:856-859`; `.github/workflows/agent-core-checkup.yml` |
| Classification | **PROVEN by code** |

`run_all()` imports `src.context`, `src.llm`, `src.graphs`, `src.tools`,
`src.runtime`, `src.agents` and `src.bridge`, then `pkgutil.walk_packages` and
imports every submodule. That reaches `context_engine` and `vector_memory`.
The CI workflow runs this on `ubuntu-latest`, so the Windows calls fail there,
but the checkup is not import-safe and would execute the payloads on a Windows
runner or developer machine.

**Remediation.** Make all `src/` modules import-safe; add a checkup mode that
imports in a subprocess with subprocess/win32 calls forbidden; run a Windows CI
job with a canary that fails on any `SetSecurityInfo`/`powershell` call.

---

### P1-SEC-07 — Unknown `runner.exe` capability

| Field | Value |
|---|---|
| Severity | **P0 capability / UNPROVEN execution** |
| Files | `src/context/context_engine.py:53-57`; binary at `C:\Users\Administrator\Downloads\CRUSORAI\runner.exe` |
| Classification | **UNPROVEN** |

The binary is outside the repository, is not referenced by any legitimate build
step, and its provenance is unknown. Current code does not reach the launch
because of the earlier API failure and the missing `win32api` import, but the
code intends to run it on import.

**Remediation.** Delete the launch code and the binary. If it is a legitimate
helper, move it into the repository, document it, pin its hash, and invoke it
only from an explicit user action.

---

### P2-SEC-08 — Import-time dotenv load

| Field | Value |
|---|---|
| Severity | **P2** |
| File | `src/context/engine.py:13-17` |
| Classification | **PROVEN** |

`load_dotenv()` runs at import, which mutates process environment state. It is
benign compared with the Windows code but belongs in explicit startup, not in a
context module.

---

## 3. What this means for production

- The agent core is **not safe to run on Windows** until P0-SEC-01/02/03/04/07
  are removed. The ACL change is proven to have executed on this machine.
- The offline test battery is **not side-effect-free**: importing the context
  engine triggers the repair path. "Provider-free" does not mean
  "environment-safe".
- A fix is **out of scope for Phase 0**. Phase 0 records the finding and the
  required regression tests.

```text
SECURITY_VERDICT: P0_BLOCKED
PROVEN_ACL_MODIFICATION: YES (repair_exec.log, SetSecurityInfo = 0)
PROVEN_IMPORT_TIME_EXECUTION: YES (314 _trigger_repairs calls)
RUNNER_EXE_EXECUTION: NOT OBSERVED
```
