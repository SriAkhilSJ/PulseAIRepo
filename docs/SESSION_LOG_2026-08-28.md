# CrusorAI Desktop — Session Log (2026-08-28)

**Status:** ✅ **MERGED** — PR #14 merged 2026-09-11T21:02:36Z. All 32 layers + provider-fetched output caps now on `main`.

## What was done

### 1. Fixed 13 TypeScript compile errors

The new CrusorAI features (inline completions, next-edit suggestions, enhanced renderer) introduced 13 TypeScript errors. All fixed:

| File | Error | Fix |
|---|---|---|
| `crusorAI.contribution.ts` | `inlineCompletionProvider`/`nextEditProvider` declared but never read | Removed unused imports and broken `registerSingleton` calls |
| `crusorAI.contribution.ts` | Property 'type' missing in `registerSingleton` | Removed the malformed singleton registrations (providers are not standalone services) |
| `crusorAIInlineCompletionProvider.ts` | `IModelContentChangeEvent` not exported from model | Rewrote provider to use simpler API without internal editor types |
| `crusorAIInlineCompletionProvider.ts` | `ProvideInlineCompletionItemsFunction`/`IInlineCompletionResult` unused/not found | Removed, replaced with direct engine communication |
| `crusorAIInlineCompletionProvider.ts` | Cannot find module `inlineCompletions.js`/`provideInlineCompletions.js` | Removed internal editor contrib imports, used plain engine bridge |
| `crusorAIInlineCompletionProvider.ts` | `getFullModelPosition` doesn't exist on TextModel | Replaced with standard `getPosition()` |
| `crusorAIInlineCompletionProvider.ts` | `lineCount` declared but never read | Removed |
| `crusorAINextEditProvider.ts` | `URI` declared but never read | Removed unused import |
| `crusorAIRenderer.ts` | `stateIcon` declared but never read | Removed unused variable |

### 2. Added "Open Agent Manager" button to Crusor Agent header

- Added a `crusorai-agent-header` section at the top of the Agent shell with a "Manager" button (organization icon).
- Button calls `host.openManager()` which opens the Crusor Manager in a **separate Electron window** via `IAuxiliaryWindowService.open()`.
- Styled with `crusorai-agent-manager-button` class using VS Code theme tokens.
- Removed the old `CommandCenterCenter` menu registration (was invisible when command center was disabled).

**Files changed:**
- `crusorAIRenderer.ts` — Added header with Manager button in `renderAgent()`
- `crusorAIRendererService.ts` — `openManagerWindow()` method using `IAuxiliaryWindowService`
- `crusorAI.contribution.ts` — Removed `CommandCenterCenter` menu entry for Manager
- `crusorAI.css` — Header and button styles

### 3. Fixed red "Crusor engine setup" error

The Crusor panel showed a red error: "CrusorAI engine root is not configured". Root cause: `resolveCrusorAIEngineRoot()` only checked `crusorai.engineRoot` setting and `CRUSORAI_ENGINE_ROOT` env var. When neither was set (common in dev), it threw.

**Fix:** Added workspace-based auto-detection as a third fallback. If the opened workspace contains the engine (e.g., `PulseAIRepo` has `src/bridge`), it's used as the engine root.

**Files changed:**
- `common/crusorAIEngineService.ts` — `resolveCrusorAIEngineRoot(configured, envRoot, workspace?)` now accepts optional workspace
- `electron-browser/crusorAIEngineService.ts` — Passes `workspace` to resolver

### 4. Python agent auto-starts on launch

Already worked (`autoStart` defaults to `true`), but was broken by issue #3. With the engine root now resolvable, the Python sidecar starts automatically when the Crusor Agent view mounts.

### 5. Manager opens as a separate Electron window

Changed from editor-tab to a real OS window:
- Uses `IAuxiliaryWindowService.open()` which creates a native popup window
- Window title: "Crusor Manager"
- Size: 1100×750
- Mounts the Manager renderer (`surface = 'manager'`) into the auxiliary window container
- All VS Code CSS is cloned automatically by the auxiliary window service

## Build status

- `compile-client` (tsc): **0 errors**
- `build-fast`: **0 errors**
- App launches with CDP on port 9222
- Engine resolves, "Crusor ready" shown

## Files modified (this session)

### Desktop IDE (`desktop/vscode/src/vs/workbench/contrib/crusorai/`)
- `browser/crusorAI.contribution.ts` — Removed broken registerSingleton, removed CommandCenterCenter Manager entry
- `browser/crusorAIRenderer.ts` — Agent header with Manager button, model interface update
- `browser/crusorAIRendererService.ts` — `openManagerWindow()`, `IAuxiliaryWindowService` injection, engine error fix
- `browser/crusorAIInlineCompletionProvider.ts` — Complete rewrite (simpler API)
- `browser/crusorAINextEditProvider.ts` — Removed unused URI import
- `browser/crusorAIRenderer.ts` — Removed unused stateIcon
- `browser/media/crusorAI.css` — Header/button styles, removed dialog overlay CSS
- `common/crusorAIEngineService.ts` — Workspace fallback in `resolveCrusorAIEngineRoot()`
- `electron-browser/crusorAIEngineService.ts` — Pass workspace to resolver

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
taskkill /F /IM "CrusorAI.exe"

# Launch with engine config
cd desktop/vscode
set CRUSORAI_PYTHON_PATH=D:\crusorAIagent\PulseAIRepo\.venv\Scripts\python.exe
set CRUSORAI_ENGINE_ROOT=D:\crusorAIagent\PulseAIRepo
start /b .build\electron\CrusorAI.exe . --remote-debugging-port=9222 D:\crusorAIagent\PulseAIRepo
```

Or simply open the workspace — the engine auto-detects from workspace path.
