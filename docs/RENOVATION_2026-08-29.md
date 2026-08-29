# Renovation 2026-08-29 — Context Engine, Security, CopilotKit, Desktop

**Scope:** full Hermes alignment + CopilotKit fully (desktop fixed right, single agent) — Latency/Cheapness/Performance/Look/Durability/Security/ UI.

## 1. What changed

### Context Engine — `src/context/context_engine.py:1` → ABC
* New `src/context/engine.py:1` pluggable `ContextEngine(ABC)` — `threshold_percent=0.75/protect_first/last 3/6`, `sanitize_memory_context 6k`, hooks `should_compress/prune_tool_results_only/select_context/on_turn_complete`.
* Removed `LAYER_RELEVANCE 16×9` scoring + `dedup 0.88` embedding churn (turn path now inference-free). Kept `VOLATILE_TAIL_PREAMBLE` + `ContextBudget share(n)` fair slicing.
* New 3-tier prompt `src/context/system_prompt.py:1` stable/context/volatile + `src/context/prompt_cache_boundary.py:1` `register_stable_prefix/find_stable_prefix` LRU 32.

### Security
* `src/context/threat_patterns.py:1` — 35 regex scoped `all/context/strict` + NFKC + `INVISIBLE_CHARS` (port `tools/threat_patterns.py:63`).
* `src/context/file_safety.py:1` — `realpath` deny `~/.ssh/.aws/.gnupg`, `get_read_block_error` for `.env/.env.*/.envrc/mcp-tokens/browser-profile` (774L port).
* `src/utils/redact.py:1` — 50 prefix patterns + `ENV_ASSIGN/CFG_DOTTED/YAML` + `JWT/DB_CONNSTR` (1427L port, `agent/redact.py:774`), wired in `src/tools/file_tools.py:108` (`file_read` sentinel) + `src/runtime/tool_middleware.py:41` (`<untrusted_tool_result>` wrapper + `redact_sensitive_text(force)`).
* `src/context/safety_guard.py:83` — realpath + `get_read_block_error`.

### CopilotKit — `ui/` deleted → `pulse-webview/`
* `ui/` SolidJS lab removed (disgusting per UX review) — replaced by Vite React-TS `pulse-webview/` (`@copilotkit/react-core@1.69.3/runtime@1.69.3/a2ui-renderer@1.69.3`, `zod@4.5.2`, `react@19.2.8`).
* `pulse-webview/server.ts:1` — `CopilotRuntime({agents:{pulse_agent:Agent, default:Agent}, intelligence: CopilotKitIntelligence(apiKey: INTELLIGENCE_API_KEY), a2ui:{injectA2UITool:false}, cors:true})` on `8200` with `LangGraphHttpAgent → http://localhost:8123`.
* `src/server.py:1` — FastAPI `8123` `add_langgraph_fastapi_endpoint` with `MemorySaver` (async-compatible, preserves `SqliteSaver` for bridge). Needs `uv run python -m src.server` (not `python src/server.py`).
* `src/a2ui_schemas/pulse_task_schema.json:1` fixed-schema Card>Column, `src/graphs/chat_graph.py:340` `@tool display_pulse_task` → `a2ui.render`, `src/graphs/state.py:8` `AgentState(CopilotKitState)`.
* `.copilotkit/project.json:1` `pulseai 3084` `sri-s-organisation` + `.env:INTELLIGENCE_API_KEY=cpk-3084_***` provisioned.
* Desktop lock — `desktop/vscode/src/vs/workbench/contrib/pulseai/browser/pulseAI.contribution.ts:84` `AuxiliaryBar, canMoveView:false`, single Pulse Agent `pulseAIViewPane.ts:50` + webview `pulse-webview` right of editor.

### Error surfacing & cheapness
* `src/llm/error_classifier.py:1` (2187L taxonomy `FailoverReason`) wired in `src/llm/factory.py:729` `_is_retryable` (billing/auth not retryable); `src/dashboard/error_surface.py:1` → `src/dashboard_server.py:178` emits `{layer,code,retryable,provider,model}` + `ToolRow.tsx:6` layer badge.
* `src/llm/stream_diag.py:1`, `src/utils/redact.py` at journal + dashboard, narrow-waist still TODO (31→8 tools).

## 2. Verification (no Sarvam LLM spent except final hello)

* `uv run pytest src/tests/test_bounded_scan.py src/tests/test_bridge_protocol_v2.py -q` → 35 passed.
* `npm run typecheck-client --prefix desktop/vscode` PASS; `npx tsc --noEmit --project pulse-webview/tsconfig.json` PASS.
* `curl http://localhost:8200/api/copilotkit/info` → `{"pulse_agent","default"} mode:intelligence a2uiEnabled:true` (after `dotenv/config` fix).
* `curl http://localhost:8123/health` → `{"status":"ok"}` (after `MemorySaver` fix for `SqliteSaver async`).
* `http://localhost:5173` — first load blank `Agent default not found` → fixed `server.ts` alias + `App.tsx agent="pulse_agent"` → header `PulseAI — Pulse Agent` + `CopilotChat` input + user `hello` bubble rendered (`D:\pulseAIagent\browser-verify.png` 22806 bytes, `e2e-verify.spec.ts` 1 passed). `Failed to fetch` on POST is transient when `8123` not ready before `5173` load.

## 3. Sarvam API — cheapness guard

* `CUSTOM_BASE_URL=https://api.sarvam.ai/v1` `CUSTOM_API_KEY=sk_mxvz84oz_***` — only 90 credits left. Renovation used 0 LLM calls; e2e used only UI render (no completion). Real `hello` → `pulse_agent` completion will spend 1 turn.

## 4. Runbook

```powershell
# Terminal 1 — 8200
Set-Location -LiteralPath "D:\pulseAIagent\PulseAIRepo"; & "C:\Program Files\nodejs\npx.cmd" --yes tsx pulse-webview/server.ts
# Terminal 2 — 8123
Set-Location -LiteralPath "D:\pulseAIagent\PulseAIRepo"; uv run python -m src.server
# Terminal 3 — verify
curl http://localhost:8200/api/copilotkit/info; curl http://localhost:8123/health
# Terminal 4 — 5173
Set-Location -LiteralPath "D:\pulseAIagent\PulseAIRepo\pulse-webview"; npm run dev
# open http://localhost:5173 → CopilotChat, hard refresh Ctrl+Shift+R
```

## 5. Next (not yet)
* Narrow waist toolsets `toolsets.py` (31→8), prompt-cache prefix metering `prompt_cache_audit`, `AsyncSqliteSaver` durable for `8123` (currently `MemorySaver`), and full `Failed to fetch` retry on browser POST (keep both servers alive before chat).

