# P0.6.4 — Desktop Observability & Acceptance Harness

- **Run ID:** `p0_6_4_20261107T124415_7853425d`
- **Evidence dir:** `C:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\diagnostics\p0_6_4`
- **Git HEAD:** `6bfb6d6d` on `feat/prompt-cache-stabilization`
- **Workspace id:** `ws_ae3a00a313dd140c`
- **Provider dispatches this run:** 0

## Electron lane

- launched: `True`  pid: `21804`
- renderer belongs to Crusor: `None`
- composer `textarea.crusorai-composer-input` count: `None` visible: `None` enabled: `None`
- screenshots: (none)
- unhandled errors: 0 / rejections: 0 / console errors: 0

## Bridge lane

- handshake: `crusorai` protocol `2` version `0.2.0-runtime`
- session id: `session-30785f5828574e9eae359cf7cbd703e3`
- exit code: `0`
- validation passed: `True`
- compiled workbench stale vs sources: `True` — [bridge] DESKTOP WORKBENCH STALE: the shipped panel was emitted from DIFFERENT crusorai sources than this checkout (sha256 e7f9f650588c… != 6d3594d3ab3c…) — the Agent pane will render OLD cards no matter what the engine 

## Governance

- pricing verified: `True` (in $0.05/1M, out $0.20/1M)
- max request cost: INR `0.038657` / USD `0.000418` — fits ₹5.0: `True`
- retry posture: `{'provider': 'custom', 'model': 'z-ai/glm-5.3-flash', 'retry_proxy_class': 'RetryLLMProxy', 'max_attempts': 5, 'inner_client_class': 'ReasoningAwareOpenAI', 'max_retries': 0, 'failover': False}`
- Invariant 7 maintained: `True` (drift: [], undeclared: [])

## Acceptance criteria (P0.6.4 = observability only)

| Criterion | Evidence |
| --- | --- |
| 1. real Electron executable running | PARTIALLY VERIFIED |
| 2. actual CDP connection to renderer | NOT VERIFIED |
| 3. composer textarea.crusorai-composer-input located | NOT VERIFIED |
| 4. prompt entered through composer | NOT VERIFIED |
| 5. UI submission action triggered | NOT VERIFIED |
| 6. worker + bridge handled same session | PARTIALLY VERIFIED |
| 7. provider request belongs to same turn | NOT VERIFIED |
| 8. artifact belongs to same execution | NOT VERIFIED |
| 9. final response rendered in panel | NOT VERIFIED |
| 10. renderer console: zero unhandled exceptions | NOT VERIFIED |

## Errors

- desktop lane: LaunchError: desktop app exited with code 1 before serving a debugging endpoint (requested port 9333, stderr=['[main 2026-11-07T20:44:24.696Z] TypeError: this._win.webContents.session.setProxy is not a function', '[main 2026-11-07T20:44:24.698Z] [uncaught exception in main]: AggregateError: Encountered errors while disposing of store', '[main 2026-11-07T20:44:24.698Z] AggregateError: Encountered errors while disposing of store', '[main 2026-11-07T20:44:24.698Z] [uncaught exception in main]: TypeError: electron.ipcMain.removeListener is not a function', '[main 2026-11-07T20:44:24.698Z] TypeError: electron.ipcMain.removeListener is not a function', '[main 2026-11-07T20:44:24.700Z] AggregateError: Encountered errors while disposing of store', '    TypeError: electron.ipcMain.removeListener is not a function', '    TypeError: electron.ipcMain.removeListener is not a function', '    TypeError: electron.ipcMain.removeListener is not a function', 'Error: Trying to add a disposable to a DisposableMap that has already been disposed of. The added object will be leaked!'])
