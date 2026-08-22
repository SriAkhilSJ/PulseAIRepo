# CDP Test Guide — Agent-Friendly, Copy-Paste Ready

**Purpose:** Run PulseAI CDP acceptance tests in <30 min. Zero analysis needed — just copy-paste commands.

## Quick Start (30 seconds)

```bash
# 1. Verify Python works
D:/pulseAIagent/PulseAIRepo/.venv/Scripts/python.exe -c "import langchain_core; print('ok')"

# 2. Launch app with CDP
cd PulseAIRepo/desktop/vscode && cmd.exe //c "set PULSEAI_PYTHON_PATH=D:\\pulseAIagent\\PulseAIRepo\\.venv\\Scripts\\python.exe&&set PULSEAI_ENGINE_ROOT=D:\\pulseAIagent\\PulseAIRepo&&scripts\\code.bat D:\\pulseAIagent\\PulseAIRepo --remote-debugging-port=9222" &

# 3. Wait 15s, verify CDP
sleep 15 && curl -s http://localhost:9222/json/version | head -2

# 4. Run tests (from CDP_test dir)
cd D:/pulseAIagent/pulse-res/cancel-session-artifacts/CDP_test && node r03_final.js
```

## Prerequisites

| Item | Value | Verify |
|------|-------|--------|
| Python venv | `D:\pulseAIagent\PulseAIRepo\.venv` | `python.exe -c "import langchain_core; print('ok')"` |
| Node.js | v24+ | `node --version` |
| ws module | `D:\pulseAIagent\pulse-res\cancel-session-artifacts\CDP_test\node_modules\ws` | `ls node_modules/ws/package.json` |
| PulseAI.exe | `desktop/vscode/.build/electron/PulseAI.exe` | `ls -la` |
| CDP port | 9222 | `curl -s http://localhost:9222/json/version` |

## Test Scripts (copy-paste ready)

All scripts are in `D:\pulseAIagent\pulse-res\cancel-session-artifacts\CDP_test\`:

| Script | What it tests | Duration |
|--------|--------------|----------|
| `r03_final.js` | Criteria 2-6 (protocol, tiny turn, cancellation, shutdown) | ~60s |
| `r03_large_v3.js` | Criterion 4 (20k-entry workspace turn) | ~30s |
| `r03_simple_test.js` | Quick diagnostic (state check) | ~10s |

### Run all tests:
```bash
cd D:/pulseAIagent/pulse-res/cancel-session-artifacts/CDP_test

# Step 1: Trust folder (user must click "Yes, I trust" in app)
# Step 2: Run main test
node r03_final.js

# Step 3: Run large workspace test
node r03_large_v3.js
```

## CDP Cheat Sheet

### Connect to app
```javascript
const WebSocket = require('ws');
const resp = await fetch('http://localhost:9222/json');
const targets = await resp.json();
const page = targets.find(t => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
```

### Key CDP commands
```javascript
// Screenshot
const r = await send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync('shot.png', Buffer.from(r.result.data, 'base64'));

// Run JS
const val = await send('Runtime.evaluate', {
  expression: 'document.body.innerText.includes("Pulse ready")',
  returnByValue: true
});

// Type text (fast, no hang)
await send('Input.insertText', { text: 'your prompt here' });

// Press Enter
await send('Input.dispatchKeyEvent', {
  type: 'keyDown', key: 'Enter',
  windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13
});

// Click at coordinates
await send('Input.dispatchMouseEvent', {
  type: 'mousePressed', x: 1131, y: 510,
  button: 'left', clickCount: 1
});
```

### Find textarea (always works)
```javascript
const ta = await ev(`(() => {
  const t = document.querySelector("textarea.pulseai-composer-input");
  if (!t) return null;
  const r = t.getBoundingClientRect();
  return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
})()`);
const {x, y} = JSON.parse(ta);
await clickAt(x, y);
```

### Find stop button (always works)
```javascript
const stop = await ev(`(() => {
  const el = document.querySelector('[class*="stop"]');
  if (el) { const r = el.getBoundingClientRect(); return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2}); }
  return null;
})()`);
```

### Poll for text (with timeout)
```javascript
async function poll(needle, maxMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    const txt = await ev('document.body.innerText');
    if (txt && txt.includes(needle)) return { found: true, ms: Date.now() - t0 };
    await new Promise(r => setTimeout(r, 200));
  }
  return { found: false, ms: Date.now() - t0 };
}
```

## Pitfalls (Learned the Hard Way)

1. **No textarea?** → App may be in restricted mode. Wait 10s for workspace to load, or trust folder via `F1` → `Workspaces: Trust`
2. **`Input.insertText` vs char loop** → ALWAYS use `insertText`. Char-by-char `dispatchKeyEvent` hangs.
3. **`ws` module not found** → Run from `CDP_test/` dir where `node_modules/ws` exists
4. **Screenshot timeout** → Page may be navigating. Retry after 2s.
5. **"Pulse ready" not showing** → Wait 10s after launch. Large workspaces take longer to load.
6. **Stop button not found** → Use `[class*="stop"]` selector. Coordinates shift between layouts.
7. **`PULSEAI_PYTHON_PATH`** → MUST set before launch. Wrong python = `ModuleNotFoundError langchain_core`.

## Build Commands

```bash
# Full bundle (recommended, ~2min)
cd PulseAIRepo/desktop/vscode
node --experimental-strip-types --max-old-space-size=8192 build/next/index.ts bundle --nls --out out-vscode

# Compile only (~8min)
node --experimental-strip-types --max-old-space-size=8192 ./node_modules/gulp/bin/gulp.js compile-build-without-mangling

# Full gulp build (may fail on NLS step)
node --experimental-strip-types --max-old-space-size=8192 ./node_modules/gulp/bin/gulp.js vscode-win32-x64
```

## Generate 20k Workspace

```bash
cd PulseAIRepo
python -c "
from benchmarks.pulse_reliability_v1.fixtures import load_fixture_manifest, build_fixture
from pathlib import Path
manifest = load_fixture_manifest('benchmarks/pulse_reliability_v1/fixtures.json')
spec = next(f for f in manifest.fixtures if f.task_id == 'PBR-004')
build_fixture(spec, Path('D:/pulse-res/large-20k'))
print('Done: 20,001 files')
"
```

## Evidence Layout

```
D:\pulse-res\r03-<timestamp>\
├── R03_REPORT.md          # Final report
├── provenance.txt          # Commit + blob hashes
├── build.log               # Build output
├── *.png                   # Screenshots
├── r03_final_results.json  # Machine-readable results
└── r04_large_result.json   # Large workspace results
```

## Environment Variables

```bash
export PULSEAI_PYTHON_PATH='D:/pulseAIagent/PulseAIRepo/.venv/Scripts/python.exe'
export PULSEAI_ENGINE_ROOT='D:/pulseAIagent/PulseAIRepo'
```

## Shutdown Cleanup

```bash
taskkill //F //IM PulseAI.exe
sleep 3
# Verify: 0 PulseAI, 0 python, ports 9222/5999 free
```
