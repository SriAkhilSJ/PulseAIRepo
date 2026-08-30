# UI + Performance of Context Engine

**Scope:** `desktop/vscode/src/vs/workbench/contrib/pulseai` + `pulse-webview` + `src/context/context_engine.py`.

## 1. Desktop UI Rendering Inside Fork

- **Renderer:** `browser/pulseAIRenderer.ts:577` framework-neutral, mounts into `pulseAIViewPane.ts:50` `.pulseai-render-root` `ViewContainerLocation.AuxiliaryBar` `canMoveView:false` single Pulse Agent fixed right. No Electron/Node boundary.
- **Tool families:** `common/pulseAIToolCatalog.ts` → `familyBody:194` `terminal/file-read/file-write/search/verification/web/browser/session/subagent/code/scaffold` each with bounded output `12k` and `displayTarget` extraction.
- **State:** `common/pulseAIRendererService.ts` `PulseAIRenderModel` history + tools + subAgents + `turnOutcome` + `telemetry cacheHitRate`.
- **Performance:** 613 lines, no React, `data-testid` stable, `visible` role handling for Mistral alternation `_template_visible_role:302`.

## 2. Webview (CopilotKit) UI

- `pulse-webview/src/App.tsx:29` `CopilotKitProvider runtimeUrl="/api/copilotkit" agentId="pulse_agent"` + `a2ui={{catalog}}` + `useAgentContext` workspace bridge → `CopilotChat`.
- `pulse-webview/server.ts:11` `CopilotRuntime + LangGraphHttpAgent → http://localhost:8123` `8200` with `intelligence` optional + `a2ui injectA2UITool:false`.
- **Look:** `browser/media/pulseAI.css` tokens, `pulseAI-tokens.css` — workbench-native, no React chrome.

## 3. Context Engine Performance Impact on UI

- **Build latency:** Cold 34.9s (first repo_map+chunks), warm <15ms via `context_engine.py:289` differential `_HASHED_STATE_KEYS 16` + `VOLATILE_LAYERS` git 1s. UI streaming blocked on build → warm matters for perceived latency.
- **Token overhead:** `prompt_cache_boundary` 4-breakpoint miss every turn = 5.6k tool-def resend ×30 turns = wasted. Fix P2 cuts 4.6×.
- **Retrieval:** Warm ≤20ms, cold 7s (first embedding). UI shows spinners `statusGlyph:155` for `running`.
- **Compaction:** `compaction.py:214` + `smart_compressor 212L` turn-atomic, protects `head first turn + tail 20K`, middle iterative 3K anti-thrash `15%→3×`. Without lean tail, 400K history UI freezes on trim.

## 4. Checks

```bash
# UI typecheck + DOM
npx tsc -b --project pulse-webview/tsconfig.json
npm run test --prefix pulse-webview  # 9 DOM
# Context perf
uv run python -m pytest src/tests/test_bounded_scan.py -q
# Live
curl http://localhost:8200/api/copilotkit/info | findstr pulse_agent
```

**Next:** P1 lean tail + P2 4-breakpoint + keep tree-sitter vs LSP (Pulse ahead on hybrid). See `PULSEAI_IMPROVEMENT_SCOPE.md`.
