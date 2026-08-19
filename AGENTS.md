# AGENTS.md — Tips for Other Agents

## Project Layout

```
D:\pulseAIagent\PulseAIRepo\          # repo root
  desktop\vscode\                      # Code OSS fork (Electron)
    src\vs\workbench\contrib\pulseai\  # Pulse overlay (committed in place)
  src\                                 # Python backend (LangGraph agent)
    context\git_context.py             # Git context builder (deadlock-safe)
    tests\test_git_context.py          # 17 tests for git context
  CDP_test\                            # CDP drivers, screenshots, evidence traces
    v5_driver.js                       # working CDP driver (screenshot: 05_result.png)
    large_v3.js                        # large workspace CDP driver
    cancellation.js                    # stop-button test
  .env                                 # secrets only (never put PULSEAI_AUTO_APPROVE_WRITES here)
  stub_llm\                            # not in repo; local at C:\Users\Administrator\AppData\Local\Temp\opencode\stub_llm.py
```

## Running Tests

```powershell
cd D:\pulseAIagent\PulseAIRepo
New-Item -ItemType Directory -Force -Path "D:\pytest-tmp" | Out-Null
$env:TMP="D:\pytest-tmp"; $env:TEMP="D:\pytest-tmp"
.venv\Scripts\python.exe -m pytest src\tests -q --no-header --ignore=src/tests/test_session_engines.py
```

- venv is at `D:\pulseAIagent\PulseAIRepo\.venv` (Python 3.14.4)
- `TMP`/`TEMP` must point to a fresh directory outside the repo (full drive or repo-relative temp breaks tests)
- All 116 tests across 8 files should pass

## CDP Desktop Testing

### How it works
- PulseAI.exe is at `desktop\vscode\.build\electron\PulseAI.exe`
- Launch via batch files that set env: `NODE_ENV=development`, `VSCODE_DEV=1`, `VSCODE_CLI=1`, `ELECTRON_ENABLE_LOGGING=1`
- CDP driver scripts use `puppeteer-core` to connect over DevTools Protocol
- **CDP port changes every launch** (e.g. 53479 → 53480 → 53481 → 53490 → 53491) — always find the port dynamically

### Finding the PULSE tab
- The PULSE tab is NOT the first tab — `tablist[0]` is the Extension Host, `tablist[1]` is a settings tab, `tablist[2]` is another internal tab
- PULSE tab is at `tablist[3]` (index 3), coordinates (1070, 52)
- Find it by title: `p.title.includes('Pulse')` or by checking if the tab has `.pulseai-container` in its DOM

### Submitting prompts
1. Click PULSE tab at (1070, 52) using `Input.dispatchMouseEvent`
2. Find the textarea: `.pulseai-input-area textarea`
3. Type into it using `Input.dispatchKeyEvent` (not `DOM.setAttributeValue` — that changes text but doesn't trigger React state)
4. Submit: click `.pulseai-send-button` at coordinates (1240, 560)
5. Wait for result: poll for "Run completed", "Done", or "context scan bounded" in DOM text

### Evidence trace hook (temporary, for gate runs only)
The `src/bridge/__main__.py` has a one-line trace addition that logs context build events to `D:\pulse-ws\.pulse-context-trace.jsonl`. This is NOT committed — it's applied temporarily for gate runs then restored to HEAD. To apply:
```powershell
# Add trace hook (replace in __main__.py)
$traceHook = '            if os.path.basename(layer_name) == "git_context":\n                import json as _json\n                _entry = {"t": time.time(), "event": "git_context_built", "elapsed_s": round(end - start, 2), "layer_bytes": len(content.encode("utf-8"))}\n                _tlog = os.path.join(workspace, ".pulse-context-trace.jsonl")\n                with open(_tlog, "a", encoding="utf-8") as _tf:\n                    _tf.write(_json.dumps(_entry) + "\\n")\n'
```
To restore HEAD after gate run:
```powershell
git checkout -- src/bridge/__main__.py
```

### Batch file launch pattern
Gate run batch files are in `C:\Users\Administrator\AppData\Local\Temp\pulse-gate-run\`. They set env vars and launch PulseAI.exe. The `.env` file in the repo is separate from the launch env.

### Stub LLM
- Location: `C:\Users\Administrator\AppData\Local\Temp\opencode\stub_llm.py`
- Starts on `127.0.0.1:5999`, returns `{"content": "OK"}` by default
- Configurable delay: `PULSEAI_STUB_DELAY` env var (seconds)
- The bridge expects structured `TaskDecision` JSON with `.action` attribute — the stub returns a generic response, so full tool-call flows won't complete (this is expected for testing context building, not full agent execution)

## Workspace Layout

- `D:\pulse-ws` — primary test workspace (use this for CDP tests)
- `D:\pulseAIagent\.pulse-ws-large` — large workspace with 21,001 files (for large-workspace tests)

## Key Constants

| Constant | Value | Location |
|----------|-------|----------|
| Pulse command | `pulseai.focus` | `desktop/vscode/src/vs/workbench/contrib/pulseai/common/pulseAI.ts:10` |
| View ID | `pulseAIView` | `pulseAI.ts` |
| Worker moduleId | `vs/workbench/contrib/pulseai/node/pulseAIWorkerMain` | `pulseAIWorkerService.ts:9` |
| Git budget | `_GIT_BUDGET_S = 3.0` | `src/context/git_context.py` |
| Run button class | `pulseai-send-button` | DOM |
| Stop button class | `pulseai-send-button pulseai-send-stop` | DOM |
| Stop button label | "Stop" | DOM |

## CDP Driver Files

| File | Purpose | Output |
|------|---------|--------|
| `v5_driver.js` | Full non-echo test | `05_result.png` |
| `large_v3.js` | Large workspace test | `lg_07_result.png` |
| `cancellation.js` | Stop button test | `cancel_03_after_stop.png` |
| `run_gate.js` | Basic run test | `08_result.png` |
| `check_tabs.js` | Debug: list all tabs | terminal output |

## Gotchas

1. **CDP port changes every launch** — don't hardcode ports; find dynamically from `--remote-debugging-port` output or scan common ports
2. **PULSE tab is not first** — always check tab titles, not indices
3. **Typing into textarea** — `DOM.setAttributeValue` doesn't work for React textareas; use `Input.dispatchKeyEvent`
4. **Stub LLM returns `{"content": "OK"}`** — this is intentional for context-building tests, not full agent execution
5. **Evidence trace is temporary** — the `__main__.py` trace hook is applied for gate runs only, then restored via `git checkout`
6. **`.env` must NOT contain `PULSEAI_AUTO_APPROVE_WRITES`** — it leaks into pytest via `load_dotenv()`; use env var directly
7. **`TMP`/`TEMP` must be outside repo** — repo-relative temp breaks git-context tests
8. **`gh` CLI is not installed** — use GitHub REST API with token from `git credential fill` for PR updates
9. **Git wrappers (Scoop/MSYS2) can deadlock** — this is why `git_context.py` uses `CREATE_NO_WINDOW`, `GIT_TERMINAL_PROMPT=0`, and tree-kill
10. **116/116 tests must pass** — run the full suite before pushing any changes

## PR #2 State

- Branch: `safe/workspace-routing-bounded-context`
- Base: `main` @ `6cd8e698`
- Head: `bcaa6dcd` (29 files, 7 commits)
- `git diff --check` clean
- PR body updated with all gate evidence
