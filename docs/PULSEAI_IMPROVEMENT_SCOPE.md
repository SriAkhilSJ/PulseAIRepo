# PulseAI Context Engine — How Big to Compete With Top

**Goal:** Compete with Hermes (Nous) + OpenClaude (Anthropic) + Copilot. **Current:** Hermes-grade rename done, but still 5 gaps that matter at 400K+ histories. **Size:** 3–4 weeks, 1 engineer, ~2.5k lines changed.

---

## 1. Where PulseAI Stands (vs Minute Audits)

| Area | PulseAI Today | Hermes | OpenClaude | Gap |
|---|---|---|---|---|
| **Window** | `model_budgets.py` env-override → cache → **endpoint `/models` (12 keys, ahead of the table)** → 3 catalog probes → default; `PROVIDER_SAFE_LIMIT=0` is the shipped AUTO default | `model_metadata.py:3048` 10-rung ladder: live endpoint/provider metadata ABOVE a hardcoded family table, 256K generous fallback + step-down on context-length errors, fallback never cached | `context.ts:223` 8-rung ladder + 1M beta + GrowthBook | Was wrongly marked Done: probes covered groq/gemini/openrouter only, so `custom` (self-hosted/routers) had no live path and ran on the 8,192 guess. Now parity for discovery; still behind on the output cap and step-down-on-400 |
| **Build** | `context_engine.py:586` classify→16 layers relevance 0.15→score→budget→prune→volatile tail, RLock, shared classifier | `system_prompt.py:341` 3-tier stable/context/volatile + `prompt_builder` threat scan + `boundary LRU 32` | `systemPrompt.ts:115` `__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__` split static global cacheable | **Mid** — Pulse has 16-layer churn; need stable prefix metering |
| **Retrieval** | `chunk_index.py:1036` hybrid FTS5 12 terms + vec0 KNN `MATCH vec_f32` 12× + RRF k=60 + PageRank, bounded `bounded_scan.py:78` 1000f/16MiB/5s ledger, import-edges `lang_extractors` | LSP-based `coding_context` (no vec) | RepoMap PageRank `renderMap 2048` + knowledgeGraph keyword | **Pulse ahead** on hybrid, behind on lean tail deref |
| **Compaction** | `compaction.py:214` head-first-turn + tail 20K + middle `SmartCompressor` + `summarizer 800/3000/8000` + prune ≥600c placeholder | `context_compressor.py:1` lean tail verbatim user blocks 24K + tool demotions 6 rounds + chunked map-reduce digests 72K/28×1.4K + salvage + `session_search` recovery footer + 7K anchor index | `compact.ts:410` 50K post-compact budget, `microCompact` cached `pendingCacheEdits` | **Pulse missing 400K+ tail** — hermes lean tail |
| **Cache** | `prompt_cache_boundary.py:56` LRU 32 + `system_prompt.py` | `prompt_cache_boundary` + `prompt_cache_scope` lineage + `conversation_compression` 4-breakpoint 5m/1h + native `gpt-5.6` compaction | `promptCacheBreakDetection.ts:704` drop >5%+2K, `cacheStatsTracker` ring 500 | **Pulse missing** scope lineage + 4-breakpoint + native |
| **Security** | `threat_patterns.py:63` 35 scoped + `file_safety` realpath + `redact` 50 prefixes (ported) | Same + cross-profile/sandbox-mirror guards | N/A | **Done** (ported) |
| **Token** | `token_budget.py:17` tiktoken `chars/4` +4/+2 | Rough `chars/4` | `tokenEstimation.ts:147` API `countTokens` → Haiku fallback → `len/4` + `toolResultStorage` persisted 50k | **Pulse best** (exact) but trim can split tool pairs—hermes keeps envelope |

## 2. How Big Is “Compete” — Phased Effort

### P1 — Lean tail + recovery (5 days, ~600 lines)
Copy Hermes `context_compressor.py:951` verbatim:
- `LEAN_TAIL_FLOOR 10K CAP 25K` + `_LEAN_USER_BUDGET 24K` verbatim blocks, `_LEAN_TAIL_KEEP_TOOL_ROUNDS 6` demote to `stub + session_search` recovery footer, chunked digests `72K/28`. Add `salvage_grown_transcript:501` cheapest-first shrink. This closes the only gap that matters at 400K histories—today Pulse truncates middle and loses user verbatim.

### P2 — Stable prefix lineage + 4-breakpoint (4 days, ~400 lines)
- Port `prompt_cache_boundary LRU` already done → add `prompt_cache_scope.py:43` lineage `get_compression_lineage()[0]` memo, and `prompt_caching.py:385` 4-breakpoint `direct_native_tool_cache`. Meter via `prompt_cache_audit.py:56` hit rate, gate on `PULSEAI_PROMPT_CACHE=1`. Without this, 16-layer reorder busts cache every turn (Law 1).

### P3 — Import-edge + tree-sitter keep (2 days, keep)
Pulse already has `lang_extractors 645L` for JS/TS/Go/Rust/Java vs Hermes LSP. Keep, just add `resolveFocusFiles` boost like Hermes `subdirectory_hints:256` 8K ANCESTORS 5. No change.

### P4 — Token envelope + tool-pair guard (1 day, ~80 lines)
Fix `token_budget.trim_messages_to_budget 92` to never split `AIMessage(tool_calls)`/`ToolMessage` pair—copy `smart_compressor._enforce_tool_pairing:128`. Add `countTokens` envelope + `replayKeys` distinction `_ALWAYS_REPLAYED` vs `_NEWEST_TURN_ONLY` hermes `1826`.

### P5 — Herms deps bench + UI perf (3 days)
Setup `D:\hermes` `pyproject.toml:19` `openai==2.24.0` strict pins vs Pulse `openai>=2.47` conflict → **separate venvs** (do not co-install). Bench 5 fixtures micro/mid/5K-desktop/400-history/autonomous: measure token+latency+retrieval+compaction + webview `CopilotChat` render vs `pulseAIRenderer.ts:577` fixed right.

**Total:** 15 days, ~2.5k LOC, 1 engineer. Without P1+P2, Pulse can’t compete on cost/latency—cache miss every turn multiplies `~5.6k` tool-def tokens 30×.

## 3. Why This Is Enough to Compete

Hermes and OpenClaude intentionally avoid vector RAG—both use deterministic RepoMap PageRank + bounded scans. Pulse’s hybrid vec0+FTS RRF is already *more* than they have. The moat is not retrieval, it’s **prompt-cache stability** (Law 1) + **lean tail recoverability** (Law 2). Copy those two and Pulse ties on cheapness, latency, durability, security, UI—look is already ahead (workbench-native `pulseAIRenderer.ts` vs webview).

*Next: `docs/PULSEAI_CONTEXT_BENCH.md` for bench setup + `verify.bat` for provider-free proof.*
