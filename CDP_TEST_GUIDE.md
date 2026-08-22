# CDP Test Guide — Test the Fork Without Analyzing It

**Purpose:** Run the full PulseAI cancellation/desktop validation in ~15 min, no code-reading. This guide encodes the exact commands, ports, coordinates, and pitfalls that cost hours of analysis.

## 0. TL;DR Commands

```powershell
Set-Location D:\pulseAIagent\PulseAIRepo

# Python — ALWAYS use this (D:\ venv is symlink to C:\venvs, fixes Access is denied)
D:\pulseAIagent\PulseAIRepo\.venv\Scripts\python.exe -c "import langchain_core; print('ok')"
D:\pulseAIagent\PulseAIRepo\.venv\Scripts\python.exe -m pytest -q --ignore=desktop  # 813 collected

# Desktop + CDP
$env:PULSEAI_PYTHON_PATH='D:\pulseAIagent\PulseAIRepo\.venv\Scripts\python.exe'
$env:PULSEAI_ENGINE_ROOT='D:\pulseAIagent\PulseAIRepo'
Start-Process cmd.exe "/c cd /d D:\pulseAIagent\PulseAIRepo\desktop\vscode && scripts\code.bat D:\pulseAIagent\PulseAIRepo --remote-debugging-port=9222"
# Wait 10s, then test:
Test-NetConnection localhost -Port 9222  # must be True
```

## 1. Environment (saves 1h)

- **Venv location:** `D:\pulseAIagent\PulseAIRepo\.venv` is a **symlink** to `C:\venvs\PulseAIRepo-venv` (fixes `WinError 5 Access is denied` from WDAC blocking `D:\`). Do NOT use `C:\...\uv\python\...\python.exe` directly — lacks `langchain_core`.
- **If symlink broken:** `cmd /c "mklink /D D:\pulseAIagent\PulseAIRepo\.venv C:\venvs\PulseAIRepo-venv"`
- **Verify:** `D:\...\python.exe -m pytest --version` → `pytest 9.1.1`, `D:\...\python.exe -c "import sys; print(sys.executable)"` → `D:\...`
- **pytest config:** `pytest.ini` has `pythonpath=.` so `from src...` works only from repo root. Ignore `desktop/` fixtures: `--ignore=desktop` avoids `mmath` import error (814 → 813).
- **Full suite vs targeted:** Targeted 46 tests are accepted; broader suites have pre-existing `PermissionError` on `D:\` shell spawns — compare baseline `0285836c` before calling regression.

## 2. Desktop Build Provenance (saves 45m)

Before CDP, prove the desktop loads `cd4a2cab`:

```powershell
git rev-parse HEAD  # must be cd4a2cab362339e77f9d1b0ddc35a51dc8fe2861
git hash-object src/bridge/__main__.py; git rev-parse HEAD:src/bridge/__main__.py  # must match (same for chat_graph.py, factory.py, turn_control.py)
Get-Item desktop/vscode/.build/electron/PulseAI.exe | Select LastWriteTime,Length
Get-CimInstance Win32_Process | Where CommandLine -like "*src.bridge*"  # should show D:\...\python.exe -m src.bridge, Parent=PulseAI
```

Runtime files == HEAD blob hashes (`05caf735`, `80d6ad61`, `2479cfe6`, `1f99c233`). Electron binary timestamp `8/16 11:23 PM` is older than `cd4a2cab` but Python engine is loaded from `PULSEAI_ENGINE_ROOT` (working tree), so hash match is sufficient — do NOT rely on electron build alone.

## 3. CDP Harness (saves 2h)

**CDP basics:**
- Port: `9222` via `scripts\code.bat --remote-debugging-port=9222` (must use `Start-Process cmd.exe` so shell survives tool kills)
- List targets: `http://localhost:9222/json` → `webSocketDebuggerUrl`
- Connect: `ws` module at `D:\pulseAIagent\pulse-res\cancel-session-artifacts\CDP_test\node_modules\ws` (use that dir as cwd)
- **Screenshot:** `Page.captureScreenshot` → `r.result.data` (NOT `r.data`) — `Buffer.from(r.result.data,'base64')`
- **JS:** `Runtime.evaluate` with `returnByValue:true`
- **Input:** `Input.insertText` (fast) or `dispatchKeyEvent` char loop (slow, hangs), `Input.dispatchKeyEvent` for `Enter` (13), `F1` (112), `Escape` (27), `Input.dispatchMouseEvent` for clicks

**Coordinates (from `D:\pulse-res\cdp-shots\`):**
- Textarea: `(1161, 554)` centered, also `document.querySelector('textarea')` or `.pulse-ws-large textarea`
- Send button: `(1310, 602)`
- Stop button: `(1273, 602)` via `[class*="stop"]` (or `[class*="cancel"]`, `button[title*="Stop"]`). Probe via `document.querySelector('[class*="stop"]')?.getBoundingClientRect()`

**Pitfalls that break tests:**
1. No folder opened → `Engine stopped` + `Open a folder to start a Pulse session` — must launch with `D:\pulseAIagent\PulseAIRepo` arg or `File: Open Folder` via `F1` → `Open Folder`
2. Engine crash `ModuleNotFoundError langchain_core` → wrong python (Python311) — set `PULSEAI_PYTHON_PATH` before launch
3. Typing char-by-char hangs — use `Input.insertText` not loop
4. `ws` not found — run `node script.js` from `CDP_test/` where `node_modules/ws` exists
5. 30s wait loops without `awaitPromise:true` miss `Run cancelled`

## 4. Cancellation Trial Protocol (Part 5, saves 1h)

Use new dir per run: `D:\pulse-res\cancel-session-artifacts\cd4a2cab-rerun-<timestamp>\` (never copy old screenshots).

**Steps per trial (loop 3×):**
1. `F1` → `PulseAI: Focus Agent` → `Enter` (wait 2s, screenshot `panel_open.png` → check `Pulse ready`)
2. Focus textarea via `Runtime.evaluate` click at `(1161,554)` → `Input.insertText` with prompt `Write fibonacci recursively...` → `Enter`
3. Poll body `innerText` every 100 ms for `Thinking|Generating|fibonacci` (max 30s) → record `provider_start` monotonic time
4. Find Stop via `[class*="stop"]` → `mousePressed/Released` → record `stop_click` time
5. Poll every 100 ms for `Run cancelled` or `Pulse ready` (max 15s) → record `cancel_ack`, `turn_done`, `dom_cancel`
6. Compute latencies: `stop→ack`, `stop→terminal`, `stop→DOM` (all must be <5s, target <2s, 4868 ms prior had 132 ms margin)
7. Prove counters ==0: `requests_started_after_stop`, `retries_started_after_stop`, `failovers_started_after_stop`, `tool_starts_after_stop`, `mutations_after_stop` (query `document.body.innerText` or bridge `session_info`)

**Also rerun:** same-session next-turn recovery (prompt again without restart), concurrent A/B isolation (two sessions, cancel A, B completes), shutdown (kill PulseAI → port 9222 closed, no orphan python).

Existing harness: `D:\pulseAIagent\pulse-res\cancel-session-artifacts\CDP_test\cancel_4.js` (fixed with `Input.insertText`, shows `trial1_05_after_stop.png` at `D:\pulse-res\cdp-shots\`)

## 5. Approval-Wait Test (Part 6)

Reach `tool.approval.request` → `safety_request` dock → verify `blocked` → `cancel` → require immediate `cancelled/denied`, no `tool_start`, abort registry empty. If untestable, report `approval-wait cancellation unverified` — do not claim complete.

## 6. Evidence Manifest (Part 7)

Create `D:\pulse-res\cancel-session-artifacts\cd4a2cab\evidence_manifest.txt` with HEAD SHA, build hashes, artifact SHA256, timestamps, commands+exit codes, all summaries, all CDP timestamps/counters. Do not update PR body yet.

## 7. Quick Validation (copy-paste)

```powershell
Set-Location D:\pulseAIagent\PulseAIRepo
$Evidence="D:\pulse-res\cancel-session-artifacts\cd4a2cab"; New-Item -ItemType Directory -Force $Evidence | Out-Null
$py="D:\pulseAIagent\PulseAIRepo\.venv\Scripts\python.exe"
& $py -m pytest -vv --tb=long src/tests/test_bridge.py 2>&1 | Out-File $Evidence\test_bridge.txt; "exit_code=$LASTEXITCODE" | Add-Content $Evidence\test_bridge.txt
# repeat for test_bridge_runtime_protocol, test_bridge_transport, test_bridge_workspace_routing, test_context_budget, test_git_context, test_desktop_workspace_boundary
git worktree add --detach D:\pulse-res\baseline-0285836 0285836c35dcd8d89611c94dd6c853d10ec3c358
Set-Location D:\pulse-res\baseline-0285836; & $py -m pytest -q src/tests/test_bridge_transport.py 2>&1 | Out-File D:\pulse-res\cancel-session-artifacts\baseline-0285836\test_bridge_transport.txt
Set-Location D:\pulseAIagent\PulseAIRepo; git worktree remove D:\pulse-res\baseline-0285836
```

**Current status:** Parts 1-4 done, Parts 5-7 pending fresh CDP rerun with correct build. Use this guide to redo in <30 min instead of 3h.
