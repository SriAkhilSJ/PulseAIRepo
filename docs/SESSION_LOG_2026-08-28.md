# PulseAI Desktop — Session Log (2026-08-28)

## What was done

### 1. Fixed 13 TypeScript compile errors

The new PulseAI features (inline completions, next-edit suggestions, enhanced renderer) introduced 13 TypeScript errors. All fixed:

| File | Error | Fix |
|---|---|---|
| `pulseAI.contribution.ts` | `inlineCompletionProvider`/`nextEditProvider` declared but never read | Removed unused imports and broken `registerSingleton` calls |
| `pulseAI.contribution.ts` | Property 'type' missing in `registerSingleton` | Removed the malformed singleton registrations (providers are not standalone services) |
| `pulseAIInlineCompletionProvider.ts` | `IModelContentChangeEvent` not exported from model | Rewrote provider to use simpler API without internal editor types |
| `pulseAIInlineCompletionProvider.ts` | `ProvideInlineCompletionItemsFunction`/`IInlineCompletionResult` unused/not found | Removed, replaced with direct engine communication |
| `pulseAIInlineCompletionProvider.ts` | Cannot find module `inlineCompletions.js`/`provideInlineCompletions.js` | Removed internal editor contrib imports, used plain engine bridge |
| `pulseAIInlineCompletionProvider.ts` | `getFullModelPosition` doesn't exist on TextModel | Replaced with standard `getPosition()` |
| `pulseAIInlineCompletionProvider.ts` | `lineCount` declared but never read | Removed |
| `pulseAINextEditProvider.ts` | `URI` declared but never read | Removed unused import |
| `pulseAIRenderer.ts` | `stateIcon` declared but never read | Removed unused variable |

### 2. Added "Open Agent Manager" button to Pulse Agent header

- Added a `pulseai-agent-header` section at the top of the Agent shell with a "Manager" button (organization icon).
- Button calls `host.openManager()` which opens the Pulse Manager in a **separate Electron window** via `IAuxiliaryWindowService.open()`.
- Styled with `pulseai-agent-manager-button` class using VS Code theme tokens.
- Removed the old `CommandCenterCenter` menu registration (was invisible when command center was disabled).

**Files changed:**
- `pulseAIRenderer.ts` — Added header with Manager button in `renderAgent()`
- `pulseAIRendererService.ts` — `openManagerWindow()` method using `IAuxiliaryWindowService`
- `pulseAI.contribution.ts` — Removed `CommandCenterCenter` menu entry for Manager
- `pulseAI.css` — Header and button styles

### 3. Fixed red "Pulse engine setup" error

The Pulse panel showed a red error: "PulseAI engine root is not configured". Root cause: `resolvePulseAIEngineRoot()` only checked `pulseai.engineRoot` setting and `PULSEAI_ENGINE_ROOT` env var. When neither was set (common in dev), it threw.

**Fix:** Added workspace-based auto-detection as a third fallback. If the opened workspace contains the engine (e.g., `PulseAIRepo` has `src/bridge`), it's used as the engine root.

**Files changed:**
- `common/pulseAIEngineService.ts` — `resolvePulseAIEngineRoot(configured, envRoot, workspace?)` now accepts optional workspace
- `electron-browser/pulseAIEngineService.ts` — Passes `workspace` to resolver

### 4. Python agent auto-starts on launch

Already worked (`autoStart` defaults to `true`), but was broken by issue #3. With the engine root now resolvable, the Python sidecar starts automatically when the Pulse Agent view mounts.

### 5. Manager opens as a separate Electron window

Changed from editor-tab to a real OS window:
- Uses `IAuxiliaryWindowService.open()` which creates a native popup window
- Window title: "Pulse Manager"
- Size: 1100×750
- Mounts the Manager renderer (`surface = 'manager'`) into the auxiliary window container
- All VS Code CSS is cloned automatically by the auxiliary window service

## Build status

- `compile-client` (tsc): **0 errors**
- `build-fast`: **0 errors**
- App launches with CDP on port 9222
- Engine resolves, "Pulse ready" shown

## Files modified (this session)

### Desktop IDE (`desktop/vscode/src/vs/workbench/contrib/pulseai/`)
- `browser/pulseAI.contribution.ts` — Removed broken registerSingleton, removed CommandCenterCenter Manager entry
- `browser/pulseAIRenderer.ts` — Agent header with Manager button, model interface update
- `browser/pulseAIRendererService.ts` — `openManagerWindow()`, `IAuxiliaryWindowService` injection, engine error fix
- `browser/pulseAIInlineCompletionProvider.ts` — Complete rewrite (simpler API)
- `browser/pulseAINextEditProvider.ts` — Removed unused URI import
- `browser/pulseAIRenderer.ts` — Removed unused stateIcon
- `browser/media/pulseAI.css` — Header/button styles, removed dialog overlay CSS
- `common/pulseAIEngineService.ts` — Workspace fallback in `resolvePulseAIEngineRoot()`
- `electron-browser/pulseAIEngineService.ts` — Pass workspace to resolver

### Python runtime (`src/`)
- `bridge/__main__.py` — Bridge startup changes
- `bridge/protocol.py` — Protocol helpers
- `bridge/protocol_v2.json` — Schema additions
- `context/custom_instructions.py` — New file
- `tools/inline_completions.py` — New file
- `tools/lsp_server.py` — New file
- `tools/next_edit_suggestions.py` — New file

## How to launch

```bash
# Kill existing
taskkill /F /IM "PulseAI.exe"

# Launch with engine config
cd desktop/vscode
set PULSEAI_PYTHON_PATH=D:\pulseAIagent\PulseAIRepo\.venv\Scripts\python.exe
set PULSEAI_ENGINE_ROOT=D:\pulseAIagent\PulseAIRepo
start /b .build\electron\PulseAI.exe . --remote-debugging-port=9222 D:\pulseAIagent\PulseAIRepo
```

Or simply open the workspace — the engine auto-detects from workspace path.
