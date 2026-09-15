# Hermes vs CrusorAI Context Engine — Diff for AI IDE Agent

**Date:** 2026-09-12
**Source:** `NousResearch/hermes-agent @ main` vs `PulseAIRepo @ 932db0de`
**Perspective:** What does an AI IDE agent need that Hermes CLI already solved?

## TL;DR

Crusor already ports ~70% of Hermes context machinery (lean tail, anchor index, verbatim user section, recovery footer, prompt-cache audit, usage-pressure state machine, bounded scan receipts). **Gaps are in operational hardening** that Hermes learned from production: proactive prune, micro-compaction, durable lock + watermark, context breakdown, provider-scoped thresholds, frozen workspace snapshot.

Hermes is a **CLI coding agent** with terminal + skills + memory provider. Crusor is an **IDE agent** with repo_map + chunk_index + git_context + editor intelligence. The IDE needs *more* context, not less — so we must keep Crusor's IDE layers and add Hermes's hardening.

## Hermes architecture

### ContextEngine ABC `agent/context_engine.py`
- `name`, `last_prompt_tokens`, `threshold_tokens`, `context_length`, `compression_count`
- `threshold_percent=0.75`, `protect_first_n=3`, `protect_last_n=6`, `emit_automatic_compaction_status=True`
- Methods: `update_from_response()`, `should_compress()`, `should_compress_info()`, `compress()`, `prune_tool_results_only()`, `select_context()`, `on_turn_complete()`, `should_compress_preflight()`, `should_defer_preflight_to_real_usage()`, `get_status()`, `update_model()`
- `sanitize_memory_context()` + `automatic_compaction_status_message()`
- `resolve_model_threshold()` with **provider-scoped keys** `"provider:substr"` where scoped outranks bare of same length.

### ContextCompressor `agent/context_compressor.py` (default engine)
- Defaults: `threshold_percent=0.50`, `protect_first_n=3`, `protect_last_n=20`, `summary_target_ratio=0.20`, `tail_mode=lean`
- Lean tail: `2.5% of window clamped 10k-25k`, `KEEP_TOOL_ROUNDS=6`, `DEMOTE_MIN_CHARS=1500`
- 4-pass prune:
  1. dedup byte-identical tool results (keep newest)
  2. summarize non-tail tool results > min_prune_chars
  3. truncate oversized tool_call args inside JSON
  3.5 retire images keep newest 3
  4. pressure demote tail when protected region > 1.5*budget (keep 3 recent)
- Summary generation: iterative (previous summary + new turns), aux LLM (janitor) with fallback_chain pin via ContextVar, single call per attempt, even sampling 8 slices across region when oversize (coverage for session log)
- Lean sections: verbatim user messages newest-first (24k chars budget), anchor index (regex harvest PRs/commits/files/errors), detailed session log (4k tokens, identifier-preserving), recovery footer with session_search hint, pruned skills markers `[SKILL_PRUNED: ...]`
- Failure handling: auth/quota/network/truncated/empty_content → abort preserve unchanged, timeout ladder 60/300/900, feasibility skip when middle <10% threshold after ineffectiveness strike, anti-thrash recovery 300s (1 probe), structural no-op backoff 300s
- Durable: `try_acquire_compression_lock` TTL 300s, watermark MAX(id) for concurrent tail preservation, `archive_and_compact` + `stamp_db_persisted_markers`
- Telemetry: per-attempt JSON with protected_head/middle/tail tokens, aux prompt tokens, fit_margin, chunking, durations

### ConversationCompression `agent/conversation_compression.py`
- `CompressionCommitFence`: fence timeout vs commit boundary, progress hook, heartbeat, deadlock detection, holder-qualified lease release
- `run_compress_context_with_progress_timeout`: idle timeout 120s, total ceiling 600s, bounded pool 4 workers, admission cap, retry once on fallback_chain via `pin_summary_route`
- Preflight compaction, idle compaction (opt-in), micro-compaction integration, todo snapshot folding, user anchor restoration

### Micro-compaction `agent/micro_compaction.py`
- Rolling per-exchange summary OFF by default (breaks prompt cache every turn)
- Cursor + rolling summary, defrag threshold 2k tokens, cadence every N turns
- Each pass breaks cache once — tradeoff for long sessions

### System prompt `agent/system_prompt.py`
- Built once per session, reused → prompt-cache
- 3 tiers: stable (identity, guidance, env hints, coding brief, platform hints), context (caller system_message, context files), volatile (skills index, memory, USER.md, external memory provider, timestamp)
- Frozen workspace snapshot pinned per session on `agent._frozen_workspace_snapshot` keyed by cwd (gateway serves many cwds) — keeps stable prefix byte-stable across git moves
- Plugin section frame coarse anchor in volatile tail for resume reconstruction
- Timestamp date-only for cache stability, plus "as of rebuild" second line for long-lived sessions

### Context breakdown `agent/context_breakdown.py`
- Cursor-style breakdown: system_prompt, tool_definitions, rules, skills, mcp, subagent_definitions, memory, conversation
- Glyph grid 20x5 = 100 cells, per-category lines, per-skill/toolset tables for `/context all`

## Crusor current

### What Crusor already has (Hermes parity achieved)
- `src/context/engine.py`: ABC with same contract, `sanitize_memory_context`, `automatic_compaction_status_message`, `resolve_model_threshold` (bare only)
- `src/context/context_engine.py`: layered engine (repo_map, relevant_chunks, git_context, task, plan, progress, recovery, replan, attempt_history, long_term_memory, tool_memory, ambiguity, tone, quality, conventions, memory_validation, reflections, skills), task-aware budget ratios, differential cache with VOLATILE_LAYERS, session-scoped registry LRU 128, RLock, shared ContextBudget, UsagePressure (75% threshold, 60% rearm), prompt-cache audit with cache_break detection, feedback memory JSONL, history_shaper with HistoryCompactor shared, lean tail 10k-25k, anchor index, verbatim user, recovery footer
- `src/context/compaction.py`: D22 Hermes pack prune-first, protected head (first complete turn) + tail 20k tokens, iterative aux summary, anti-thrash, image retirement, mutation payload compaction, salvage_grown_transcript, lean helpers
- `src/prompts/hermes/session.py`: stable prefix cache keyed by thread_id, LRU 64, invalidated only on compaction/reset, 3-tier build via `system_prompt.py`

### Gaps for IDE agent

| Hermes feature | Crusor status | IDE impact |
|---|---|---|
| Provider-scoped threshold `"provider:substr"` | Missing — only bare substring longest wins | Groq vs OpenRouter same slug different window (e.g. astra 272K on Codex vs full on OR) leaks |
| `proactive_prune_tokens` independent low trigger | Partial — prune runs only inside `compact()` when over budget, not as separate cheap path | IDE tool loops (read_file x10) bloat transcript long before 75% threshold |
| `protect_last_n=20` vs 6 | Crusor uses 6 — keeps too little recent tool output | IDE needs last 20 turns (file edits + terminal) for repair |
| Context breakdown by category | Missing — only `get_status()` with usage_percent | Agent panel can't show budget bar breakdown (system vs tools vs skills vs conversation) |
| Frozen workspace snapshot pinned by cwd | Missing — `repo_map` disabled by default, when enabled rebuilds every turn busting cache | Git moves invalidate stable prefix unnecessarily |
| Durable lock + watermark | Missing — SqliteSaver WAL but no compression lock | Dashboard double-fire same thread can interleave compaction + flush |
| Micro-compaction rolling summary | Missing — no per-exchange compaction | Long IDE sessions (100+ turns) keep growing without hitting 75% |
| Compression telemetry JSON | Partial — `compaction_stats()` counters but no per-attempt fit_margin, durations, aux route | No observability for prod cost analysis |
| Skill pruned markers `[SKILL_PRUNED: ...]` | Partial — `skills` layer but no ghost-skill defense | Skill instructions pruned silently, model thinks skill loaded |
| Prompt-cache boundary registry for skill/webhook invocations | Missing — `register_stable_prefix` exists but not for skill invocation tail | Skill turns miss cache breakpoint |
| `select_context` as retrieval hook | No-op — retrieval via layers only | IDE could inject repo_map/chunks per-request based on budget instead of pre-building layers |

## Phased implementation plan for CrusorAI IDE

### Phase 0: Audit (done) — this doc

### Phase 1: Low-risk parity fixes (no LLM, no behavior change)
- [ ] Upgrade `resolve_model_threshold` to provider-scoped ranking (Hermes `provider:substr` outranks bare)
- [ ] Align `protect_last_n` default 6 → 20, `threshold_percent` default stays 0.75 but document why (IDE needs more context than CLI's 0.50)
- [ ] Implement real `prune_tool_results_only` in `ContextEngine` (deterministic tool-result prune, returns count) + expose `proactive_prune_tokens` env
- [ ] Add `context_spend_cap`/`history_spend_cap` already exists — verify wiring

### Phase 2: Observability + UI value (IDE panel)
- [ ] Port `context_breakdown.py` → `src/context/context_breakdown.py` with categories: system_prompt, tool_definitions, rules, skills, memory, conversation, repo_map, relevant_chunks, git_context
- [ ] Extend `get_status()` to include breakdown + `prompt_cache` hit_rate + `compaction` stats + `stable_prefix` sizes
- [ ] Wire breakdown to bridge protocol `context_status` event + webview budget bar component
- [ ] Add compression telemetry JSONL sink `CRUSORAI_COMPRESSION_TELEMETRY_JSONL`

### Phase 3: Prompt-cache stability (cost)
- [ ] Frozen workspace snapshot: pin `coding_workspace_parts` per thread_id + cwd key, replay on rebuild unless cwd changed
- [ ] Ensure `invalidate_system_prompt` only on compaction/reset (already) + on workspace switch
- [ ] Add `register_stable_prefix` for skills index block boundary (Hermes `prompt_cache_boundary.py`)
- [ ] Test: cache audit `prefix_reached_history_pct` must stay >90% across git edits

### Phase 4: Long-session hardening (concurrency)
- [ ] Port `CompressionCommitFence` (simplified) → `src/context/compression_fence.py` with lock + progress + deadline
- [ ] Add `try_acquire_compression_lock` to session DB wrapper (or in-memory for MemorySaver path)
- [ ] Implement micro-compaction mixin OFF by default (`CRUSORAI_MICRO_COMPACTION=on` to enable) — rolling summary, cursor, defrag
- [ ] Add stall guard + fallback chain env `CRUSORAI_COMPRESSION_FALLBACK_CHAIN`

### Phase 5: IDE-specific `select_context`
- [ ] Implement `select_context` in `ContextEngine` to inject `repo_map`/`relevant_chunks` per-request based on `budget_tokens` (instead of only layers)
- [ ] Add `on_turn_complete` to index completed turns into `chunk_index`/`session_index` for next request
- [ ] Wire editor context (dirty files, diagnostics, symbols) via `select_context` when `CRUSORAI_IDE_CONTEXT=on`
- [ ] Verify: ASK mode must still send no tools, tool pairs must survive compaction

Each phase: provider-free tests, `tsc -b` 0, `npm test` green, no token spend.

## Decision log

- Keep Crusor's 17 IDE layers — Hermes has none of repo_map/chunks/git_context/conventions. IDE needs them.
- Keep `threshold_percent=0.75` for IDE (more context) vs Hermes 0.50, but support per-model overrides for small models.
- Micro-compaction OFF by default — same as Hermes, breaks prompt cache every turn, only for opt-in long sessions.
- No full port of `conversation_compression.py` daemon pool — Crusor runs in Electron utility process, not gateway. Simplified fence suffices.
