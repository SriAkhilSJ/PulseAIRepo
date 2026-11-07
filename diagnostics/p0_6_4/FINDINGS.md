# P0.6.4 — Desktop Readiness Findings

**Authoritative run:** `p0_6_4_20261107T131213_1edc357d`
**Evidence:** `diagnostics/p0_6_4/` (`run.json`, `evidence.jsonl`, `evidence.json`, `report.md`, `logs/`, `screenshots/`, `user-data/`)
**Mode:** offline only — **0 provider dispatches**, **0 paid frames**, no prompt submitted.
**Git:** `6bfb6d6d` on `feat/prompt-cache-stabilization`; `desktop/vscode` worktree clean (0 changes).

## Result

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Real Electron executable running | **VERIFIED** | `electron.launch`: `.build/electron/CrusorAI.exe`, sha256, pid, full argv, isolated profile; `electron.identity` |
| 2 | Actual CDP connection to renderer | **VERIFIED** | `cdp.version` (Chrome/148.0.7778.280, protocol 1.3), `cdp.target` (loopback ws origin), `electron.debug_port` (`loopback_only: true`) |
| 3 | Composer `textarea.crusorai-composer-input` located | **VERIFIED** | `composer.inspect`: count 1, visible, enabled, placeholder "Ask anything, / for commands, @ for context…", rect 278×67 |
| 4 | Prompt entered through composer | NOT VERIFIED | Out of scope for P0.6.4 (no prompt may be submitted) |
| 5 | UI submission triggered | NOT VERIFIED | Out of scope for P0.6.4 |
| 6 | Worker + bridge on the same session | **VERIFIED** | `worker.process_tree` (4 Python descendants under the app pid), `worker.launch`, `bridge.handshake`, `bridge.session`, `bridge.frames`, `bridge.shutdown` |
| 7 | Provider request belongs to same turn | NOT VERIFIED | No turn was run |
| 8 | Artifact belongs to same execution | NOT VERIFIED | No turn was run |
| 9 | Final response rendered in panel | NOT VERIFIED | No turn was run |
| 10 | Renderer console: zero unhandled exceptions | **VERIFIED** | `renderer.console`: 0 `error`, 0 `unhandledrejection`, 0 `console.error` |

Real renderer identity at capture:

```
title: crusor_p0_6_4_workspace_w6jgrvp9 - CrusorAI IDE Dev
url:   vscode-file://vscode-app/.../out/vs/code/electron-browser/workbench/workbench-dev.html
hasWorkbench: true   isElectron: true   UA: crusorai-dev/1.134.0 … Electron/42.8.1
```

Screenshots: `screenshots/renderer-workbench.png`, `screenshots/renderer-composer.png`.

## What blocked the desktop lane, and what fixed it

### B1 (FIXED) — the app booted with an Electron stub, so no renderer ever existed

The gitignored build artifact `desktop/vscode/out/main.js` had been hand-patched to
start with:

```js
import electronModule from "electron";
const electron = (…keys>0…) ? electronModule : (globalThis.electron || {});
const app = electron.app || { /* no-op stubs */ };
const protocol = electron.protocol || { registerSchemesAsPrivileged: () => {} };
```

`src/main.ts` — the source of truth — just does
`import { app, protocol, crashReporter, Menu, contentTracing } from 'electron';`.

Symptoms that traced back to this single divergence:

* `protocol.registerSchemesAsPrivileged` became a no-op → `vscode-file://` was
  never registered → `window#load` was attempted but Chromium produced **no
  renderer process** and `/json/list` stayed `[]` (verified with
  `Target.getTargets` on the browser endpoint: empty).
* `webContents.session.setProxy is not a function` crashed the `BrowserWindow`
  constructor (exit code 1) whenever `NO_PROXY`/`HTTP(S)_PROXY` was present,
  because `windowImpl.onConfigurationUpdated()` enters its proxy branch.
* `ipcMain.removeListener is not a function` during shutdown.

Repair applied (no source file touched): `out/` regenerated from `src/` with
`npm run transpile-client` (transpile-only, 24 s, 8 324 files). Result: the
workbench window rendered, CDP attached, the Crusor panel was already open and
`textarea.crusorai-composer-input` was found — criteria 1, 2, 3, 6 and 10 went
from NOT VERIFIED to VERIFIED. The hand-patched artifact was replaced by the
regenerated build (`out/` is gitignored and is not part of the repository);
its stub header is quoted verbatim above.

The harness also scrubs inherited `ELECTRON_RUN_AS_NODE` / VS Code IPC vars and
proxy variables for the child (documented in
`desktop_launcher.build_launch_environment`), because both were observed to
prevent a usable window on this machine.

### B2 (OPEN) — the build forces CDP on port 9222, ignoring the requested port

| Launch | Requested | Actually bound (DevToolsActivePort) |
| --- | --- | --- |
| harness run | 9333 | **9222** (`port_overridden: true`) |
| probe | 9444 | **9222** |
| probe | *no switch* | **9222** |
| stock `electron.exe` 42.8.1 | 9333 | 9333 |

Loopback-only is asserted for the real port, so the harness is safe; but an
always-on debugger port is a security concern and should be removed or
parameterised. No `9222` literal exists in tracked sources, compiled `out/` JS,
`product.json`, `argv.json`, or the binary strings — the origin is still
unidentified, so it is recorded as a build-level default rather than guessed at.

### B3 (OPEN, reviewable) — the committed Agent panel is stale vs its sources

```
[bridge] DESKTOP WORKBENCH STALE: the shipped panel was emitted from DIFFERENT
crusorai sources (sha256 e7f9f650588c… != 6d3594d3ab3c…)
```

Recomputed independently: current `6d3594d3ab3ce2a5e8c4bd6695bcce3a177bb0bafb0c7091649c8a622c462f11`,
shipped `e7f9f650588cfa04ce8598e401c291baa6949c29daf04a0b94e5fa1d624b0bad`.
Repair is `node scripts/emit-crusorai-bundle.mjs` in `desktop/vscode`, which
rewrites ~594 **tracked** files under `out/vs/workbench/contrib/crusorai/`.
That is a reviewable change of its own, so it was **not** applied as a side
effect of an observation run (the tree is clean).

### Observation — default retry posture is 5 attempts

`provider.retry_posture`: `RetryLLMProxy._max_attempts = 5`, inner
`max_retries = 0`, no failover. A live turn must force `_max_attempts = 1`
(as P0.5.2 did) or one transient error becomes five paid dispatches.

### Observation — one pre-existing renderer error (upstream, not Crusor)

Late in the run the renderer logged:
`Unable to create workbench contribution 'chat.contextContributions' … chatSessionRo…`.
It is a VS Code chat-contribution wiring issue in this fork, not a Crusor AI
failure, and it is not an unhandled exception (captured, counted, reported).

## What this changes about P0.6.2

P0.6.2's `PASS` came from a Python harness calling `ModelExecutionAdapter`
directly; P0.6.3 correctly classified the desktop criteria as unverified. This
run supplies the missing link: the real window, the real workbench page, the
real composer, and the real worker/bridge — all captured from the running
application, with zero provider calls.

## Next steps (each separately reviewable)

1. Remove or parameterise B2's hardcoded 9222 endpoint.
2. Re-emit the panel bundle for B3 and confirm `SOURCES_HASH` matches.
3. Run the live desktop turn (P0.6.5) through the composer with
   `_max_attempts = 1`, ≤5 dispatches, ₹5 cap; the correlation seams
   (`ui.submit` → `provider.dispatch` → `provider.usage_receipt` →
   `finops.snapshot` → `mutation.receipt` → `render.response`) are already wired.
