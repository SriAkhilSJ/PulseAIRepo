# Next Repos Reference — What the Best Repos Do & Why

**Source:** docs/agent_core_blueprint.html, docs/ref_blueprints.html, docs/*.md audits, scripts/ref_blueprints.py, scripts/agent_core_blueprint.py
**Compared repos:** Aider, OpenCode, Void, OpenClaude, Hermes (NousResearch/hermes-agent)
**CrusorAI repo:** PulseAIRepo
**Date:** 2026-11-01

---

## 1. The 4-Harness Fixed-Cost Table (from docs/ref_blueprints.html)

This is what every LLM call pays **before it reads a byte of your request** (system message + tool schemas + repo map). Measured twice from source — once by static literals (chars/4), once by assembled prompt (cl100k estimator).

| Harness | System Tok | Tools | Schema Tok | Tok/Tool | Compact Levels | Repo Map | Fixed / Cycle |
|---|---|---|---|---|---|---|---|
| Aider | 1,265 | 0 | 0 | — | 1 | 1,024 | **2,289** |
| OpenCode | 333 | 19 | 2,483 | 130 | 5 | 0 | **2,816** |
| Void | 1,400 | 15 | 497 | 33 | 1 | 0 | **1,897** |
| **CrusorAI** | **6,151** | **36** | **7,509** | **208** | **1** | **0** | **13,660** |

**CrusorAI's tool schemas alone (7,509 tok) exceed every competitor's entire fixed cost.**

- vs Aider: **6× higher**
- vs OpenCode: **4.8× higher**
- vs Void: **7.2× higher**

---

## 2. CrusorAI's Own Runs — Where the Money Went

From docs/agent_core_blueprint.html (run `41290247998`):

| Metric | Value |
|---|---|
| Prompts | 5 |
| Cycles | 104 |
| Tokens | 2,967,652 |
| Cost | $0.45 |
| Completed work | 472,716 tok (16%) |
| Discarded by cycle-cuts | 2,494,936 tok (84%) |
| Fixed overhead per cycle | 7,939 tok (27%) |
| Tokens per cycle (mean) | 28,805 |
| Cost per cycle | ~$0.0044 |
| Session wall clock inside model | 98.9% |
| Tools sent / defined | 36 / 68 |

**Cycle count explodes:** prompt 1 = 4 cycles, prompt 3 = 33 cycles.

---

## 3. Why Each Repo Is Built the Way It Is (Constraints → Decisions)

Every decision below is a **consequence of a constraint** that repo accepted. Copying the artifact without the constraint is how a plan becomes waste.

### 3.1 Aider — "any model, text only"
**Constraint:** Must work with *every* LLM, including models with no function calling. Takes a diff on the first try.

| Decision | Why (from source) |
|---|---|
| Zero tool schemas | Rejected OpenAI function calling. "GPT is worse at editing code if you use tools." |
| SEARCH/REPLACE + unified diffs | Stuffing source into JSON is escape-hell. Diffs survive; JSON does not. |
| 350 tok few-shot examples | Without them, editing errors rise 30–50%; without flexible patching, 9×. Examples are error-prevention, not decoration. |
| Repo map 1,024 → 8,192 tok | Can't read files mid-turn (no tools), so the whole repo arrives compressed. The map is a **substitute for tool calls**, not an extra. |
| 3 reflections max | With no agent loop, a wrong edit is re-asked, not investigated. Bounded because each retry is full-file context. |

**Transferable:** For file editing, a text diff beats a JSON tool call — measured.
**Not copyable:** 0 tool schemas — CrusorAI needs tools (browser, device, preview, delegate).
**Prompt lesson:** Emotional-appeal prompts ("you are blind, will tip $2000") produced **worse** scores. CrusorAI's persona carries 8 × NEVER, 5 × ALWAYS, 2 × MUST — same category, benchmarked counter-productive.

### 3.2 OpenCode — "many providers, long sessions, cache first"
**Constraint:** Runs against dozens of providers/models. Sessions live for hours. Prompt cache is the single largest cost lever.

| Decision | Why (from source) |
|---|---|
| 189-token base prompt | Harness supplies behavior; prompt only states posture. Per-model quirks live in plugins, appended on demand by model-id substring match. Thin core + composable deltas. |
| 5 graded compaction levels | Whole → outputs clipped → outputs removed → user-only → omitted. Cheap levels are free (no LLM call); summary is last resort. |
| Precompute at 85%, hold, don't apply | "Summarizes everything before the latest response **in the background** … held, not applied: swapping it in now would **rewrite the prefix and throw away the cache**." **This is CrusorAI's bug, named by someone else.** |
| PRECOMPUTE_MIN_TOKENS = 64,000 | Explicit break-even gate before spending a background summary. |
| TRANSCRIPT_CLIP = 2,000 chars per end | Old tool output kept as head + tail, never re-sent whole. |
| Prefer dedicated tools over shell | Terminal is fallback, not strategy. |

**Transferable:** Compaction must hold a precomputed summary, never rewrite the prefix. OpenCode's comment describes exactly CrusorAI's failure.
**Not copyable:** 6 providers, plugin architecture — CrusorAI has one model.

### 3.3 Void — "an editor first, local models included"
**Constraint:** VS Code fork driving frontier + local models. User is watching the screen while it works.

| Decision | Why (from source) |
|---|---|
| XML tool definitions, not JSON Schema | Fallback path for providers with no native tool wire format (local/Ollama/custom). Terseness is a side effect. |
| ~20 tok per tool description | Written for generic small model — every word must earn itself. Compatibility, not token optimization. |
| File tree in system message | 20,000 chars, sent **once at start** (on-demand variant for later). Removes a discovery round-trip at t=0. Stable prefix → caches. Pays tokens to buy one fewer cycle. |
| 15 tools, 3 search | Structured results smaller/cheaper than raw grep output. |
| ONE tool call per response | UI streams each result into a diff zone as it lands. One call = visible, cancellable progress. Latency design, not token design. |
| Apply in-editor (Fast Apply) | SEARCH/REPLACE; model never round-trips the file. Fast Apply for small files, Slow Apply for large. |

**Transferable:** In-editor apply applies exactly to CrusorAI (desktop/vscode, crusorai-diff, MAX_INLINE_DIFF_CHARS = 512,000). One-call-per-response exists for streaming — CrusorAI can have batching AND visible progress.
**Not copyable:** XML schemas — CrusorAI uses JSON Schema natively.

### 3.4 OpenClaude — "no vector RAG, deterministic PageRank"
**Constraint:** Context engine built on deterministic retrieval, not embeddings.

| Decision | Why |
|---|---|
| RepoMap via tree-sitter → PageRank | Keyword graph, token-budgeted renderMap. No vector store. |
| Knowledge graph | Entities/relations/rules, keyword RAG via getOrchestratedMemory. |
| Memory injection | 19 attachment types, MAX_MEMORY_LINES 200, MAX_MEMORY_BYTES 4096. |
| Prompt cache break detection | Hash previous state, drop if >5% + >2000 tokens change. |
| Auto-compact buffer 13,000 tok | Warning/error buffer 20,000 tok, failure cooldown 5 min. |
| Context partitioning | Zones: recent 50k / important 30k / background 10k / system 8k. |

**CrusorAI gap:** No vector store vs deterministic PageRank — but CrusorAI already has repo_map + chunk_index + git_context which OpenClaude lacks.

### 3.5 Hermes (NousResearch/hermes-agent) — "CLI coding agent, production-hardened"
**Constraint:** CLI agent, long sessions, production reliability.

| Decision | Why |
|---|---|
| Byte-stable system prompt | Never mutate past context. Only sanctioned mutation is compression. |
| Strict role alternation | assistant(tool_calls) → tool → user pattern only. |
| Prompt cost paid once | Universal guidance blocks kept tight — ship in cached prefix. |
| Model-conditioned guidance | Only pay tokens where the model shows the failure mode. Claude gets none. |
| Skills pull model | Index rides system prompt; full body loads on demand via skill_view. |
| [SKILL_PRUNED] markers | Compression failure becomes recoverable — model told to re-pull. |
| Provider-scoped thresholds | "provider:substr" outranks bare substring. Groq vs OpenRouter same slug, different window. |
| Proactive prune | Independent low trigger, not just inside compact() when over budget. |
| protect_last_n = 20 | CLI needs last 20 turns for repair. |
| Durable lock + watermark | try_acquire_compression_lock TTL 300s, MAX(id) watermark for concurrent tail preservation. |
| Compression telemetry | Per-attempt JSON with fit_margin, durations, aux route. |

**CrusorAI already has (Hermes parity achieved):** Lean tail, anchor index, verbatim user section, recovery footer, prompt-cache audit, usage-pressure state machine, bounded scan receipts, micro-compaction off by default.
**Gaps:** Provider-scoped thresholds, proactive prune, protect_last_n=20, context breakdown UI, frozen workspace snapshot, durable compression lock, micro-compaction opt-in, compression telemetry JSONL.

---

## 4. What CrusorAI Should Copy vs Not Copy

### Copy (constraint matches: one model, native tool calling, IDE we own, interactive turns)

| Decision | Source | Reason |
|---|---|---|
| Terse tool descriptions (≤90 chars) | Void (83 avg) | CrusorAI averages 570. Brevity is robust. |
| Keep dedicated search tools, terminal as fallback | OpenCode + Void | Terminal replaces 20 tools was wrong. |
| Text diff for edits, not JSON tool call | Aider | Function calling measured worse for code editing. |
| One worked example per tool family | Aider | 350 tok examples prevents 30–50% more editing errors. Cheaper than one retry cycle (~25k tok). |
| Compaction: hold precomputed summary, never rewrite prefix | OpenCode | OpenCode's comment names CrusorAI's exact failure. |
| Batch eligible tools concurrently + stream results | Void | Void's one-call rule is for streaming; CrusorAI can have batching AND visible progress. |
| File tree sent once at start, cached | Void | Buys one fewer cycle, stable prefix. |
| XML → terse descriptions | Void | 208 tok/tool for CrusorAI vs 33 for Void is the finding. |
| Provider-scoped model windows | Hermes | Same slug, different window across providers. |
| protect_last_n = 20 | Hermes | IDE needs more recent context than CLI's 6. |
| Cost budget as binding leg | CrusorAI's own fix order | Currently OFF by default — prompts die at iterations 20/20. |

### Not Copy (constraint mismatch)

| Decision | Source | Reason Not to Copy |
|---|---|---|
| Zero tool schemas | Aider | CrusorAI needs browser, device, preview, delegate tools. |
| Repo map as tool substitute | Aider | CrusorAI has live editor + tools; repo map adds fixed cost. |
| Six per-model prompts | OpenCode | CrusorAI has one model (glm-5.3-flash). |
| One tool call per response | Void | CrusorAI streams instead — batching is the efficiency lever. |
| 20k-char file tree in system msg | Void | CrusorAI has a live editor; tree is redundant. |
| Micro-compaction ON by default | Hermes | Breaks prompt cache every turn; opt-in only for long sessions. |

---

## 5. The "One Cable" Problem (from agent_core_blueprint.html)

It's a series of cables. One misconfigured cable causes cascading failure:

1. **Cost budget OFF by default** → only iteration cap (20) stops the loop
2. **Rich 6,151-token persona re-sent every cycle** → 639,704 tok ≈ $0.098/session just for system message
3. **7,509-token tool schemas re-sent every cycle** → 780,936 tok over 104 cycles (~26% of every cycle)
4. **Compaction rewrites prefix** → cache hit 53% → 39%; every cycle re-prefills at full price
5. **Blind retry on read_terminal_output failure** → model retries with no cause, ~90,000 tok/prompt wasted

**Result:** 84% of tokens discarded, $0.45 for 5 prompts, only 16% actual work.

If you copy CrusorAI's design, you inherit the same waste.

---

## 6. Fix Order — By Money Recovered (from agent_core_blueprint.html)

| # | Fix | Recovers | Pipeline |
|---|---|---|---|
| 1 | Give the agent its own budget (45) and make `AGENT_COST_BUDGET` the binding leg | the 84% currently thrown away | 8 loop control |
| 2 | Mask instead of rewrite on compaction (OpenHands condenser) | cache hit 39% → 80%+; ~17% of every prompt | 4 context |
| 3 | Trim the tool preamble: 36–48 schemas = 7,509 tok/cycle | ~26% of every cycle, ×104 | 5 model call |
| 4 | Cap tool results in tokens, not 12,000 chars | up to ~90k tokens per prompt | 7 tools |
| 5 | One stuck detector instead of three guards | runaway cycles | 8 loop control |

---

## 7. Files to Check Before Changing Anything

| File | What it controls |
|---|---|
| `docs/ref_blueprints.html` | Competitor comparison (verified numbers) |
| `docs/agent_core_blueprint.html` | CrusorAI's own measured waste |
| `docs/REFERENCE_DESIGN_REASONS_2026-11-01.md` | Why each repo decided what it did |
| `docs/HERMES_CONTEXT_ENGINE_DIFF_FOR_IDE.md` | Hermes gaps CrusorAI should fill |
| `docs/HERMES_PROMPT_ENGINEERING.md` | Prompt laws: byte-stable, role alternation, model-conditioned |
| `docs/HERMES_RUNTIME_AUDIT.md` | Test-5 runtime repair — autonomous persona, tool reduction |
| `docs/OPENCODE_SUBAGENT_PIPELINE.md` | OpenCode subagent architecture (task tool, background jobs, UI inspector) |
| `docs/OPENCLAUDE_CONTEXT_MINUTE.md` | OpenClaude context engine — no vector RAG, deterministic PageRank |
| `src/prompts/claude_persona.py` | The 6,151-token persona (system_persona()) |
| `src/tools/toolsets.py` | Always-on tool waist (36 tools bound per cycle) |
| `src/agents/runtime_profile.py` | Capability classification (pulls in more tools per task type) |
| `src/context/compaction.py` | Compaction that rewrites prefix (HistoryCompactor) |
| `src/bridge/turn_watchdog.py` | Silence-based watchdog (600s), not cost-based |
| `src/config/settings.py` | PROVIDER_SAFE_LIMIT, LLM_MODEL, LLM_PROVIDER |
| `src/context/model_budgets.py` | Context window resolution (256K default fallback) |
| `src/context/token_budget.py` | Token counting and trimming |
| `scripts/ref_blueprints.py` | Regenerates ref_blueprints.html from ref_verify.json |
| `scripts/agent_core_blueprint.py` | Regenerates agent_core_blueprint.html |
| `docs/ref_verify.json` | Source-of-truth measurements for all 4 harnesses |

---

## 8. Regenerate the Blueprints

```bash
# Step 1: Measure the repos (requires network)
python3 scripts/ref_verify.py

# Step 2: Draw from the measurement
python3 scripts/ref_blueprints.py
```

Outputs: `docs/ref_blueprints.html` and `docs/ref_blueprints.svg` (plus agent_core variants).

---

**Bottom line:** CrusorAI inherited ideas from Aider, OpenCode, and Void but named no constraint of its own. The fix is not to copy any one repo — it's to state CrusorAI's constraint (one model, native tools, IDE, interactive turns) and design every lever around that. Start with fix #1 (cost budget as binding leg) — that's the cable that's not set up correctly.
