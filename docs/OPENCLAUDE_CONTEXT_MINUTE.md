# OpenClaude Context Engine — Every Minute Thing

**Repo:** `D:\openclaude` (Gitlawb/openclaude) — audit 2026-08-30. Keywords `context/prompt/memory/compress/token/cache/retrieval` scanned `src/ web/ docs/ vendor/ scripts/`.

> **Top finding: No explicit RAG/vector/embedding engine exists.** Nearest equivalents: **RepoMap** (tree-sitter PageRank), **knowledgeGraph/conversationArc** (keyword graph), **attachments/memory injection** (CLAUDE.md), **skillSearch** (chunked semantic). `web/` `vendor/` `scripts/` `docs/` contain zero context-engine logic.

---

## 1. Context Window

**`src/utils/context.ts:16`**
- `MODEL_CONTEXT_WINDOW_DEFAULT 200000:17`, `OPENAI_FALLBACK 128000:24` (env `CLAUDE_CODE_OPENAI_FALLBACK_CONTEXT_WINDOW`), `COMPACT_MAX_OUTPUT_TOKENS 20000:30`, `CAPPED_DEFAULT_MAX_TOKENS 8000:42` → covers 99% (p99 4911), `ESCALATED_MAX_TOKENS 64000:43`, `MIN_CONTEXT_WINDOW_OVERRIDE 33000:56` (20k+13k), `CONTEXT_1M_BETA context-1m-2025-08-07:24`.
- `getContextWindowForModel:223` ladder: CLAUDE_CODE_MAX_CONTEXT_TOKENS (ant) → session override `/set_context_window` → `[1m]` suffix → integration runtime limits `resolveModelRuntimeLimits` → `modelCapabilities.max_input_tokens>=100k` → beta `context-1m` → GrowthBook `coral_reef_sonnet` → descriptor → 200k.
- `calculateContextPercentages:313` sums `input+cache_creation+cache_read`.

**`src/services/compact/autoCompact.ts:35`**
- `MAX_OUTPUT_TOKENS_FOR_SUMMARY 20000:32`, `AUTOCOMPACT_BUFFER 13000:77`, `WARNING/ERROR_BUFFER 20000:78`, `MANUAL 3000:80`, `FAILURE_COOLDOWN 300000:82` (5m), `MAX_CONSECUTIVE_FAILURES 3:92` (BQ 250K wasted/day). `getEffectiveContextWindowSize:35 = max(context-min(maxOutput,20k), reserved+13k)`, `getAutoCompactThreshold:170 = effective-13k`, `shouldAutoCompact:263` guards compact/session_memory/marble_origami/tengu_cobalt/CONTEXT_COLLAPSE.

**`src/integrations/runtimeMetadata.ts:243` + `descriptors.ts:115`** per-route catalog windows (`qwen.ts:15`, `moonshot.ts:37` 262144), `contextWindowUpgradeCheck.ts`.

---

## 2. Prompt Building

**`src/constants/prompts.ts:115` + `src/utils/systemPrompt.ts:41`**
- `SYSTEM_PROMPT_DYNAMIC_BOUNDARY __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__:115` splits static `scope:global` cacheable vs dynamic. Sections: intro, doingTasks, actions, usingTools, sessionSpecificGuidance `348` (post-boundary), outputEfficiency, toneAndStyle, reminders `121`, plus registry `memory, ant_model_override, env_info_simple, mcp_instructions, scratchpad, token_budget`.
- `getSystemPrompt:440` returns `string[]` bare mode short.
- `src/services/api/claude.ts:382` `getPromptCachingEnabled:345` firstParty/bedrock/vertex, `getCacheControl:383` `{type:ephemeral, ttl:1h?, scope:global}`, `userMessageToMessageParam:613` cache on last block, `queryModel:1101` builds betas + tool schemas.

## 3. Memory Injection

**`src/utils/attachments.ts:1`** 19 types via `getAttachments()` <1s abort `794`: `userInputAttachments` (at-files, mcp resources, skill turn-0), `allThreadAttachments` (queued_commands, deferred_tools_delta, changed_files, plan_mode, teammate mailbox), `mainThreadAttachments` (IDE selection, diagnostics, LSP, token_usage). `MAX_MEMORY_LINES 200`, `MAX_MEMORY_BYTES 4096`, `RELEVANT_MEMORIES 60KB:304`.

**`memdir/`, `utils/memory/`, `SessionMemory/`** `memoryCompaction.ts:16` pressure `elevated→onCompact(false) critical→onCompact(true)`.

**`utils/context*.ts`** `contextAnalysis.ts:27` per-tool `roughTokenCountEstimation`, `conversationArc.ts:86` phase init→exploring→implementing→reviewing→completed + `extractFactsAutomatically`, `knowledgeGraph.ts` entities/relations/rules `getOrchestratedMemory`, `hybridContextStrategy.ts:176` split cacheWeight 0.4, `contextPartitioning.ts:35` zones recent 50k/important 30k/background 10k/system 8k.

## 4. Token Budgeting

**`src/services/tokenEstimation.ts:1` 716L** `countMessagesTokensWithAPI:147` via `betas/messages/countTokens` → `roughTokenCountEstimationForCountTokensFallback` → `countTokensViaHaikuFallback:465` → `rough...ForMessages`. `roughTokenCountEstimation 274 len/4`, `MODEL_TOKENIZER_CONFIGS 308`, `roughTokenCountEstimationForBlock 607` image 2000, tool_use `name+input json`.

**`src/utils/tokens.ts:1` 590L** `getTokenCountFromUsage:77` sum input+cache+output, `tokenCountWithEstimation:572` incremental `IncrementalTokenCounter:48` SHA256 16hex LRU, `TokenUsageTracker:415` 1000 entries. `src/utils/toolResultStorage.ts:1` `MAX_TOOL_RESULT_BYTES` 50k preview 2000, `enforceToolResultBudget:801` group-merge fresh.

**`src/utils/tokenBudget.ts:1`** `+10k` shorthand `SHORTHAND_START_RE`, `createBudgetTracker`, `checkTokenBudget:45` continues while `turnTokens < budget*0.9`.

## 5. Compaction

**`compact.ts:1` 1000L** `stripImages 154`, `CompactionResult 308` boundaryMarker, `compactConversation:410` preHooks → `streamCompactSummary` forked-agent cache-sharing vs fallback (2 retries, 120000ms), `POST_COMPACT_MAX_FILES 5 POST_COMPACT_TOKEN_BUDGET 50k:131`. `microCompact.ts:1` 552L `COMPACTABLE_TOOLS {Read, Shell, Grep}` + `microcompactMessages:257` time-based 60m vs cached `pendingCacheEdits` via `cache_reference`.

**`query.ts:1` 2400L** loop `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES` guard, `blockingLimit effective-3k`.

## 6. Caching

**`promptCacheBreakDetection.ts:1` 1027L** `PreviousState` per source max10 prefixes, `recordPromptState:514` hashes, `checkResponseForCacheBreak:704` drop >5% + >2000 tokens `MIN_CACHE_MISS_TOKENS 147`, `CACHE_TTL_5MIN 300k`.

**`cacheStatsTracker.ts:1`** ring 500, `fileReadCache.ts:14` Map 1000 mtime, `conversationCache.ts:21` LRU 100 TTL 24h, `context/repoMap/cache.ts` disk `~/.claude` per repo `DEFAULT_MAX_TOKENS 2048` `buildRepoMap:94` hash-hit else tree-sitter→graph→PageRank.

## 7. Retrieval (No Vector RAG)

**Explicit:** `rg RAG|vector` hits only model names. Gap = dedicated vector store.

| File | Role |
|---|---|
| `context/repoMap/graph.ts` | RepoMap tree-sitter → PageRank → token-budgeted `renderMap` |
| `knowledgeGraph.ts` | Entity graph `addGlobalEntity/Relation/Rule` keyword RAG |
| `attachments.ts:241 findRelevantMemories` | Memory surfacing `relevantMemories` |
| `skillSearch/` | Chunked semantic skill discovery |
| `ripgrep.ts + GrepTool` | Manual text search |

## 8. Constants Table

| Constant | Value | File |
|---|---|---|
| 200k default | 200000 | context.ts:17 |
| AUTOCOMPACT_BUFFER | 13000 | autoCompact.ts:77 |
| MAX_CONSECUTIVE_FAILURES | 3 | autoCompact.ts:92 |
| SYSTEM_PROMPT_DYNAMIC_BOUNDARY | __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__ | prompts.ts:115 |
| POST_COMPACT_BUDGET | 50k | compact.ts:131 |
| IMAGE_MAX_TOKEN | 2000 | microCompact.ts:31 |
| MIN_CACHE_MISS | 2000 | promptCacheBreakDetection.ts:147 |

---

*Use this as OpenClaude baseline — PulseAI gap is vector store vs deterministic PageRank; see `PULSEAI_CONTEXT_BENCH.md` for bench.*
