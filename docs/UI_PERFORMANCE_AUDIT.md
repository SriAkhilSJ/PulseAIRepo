# UI + Performance of Context Engine

**Scope:** `desktop/vscode/src/vs/workbench/contrib/crusorai` + `crusor-webview` + `src/context/context_engine.py`.
**Status:** ✅ **MERGED** — PR #14 merged 2026-09-11T21:02:36Z. All 32 layers + provider-fetched output caps now on `main`.

## 1. Desktop UI Rendering Inside Fork

- **Renderer:** `browser/crusorAIRenderer.ts:577` framework-neutral, mounts into `crusorAIViewPane.ts:50` `.crusorai-render-root` `ViewContainerLocation.AuxiliaryBar` `canMoveView:false` single Crusor Agent fixed right. No Electron/Node boundary.
- **Tool families:** `common/crusorAIToolCatalog.ts` → `familyBody:194` `terminal/file-read/file-write/search/verification/web/browser/session/subagent/code/scaffold` each with bounded output `12k` and `displayTarget` extraction.
- **State:** `common/crusorAIRendererService.ts` `CrusorAIRenderModel` history + tools + subAgents + `turnOutcome` + `telemetry cacheHitRate`.
- **Performance:** 613 lines, no React, `data-testid` stable, `visible` role handling for Mistral alternation `_template_visible_role:302`.

## 2. Webview (CopilotKit) UI

- `crusor-webview/src/App.tsx:29` `CopilotKitProvider runtimeUrl="/api/copilotkit" agentId="crusor_agent"` + `a2ui={{catalog}}` + `useAgentContext` workspace bridge → `CopilotChat`.
- `crusor-webview/server.ts:11` `CopilotRuntime + LangGraphHttpAgent → http://localhost:8123` `8200` with `intelligence` optional + `a2ui injectA2UITool:false`.
- **Look:** `browser/media/crusorAI.css` tokens, `crusorAI-tokens.css` — workbench-native, no React chrome.

## 3. Context Engine Performance Impact on UI

- **Build latency:** Cold 34.9s (first repo_map+chunks), warm <15ms via `context_engine.py:289` differential `_HASHED_STATE_KEYS 16` + `VOLATILE_LAYERS` git 1s. UI streaming blocked on build → warm matters for perceived latency.
- **Token overhead:** `prompt_cache_boundary` 4-breakpoint miss every turn = 5.6k tool-def resend ×30 turns = wasted. Fix P2 cuts 4.6×.
- **Retrieval:** Warm ≤20ms, cold 7s (first embedding). UI shows spinners `statusGlyph:155` for `running`.
- **Compaction:** `compaction.py:214` + `smart_compressor 212L` turn-atomic, protects `head first turn + tail 20K`, middle iterative 3K anti-thrash `15%→3×`. Without lean tail, 400K history UI freezes on trim.

## 4. Checks

```bash
# UI typecheck + DOM
npx tsc -b --project crusor-webview/tsconfig.json
npm run test --prefix crusor-webview  # 9 DOM
# Context perf
uv run python -m pytest src/tests/test_bounded_scan.py -q
# Live
curl http://localhost:8200/api/copilotkit/info | findstr crusor_agent
```

**Next:** P1 lean tail + P2 4-breakpoint + keep tree-sitter vs LSP (Crusor ahead on hybrid). See `CRUSORAI_IMPROVEMENT_SCOPE.md`.
