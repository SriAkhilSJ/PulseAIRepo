# LIVE12 Run — Abort Report (Launch Failure)

**Run ID:** `p0_6_5_20261108T090012_ccd13cd7`
**Evidence directory:** `diagnostics/live12_run_20261108_085953/`
**Harness verdict:** `P0.6.6_LIVE_FAILED`
**Acceptance verdict:** `LIVE12_INCONCLUSIVE`
**Provider calls:** 0
**Provider spend:** ₹0.00
**Electron workbench sessions:** 0
**Submissions:** 0
**Task turns:** 0

---

## 1. What happened

The harness started, created an isolated workspace, recorded the git identity,
and launched `desktop/vscode/.build/electron/CrusorAI.exe` on a loopback CDP
port. The Electron **main process crashed during startup**, before the
workbench, bridge, or any session existed. CDP `/json/version` never answered
and the harness aborted after its launch timeout.

The app did emit `DevTools listening on ws://127.0.0.1:59089/...`, so the
Electron binary itself started; the app main process then threw.

## 2. Root cause

`desktop/vscode/node_modules/@vscode/policy-watcher` had no native binding:

```text
Error: Could not locate the bindings file. Tried:
  .../node_modules/@vscode/policy-watcher/build/Release/vscode-policy-watcher.node
  ...
    at bindings (.../bindings.js:126:9)
    at Object.<anonymous> (.../@vscode/policy-watcher/index.js:6:44)
    ...
    at async NativePolicyService._updatePolicyDefinitions
    at async ConfigurationService.initialize
    at async CodeMain.initServices
    at async CodeMain.startup
```

`npm ci --ignore-scripts` (used earlier to restore the TypeScript/Electron
dependency tree after the VS 18 / node-gyp mismatch) installed the JS packages
but skipped **all** native builds. The previous live run (Live11) used a tree
where those binaries existed. No source or compiled `out` file was involved.

## 3. Full evidence of "nothing ran"

| Check | Result |
|---|---|
| `CRUSORAI_HOME` created | no (`home/` absent) |
| `sessions.db` | none |
| submission ledger | none |
| bridge process / `[bridge]` log lines | none |
| `provider_invocations.jsonl` | empty, file created by this audit |
| FinOps state / reservations | none |
| screenshots | none |
| task artifacts | none |
| test / smoke tests | not run |
| historical `res_d7990e4d3dc3` | unchanged, `in_flight`, ₹0.167204 |

The run never reached the UI, so there was no session, no submission gesture,
no provider reservation, and no spend. The ₹1.00 authorization was **not
consumed by a task execution**.

## 4. Environment repair (offline, no spend)

The missing native modules were restored from the locally installed
Microsoft VS Code (`a717861c07`), whose binaries use N-API and load under
Electron 42's Node 24:

| Module | Binary restored | `require()` |
|---|---|---|
| `@vscode/policy-watcher` | `build/Release/vscode-policy-watcher.node` | OK |
| `@vscode/sqlite3` | `build/Release/vscode-sqlite3.node` | OK |
| `@vscode/spdlog` | `build/Release/spdlog.node` | OK |
| `@vscode/deviceid` | `build/Release/windows.node` | OK |
| `@vscode/windows-registry` | `build/Release/winregistry.node` | OK |
| `@vscode/windows-mutex` | `build/Release/CreateMutex.node` | OK |
| `@vscode/windows-ca-certs` | `build/Release/crypt32.node` | OK |
| `@vscode/native-watchdog` | `build/Release/watchdog.node` | OK |

`vsda` was not installed as a package; only its `.node` was copied, so
`require('vsda')` still fails. It is used by the sign service / extension host,
not the early main-process path that crashed. This remains an open risk for the
next launch and is not claimed as fixed.

No file under `src/`, `desktop/vscode/out/`, or `desktop/vscode/.build/electron/`
was modified. `SOURCES_HASH`, the renderer, the worker and `CrusorAI.exe` remain
byte-identical to the qualified provenance.

## 5. Why the acceptance did not continue

The procedure states: on abort, stop; do not rerun; do not start another
session; do not automatically retry. That rule was followed. This report is the
result of the authorized attempt, not a task result.

## 6. What is required to attempt the first real session

A new explicit authorization after the environment repair. The next attempt is
the first attempt that can actually create a session and submit the prompt; it
has not happened yet.

## 7. Verdict

```text
LIVE12_INCONCLUSIVE
```

The experiment cannot establish a trustworthy exactly-once or financial result
because no Electron workbench session, submission, or provider call occurred.
No claim is made about the Live11 repairs, visual tool-card rendering, or
P0.6.9. The historical reservation is untouched.
