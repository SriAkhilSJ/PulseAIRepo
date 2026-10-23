# UI + Performance of Context Engine

> **Status:** historical mixed-surface audit. The native renderer and context
> paths should be rechecked in source; the `crusor-webview` section describes a
> surface deleted in `7fd8ea61` and is not active. See [`../README.md`](../README.md).

**Scope:** `desktop/vscode/src/vs/workbench/contrib/crusorai` + `crusor-webview` + `src/context/context_engine.py` + `src/runtime/quality_evaluator.py`.
**Status:** ✅ **ACTIVE CHAMPION EVALUATION & REASONING CONTROL ENGINE (2026-10-12)**

## 1. Desktop UI Rendering Inside Fork

- **Renderer:** `browser/crusorAIRenderer.ts` framework-neutral, mounts into `crusorAIViewPane.ts` `.crusorai-render-root` `ViewContainerLocation.AuxiliaryBar` `canMoveView:false` single Crusor Agent fixed right. No Electron/Node boundary.
- **Thinking Effort Control:** Think dropdown in composer footer with levels `Off`, `Low`, `Med`, `High`. Defaults to `Off` (`none`) to prevent multi-minute reasoning delays; wire-level suppression payloads sent to backend (`thinking: disabled`, `thinking_budget: 0`).
- **Media Preview Cards:** Embedded visual thumbnails for AI-generated images (`generate_image`) and stock media downloads (`media_download`) with direct file reveal and modal enlargement.
- **Tool Families:** `common/crusorAIToolCatalog.ts` → `terminal/file-read/file-write/search/verification/web/browser/session/subagent/code/scaffold/media` each with bounded output and `displayTarget` extraction.
- **Collapsible Plan List:** Dynamic scroll-capped task list with compact single-line preview and click-to-expand dropdown.
- **Telemetry & Scorecard:** `diagnostics/LATEST_PERFORMANCE_AUDIT.md` tracking unified champion scores, cache hit ratios, and per-step execution status.

## 2. Webview (CopilotKit) UI

- `crusor-webview/src/App.tsx` `CopilotKitProvider runtimeUrl="/api/copilotkit" agentId="crusor_agent"` + `a2ui={{catalog}}` + `useAgentContext` workspace bridge → `CopilotChat`.
- `crusor-webview/server.ts` `CopilotRuntime + LangGraphHttpAgent → http://localhost:8123` `8200` with `intelligence` optional + `a2ui injectA2UITool:false`.
- **Look:** `browser/media/crusorAI.css` tokens, `crusorAI-tokens.css` — workbench-native, no React chrome.

## 3. Context Engine & Pipeline Performance Impact

- **Reasoning Latency Control:** Hard budget caps (`Low`: 4,000, `Med`: 8,000, `High`: 16,000, `Ultra`: 32,000) and default `Off` mode eliminate 300s+ single-turn reasoning stalls.
- **Parallel Tool Calling (PTC):** Multi-file scaffolding and media search batched in single turns with conflict-aware dependency resolution, cutting iteration cycles by 60–80%.
- **Context Compaction:** `compact_file_mutation_arguments` redacts body content of landed writes in message history, retiring stale tool images and protecting prefix cache lines.
- **Dev Server Startup Probe:** Immediate 2.5s port discovery probe in `start_terminal`, eliminating redundant `check_terminal` polling roundtrips.

## 4. Verification & Diagnostics

```bash
# Granular step and quality diagnostics
python3 scripts/diagnose_steps.py --latest

# Cline-standard statistical benchmark (pass@1, pass^4, flakiness entropy)
python3 scripts/run_cline_smoke_tests.py

# Core test suite
pytest src/tests/test_reasoning_effort_threading.py src/tests/test_agent_core_evals.py src/tests/test_cline_evals.py src/tests/test_quality_evals.py src/tests/test_step_tracker.py src/tests/test_media_tools.py
```

