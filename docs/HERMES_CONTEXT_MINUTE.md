# Hermes Context Engine — Every Minute Thing

**Source:** `D:\hermes\hermes-agent` — exhaustive file:line audit 2026-08-30. This is the verbatim minute-by-minute inventory to renovate PulseAI.

---

## 1. `agent/context_engine.py:1` — Pluggable ABC

**Role:** One active engine, config `context.engine="compressor"` default, plugins `plugins/context_engine/<name>/`. Engine owns compaction decision + execution + tools + token tracking.

| Constant | Line | Value |
|---|---|---|
| `MEMORY_CONTEXT_MAX_CHARS` | 34 | 6000 |
| `_MEMORY_CONTEXT_HEAD_CHARS` | 35 | 4000 |
| `_MEMORY_CONTEXT_TAIL_CHARS` | 36 | 1500 |
| `TRUNCATION_MARKER` | 37 | `\n...[memory provider context truncated]...\n` |
| `threshold_percent` | 121 | 0.75 |
| `protect_first_n` | 122 | 3 (+ system, PR #13754) |
| `protect_last_n` | 123 | 6 |

**Interface:** `update_from_response(usage)` canonical buckets `input_tokens/cache_read_tokens/reasoning_tokens` `133`, `should_compress(prompt_tokens)` `147`, `should_compress_info -> (bool,str|None)` anti-thrash `149`, `compress(messages,current_tokens,focus_topic,force,memory_context)→List[Dict]` `163`. Optional `prune_tool_results_only:194` (cheap low trigger), `select_context:215` per-turn selection-not-shrink (request-only, before cache-control), `on_turn_complete:281` ingestion, `should_compress_preflight/should_defer`, `has_content_to_compress`, `on_session_start/end/reset` (resets token tracking), `get_tool_schemas/handle_tool_call`, `get_status:444` clamp `-1→0`, `update_model:470` `threshold_tokens=int(context_length*threshold_percent)` via `resolve_model_threshold` substring match.

**Helpers:** `sanitize_memory_context:40` `redact_sensitive_text(force,redact_url_credentials)+head/tail`, `automatic_compaction_status_message:56` respects `emit_automatic_compaction_status`.

---

## 2. `agent/context_compressor.py:1` — Built-in Compressor

**Core:** Auxiliary LLM summarizer, protects head/tail + token-budget tail, tool-prune pre-pass, iterative summary, scaled budget, ghost-skill defense, lean tail.

*Pinned route* `60:141` — `ContextVar[Dict]` `_SUMMARY_ROUTE_PIN:85`, `_PINNED_ROUTE_FIELDS:92` (provider,model,base_url,api_key,api_mode,timeout), `pin_summary_route` CM, `take_pinned_summary_route` single-use.

**Key constants** `197:971`:
- `SUMMARY_PREFIX:200` REFERENCE ONLY, latest user wins, reverse signals, memory authoritative, tools active.
- `LEGACY_SUMMARY_PREFIX 235`, metadata keys `250` `_compressed_summary` underscore-prefixed for wire sanitizers, `SUMMARY_END_MARKER 425`, `_HISTORICAL_SUMMARY_PREFIXES 590` byte-pinned, `_MIN_SUMMARY_TOKENS 730=2000`, `_SUMMARY_RATIO 732=0.20`, `_CEILING 736=10000`, `_SUMMARY_INPUT_MAX_CHARS 755=160000`, `_PLaceholder _PRUNED_TOOL_PLACEHOLDER`, `_PRUNE_MIN_CHARS 763=200`, `SKILL_PRUNED_MARKER_PREFIX 806="[SKILL_PRUNED:"`, `_SKILL_VIEW_PRUNE_MIN 5000`, `LEAN_TAIL_FLOOR 952=10000 CAP 25000`, `_LEAN_USER_BUDGET 958=24000`, etc.

**Helpers:** `_fresh_compaction_message_copy:283`, `_template_visible_role:302` (Mistral alternation), `_strip_persistence_markers:331`, `_prune_stale_reasoning_replay:350`, `salvage_grown_transcript:501`, `_redact_compaction_text`, `_estimate_msg_budget_tokens:1516`, `resolve_model_threshold:2129`.

**Class** `ContextCompressor:2155` `name="compressor"` `on_session_reset:2170` resets 15+ fields.

---

## 3. Prompt Caching Trio

**`prompt_caching.py:1`:** 4-breakpoint Anthropic (static+end-system+last2 non-system), TTL 5m/1h. `_apply_cache_marker:37`, `_can_carry_marker:92`, `ALIBABA_FAMILY_PROVIDERS 127`, `is_qwen_model 135`, `effective_cache_ttl 145`, `_apply_system_cache_markers 170`, `strip_anthropic_cache_control 232`, `build_prompt_cache_plan 385`.

**`prompt_cache_boundary.py:1`:** Builder-declared `register_stable_prefix:56` / `find_stable_prefix:69` LRU 32/4MiB.

**`prompt_cache_scope.py:1`:** Rotation-stable scope via `SessionDB.get_compression_lineage()[0]` + memo per `(session_id, db)` `43`.

---

## 4. `agent/system_prompt.py:1` — Three Tiers

Once-per-session, `stable/context/volatile` joined `\n\n`. Stable = SOUL/DEFAULT_IDENTITY + HERMES_HELP + TASK_COMPLETION + PARALLEL_TOOL_CALL + MEMORY/SESSION_SEARCH/SKILLS/KANBAN + STEER_CHANNEL + TOOL_USE_ENFORCEMENT + GOOGLE_GUIDANCE + execution_guidance_text. Context = workspace snapshot + system_message + `build_context_files_prompt`. Volatile = skills index front + memory blocks + plugin `after_memory` frozen `_frozen_plugin_prompt_sections:191` + timestamp `Conversation started: WEEKDAY, Month DD, YYYY (zone UTC)` date-only stable. Exports `build_system_prompt_parts:341`, `build_system_prompt:910`, `invalidate_system_prompt:939`, `reconstruct_static_prefix:951`.

## 5. `agent/prompt_builder.py:1`

`_scan_context_content:58` BOM strip + `scan_for_threats(scope="context")` → `[BLOCKED]`, `_find_git_root:88`, `_find_hermes_md:104`, constants `DEFAULT_AGENT_IDENTITY:150`, `TASK_COMPLETION:425`, `PARALLEL_TOOL_CALL:468`, `STEER_MARKER 642`, `PLATFORM_HINTS 748`, `CONTEXT_FILE_MAX_CHARS 1414=20000`, dynamic cap `1429 0.06*window*4` floor 20k ceiling 500k.

## 6. `agent/conversation_compression.py:1`, `native_compaction.py:1`, `compaction_display.py:1`

Compression helpers, native `gpt-5.6` only `62` `compaction` with `compact_threshold 200000` `58` clamped `LOCAL_TRIGGER_SAFETY_MARGIN 8192`, display hides pure handoff.

## 7. `agent/memory_manager.py:1` + `memory_provider.py:1`

`MemoryManager:403` one external provider, `add_provider:443`, `prefetch_all:564` Thread 8s, `sync_all:714` serialized DaemonThreadPoolExecutor. `RecallStatus 54`, `is_trivial_prompt:90`, lifecycle `on_pre_compress` v2 checkpoint.

## 8. `agent/coding_context.py:1`, `subdirectory_hints.py:1`, `turn_context.py:1`

Coding posture `RuntimeMode/ContextProfile 272`, `CODING_AGENT_GUIDANCE:217`, `build_coding_workspace_block:881` git+projectFacts. `SubdirectoryHintTracker:72` `AGENTS.override.md` first, `MAX_HINT_CHARS 8000`. `TurnContext 429` prologue order: recover rotated session → idle/preflight compaction → `prefetch_all` → `api_content`.

## 9. `tools/threat_patterns.py:1`, `agent/file_safety.py:1`, `agent/redact.py:1`

`MAX_SCAN_CHARS 65536 53`, filler `(?:\w+\s+){0,8} 59`, `_PATTERNS 63` all/context/strict, `INVISIBLE_CHARS 141` 17 chars. `file_safety` write deny `~/.ssh/authorized_keys` + read block `auth.json/.env/mcp-tokens/browser-profile` + cross-profile/sandbox-mirror guards. `redact` `<18→*** else 6...4`, 50 prefix patterns, strict URL modes.

## 10. `agent/verification_evidence.py:1`, `error_classifier.py:1`, `error_surface.py:1`, `bounded_response.py:1`, `deadline.py:1`, `iteration_budget.py:1`

Evidence ledger SQLite `verification_evidence.db` `63` + `classify_verification_command:516` + `mark_workspace_edited:677`. Error taxonomy `FailoverReason 20` + pipeline `classify_api_error:770` 0 plugin→1 provider→2 status→3 code→4 message→5 SSL→6 disconnect+large. Layer `provider/endpoint/streaming/auth/billing/gateway/runtime/disk 37`. Deadline `MAX_SAFE_TIMEOUT_S 31536000` + `SuspectableBackend`, `IterationBudget 500 parent/50 subagent`.

---

*Use this as checklist to renovate PulseAI — every constant above is a port candidate. See `docs/PULSEAI_CONTEXT_BENCH.md` for gap table.*
