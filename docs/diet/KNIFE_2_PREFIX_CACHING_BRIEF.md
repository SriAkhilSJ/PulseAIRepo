# Knife #2 Knowledge Brief — System-Prompt Split + Provider Prefix Caching

**Status:** `Knife #1 shipped (05ff135e)` — you asked to understand Knife #2 without shipping it yet. This brief is read-only: no code change.

**One-sentence promise:** Keep the same bytes hitting the same offset every turn so the provider can bill the prefix from cache instead of re-reading it — same answer, ~50-90% cheaper on input tokens after the first turn, and measurably faster.

---

## 1. What Knife #2 actually is

Knife #1 shrank *what* we send (tool schemas 14,413 → 4,182 tokens/call, -71%). Knife #2 shrinks *what we pay for* by making the survivor bytes **cache-hit**.

Two halves:

1. **System-prompt split (Crusor-side, already built).** The system prompt is rendered once per session and frozen as three tiers:
   - `stable` — identity, persona, skill index shape, tooling contracts, static environment hints (never changes mid-session)
   - `context` — `SOUL.md`, workspace snapshot (`git` + file tree head), skill index content, per-session model/platform hints (changes only on `cwd`/session reset/compaction)
   - `volatile` — time, turn-local memory, ephemeral steer channel note (changes every turn but pinned to the tail)

   Ordering is the cache: `stable → context → volatile → history`. A rebuild that only touches the tail keeps the long prefix byte-identical.

2. **Provider prefix caching (provider-side, opt-in).** Modern inference providers cache the KV state for a prefix that re-appears verbatim at the start of a request:
   - **Anthropic** — explicit `cache_control: {type: "ephemeral"}` on up to 4 blocks; 5-min (default) or 1-hr TTL; hits billed `cache_read_input_tokens` at 10% of base input, writes billed at +25% once per block.
   - **OpenAI** — automatic; any prompt ≥1,024 tokens that re-uses a ≥1,024-token prefix hits after ~5 min warm-up; cached tokens reported in `usage.prompt_tokens_details.cached_tokens` (50% discount).
   - **Google Gemini (implicit caching)** — automatic; threshold ~1,024 tokens; requires deterministic ordering; reported via `cachedContentTokenCount`.
   - **Groq / Together / Fireworks / other OpenAI-compatible via LiteLLM** — mixed: some pass `cache_control` through, some strip it; a `400` on tool-result parts is a known footgun (our `tool_part_markers` flag exists for this).

Our `src/context/prompt_cache_plan.py` ports Hermes's 4-breakpoint plan (`static prefix + last tool + last 2 endpoints`) into LangChain `BaseMessage.additional_kwargs` so the same code path can decorate for Anthropic *or* do nothing for OpenAI/Gemini and still benefit from their automatic path.

---

## 2. Why it matters — the ledger math

From the evidence trace (`diagnostics/telemetry-evidence/calls-2026-10.jsonl`, still the baseline until Knife #1 gets fresh runs):

- 21 calls, 616k input billed, $0.0136 — **69% static share** after the denominator fix (`b8f068f2`). That's the provider re-billing the same prefix every turn.
- Knife #1 alone: 288k → 84k schema tokens over 20 turns (saved 204k, -71% per call). Wall budget now fits 600k without a raise.
- Knife #2 alone (orthogonal): if the stable+context prefix is ~8–12k tokens and hits for 20/21 turns, Anthropic bills ~1× write + 20× 10% reads vs 21× full; OpenAI bills 50% for hits after warm-up. Rough model:
  ```
  Before: 21 * 12k = 252k static tokens @ 100%
  After:  1 * 12k @125% (Anthropic write) + 20 * 12k @10% = 15k + 24k = 39k  → 85% saving on that slice
  OpenAI: 1 * 12k @100% + 20 * 12k @50% = 132k → 48% saving
  ```
  Combined with Knife #1, the per-task input falls from ~616k toward ~250–300k — not by being clever about tokens, but by not paying twice for bytes we already taught.

Latency: cached prefix skips recompute — Anthropic notes ~30–50% faster TTFT on long prefixes; our TTFT is already dominated by the uncached re-parse.

---

## 3. What Crusor already ships (you don't need to rebuild this)

| Piece | File | What it does | Why it exists |
|---|---|---|---|
| Stable prefix render & freeze | `src/prompts/hermes/system_prompt.py:build_system_prompt_parts` + `src/context/prompt_cache_boundary.py` | Renders once, registers `register_stable_prefix(stable)`; later `find_stable_prefix(content)` can split a fused system message back into `[{stable, cache_control}, {volatile}]` | Hermes law #1: build once per session |
| Session-scoped view cache | `src/prompts/hermes/session.py:view_for_session` / `system_prompt_for_session` | Keyed `thread_id:cwd:autonomous` (64-slot LRU), records `_cached_system_prompt`; `invalidate_session` only on compaction/reset; `CRUSORAI_STABLE_PREFIX=off` kill switch | No long-lived `AIAgent` object in LangGraph — the ContextEngine *is* the agent |
| 4-breakpoint decorator | `src/context/prompt_cache_plan.py:build_prompt_cache_plan` | Places `cache_control: {type:"ephemeral"}` on `SystemMessage(0)` (stable) + last tool result + last 2 `completed_transaction_endpoints`; handles `static_system_prefix` split, LiteLLM tool-part quirk | Port of `agent/prompt_caching.py` |
| LLM proxy passthrough | `src/llm/factory.py:RetryLLMProxy._prepare_messages` | Calls `build_prompt_cache_plan(messages_arg, provider, model)` before send; never raises; preserves `request_snapshot` for audit | Provider sees stable bytes at stable offsets |
| Failover preservation | `src/context/cache_preservation.py` + `src/context/prompt_cache_audit.py` | Strips or re-decorates `cache_control` on provider change; records `stable_prefix_invalidations` and whether prefix regressed | Provider switch must not silently bust cache |
| Ledger visibility | `src/context/token_tracker.py` + `src/telemetry/call_ledger.py` | `cached_tokens` from `usage_metadata.input_token_details.cache_read` / `prompt_tokens_details.cached_tokens`; `TokenTracker.record_call` → `call_ledger` `prompt_cache` stats; `[ai_node] prompt cache: N of M (P%)` line | Law-1 visibility: you can't tune what you can't see |
| Audit & tests | `src/tests/test_hermes_prompt_session_cache.py`, `test_prompt_cache_audit.py`, `test_cache_preservation.py` | Byte-stability pins, LRU eviction, kill switch, regression detection (>5% + >2k tokens shrink = incident) | Guard against "we cached nothing and didn't notice" |

Current default: `CRUSORAI_PROMPT_CACHE=off` (opt-in) and `CRUSORAI_STABLE_PREFIX=on`. In practice this means **we already earn automatic OpenAI/Gemini caching** (ordering alone is enough) but **not explicit Anthropic/manual caching** until you flip the env.

---

## 4. What turning Knife #2 "on" actually changes (the implementation plan — for later)

No new concept, just tightening the dials and making Knife #1's tiny tool set cache better:

1. **Enable the explicit path for the right providers.**
   ```
   CRUSORAI_PROMPT_CACHE=1
   CRUSORAI_PROMPT_CACHE_CUSTOM=1   # if Velona is OpenAI-compatible and honors cache_control passthrough
   ```
   Leave `STABLE_PREFIX=on` (you already have it). Verify `tool_part_markers` for your route — Velona via `https://velona.in/v1` is OpenAI-compatible; tool-result part markers must be off for LiteLLM-shaped routes or you get the `400` you already guarded.

2. **Make tool schemas part of the stable prefix, not the volatile tail.**
   Knife #1 already helps: 22 schemas in `SystemMessage(0)` at a fixed order (`_TOOLS_BY_NAME` registry order) means the same 4,182 tokens occupy the same bytes every turn. Without this, the provider sees "same system prompt, different tools array" and the prefix breaks. The remaining work is only to ensure `prompt_cache_plan`'s `planned_tools[-1].cache_control` survives your proxy's serialization (it does via `RequestSanitizer` today).

3. **Pin the volatile tail to the tail.**
   Time, plan state, and the Knife #1 `TOOL DISCOVERY` banner are already in the volatile suffix. Don't let per-turn file lists or skill deltas leak into `stable`. The existing `stable_prefix_invalidations` counter + `prompt_cache_audit` will fire if you do.

4. **Tune TTL, not code.**
   Anthropic 5m is the default (`_TTL = "5m"`). For Velona's `glm-5.3-flash` (1,049k window, cheap input $0.018/M) the win is latency, not dollars; for any Anthropic pass-through the win is both. Only bump to `1h` for Qwen-class routing (today's `effective_cache_ttl` already gates it).

5. **Measure, don't believe.**
   The ledger now has `tool_names` + `tools_schema_tokens` per call and `prompt_cache: {cached_tokens, prompt_tokens}` per turn. After enabling, expect:
   - `input_tokens` flat, `cached_tokens` rising after turn 1
   - `avg_tools_schema_tokens` flat (~4,182)
   - `s/step` down 15–30% on cached turns
   - No `stable_prefix_invalidations` mid-task (compaction only)

---

## 5. How to evaluate it (the "score every cut" promise)

Use the existing ledger + the `diagnostics/telemetry-evidence` harness — no new infra:

- **Tokens/call:** `avg_tools_schema_tokens` (Knife #1) vs `cached_tokens / prompt_tokens` (Knife #2). Target: Knife #2 adds 0 to `tools_schema_tokens`, adds 40–85% to `cached_tokens` hit rate by call 3.
- **s/step:** `wall_s` from `TokenTracker` + `turn_token_usage`. Target: -15–30% on turns 2–N vs turn 1; p50 TTFT down.
- **Task success:** verified/unverified from `finalize_node` + `gates` — must not move. A system-prompt split that changes meaning is a bug, not a diet.
- **Audit:** `prompt_cache_audit.CachePrefixAudit` will emit `stable prefix REGRESSION` if the stable head shrinks >5% mid-session. That line is the "did Knife #2 break the prompt" alert.

Run the same `verifdemo` / `testfresh` task once with `CRUSORAI_PROMPT_CACHE=off` and once with `=1`; the JSONL diff is the A/B.

---

## 6. Provider nuances you will hit

- **Anthropic (if you ever route there).** 4 blocks max, last block must be the freshest turn-local data. Our plan already puts them on `system(0).stable + last tool + last 2 endpoints`. Exceeding 4 silently drops the oldest — which is the stable one you wanted most. Don't add a 5th.
- **OpenAI (Velona today).** No markers needed; `order = cache`. The only way to bust it is to mutate the stable head (e.g., re-sorting tools, re-rendering the skill index). Knife #1's fixed registry order already fixes the first; `skills_index` is part of `stable` for this reason.
- **Gemini implicit.** Same as OpenAI, threshold ~1k. The fused `SystemMessage` (`_fuse_system_head` in `chat_graph.py:2050`) is intentional — Gemini counts one system block more reliably than N.
- **LiteLLM / generic custom.** Tool-result `content: [{text, cache_control}]` is rejected. Our `is_litellm_route` + `tool_part_markers=false` already steers the breakpoint off tool results onto the nearest human/assistant. Don't override it.

---

## 7. Relationship to the other knives

- **Knife #1 (shipped):** reduces the prefix that *needs* to be cached. Caching 4k well is strictly easier than caching 14k well.
- **Knife #2 (this):** makes the reduced prefix *actually hit*. They compose: 71% smaller × 85% cached = ~96% less billed static on Anthropic, ~71% + 48% on OpenAI.
- **Knife #3 (budget reshape + earlier compression):** becomes viable *after* #2 because a cached 300k turn is survivable where an uncached 616k turn tripped `AGENT_TOKEN_BUDGET=600k`. Don't raise the budget until #2 proves the head is stable — otherwise you pay more to re-bill the same prefix longer.

---

## 8. Risks & non-goals

- **Risk: false sharing (cache key = thread_id:cwd:autonomous).** Two IDE sessions in the same `cwd` with different `thread_id` must not share a stale stable prefix. The 64-slot LRU + `invalidate_session` on `thread_id` change already isolates them.
- **Risk: skill installs mid-session.** `skill_manage` mutates `stable`. The `skills_hub` path already calls `clear_skills_system_prompt_cache` — which forces a one-time rebuild. Expected, not a regression.
- **Risk: tool schema churn.** If you later add `execute_code` back to the core, every cached prefix busts once and re-warms. That's a one-turn tax, not a leak.
- **Non-goal:** per-message TTL tuning, provider-specific SDKs, or "smart" eviction. The 4-block, 5m-default plan is upstream's tested shape — keep it.

---

## 9. What you can do right now (without code)

```bash
# 1. Confirm today's baseline (no explicit caching, automatic only)
PYTHONPATH=/tmp/wt3 /tmp/testenv/bin/python -m src.telemetry.call_ledger --json | jq '.prompt_cache'
# expect: cached_tokens ~0, markers 0 (explicit off), but stable head byte-stable across calls

# 2. Flip explicit caching for one Velona run and compare
CRUSORAI_PROMPT_CACHE=1 CRUSORAI_PROMPT_CACHE_CUSTOM=1 \
  PYTHONPATH=/tmp/wt3 /tmp/testenv/bin/python -m src.telemetry.call_ledger --json | jq .

# 3. Watch the in-flight signal
# [ai_node] prompt cache: 11,200 of 12,800 (88%)  — good
# [ContextEngine] stable system prefix invalidated — bad mid-task, find the mutator
```

When you're ready to ship Knife #2, the change is a one-line env flip + (optionally) teaching `prompt_cache_plan` that Velona's route honors `cache_control` — everything else is already in the tree and tested.

---

*Prepared 2026-10-22 on `arena/0d4596c3-pulseairepo` at `05ff135e` (Knife #1). No behavior change in this document; verify by `git diff --stat HEAD` (this file only if you keep it).*
