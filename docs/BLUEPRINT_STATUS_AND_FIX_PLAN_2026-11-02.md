> **Update:** Subsequent implementation and validation are documented in
> [CONTINUOUS_TOOL_DISCOVERY_FIX_2026-11-02.md](CONTINUOUS_TOOL_DISCOVERY_FIX_2026-11-02.md).
> The earlier statements below describe the status before those changes.

# Blueprint status and safe-fix plan

## Answer: is the blueprint problem fixed?

**Not yet end to end.** Continuation over internal graph boundaries has provider-free proof and several context/verification mechanisms were previously implemented. But the latest live ecommerce run remained incomplete and its measured per-request overhead was higher than the older same-prompt GLM run. The older and newer runs used different hosts/settings, so this is not a controlled A/B and does not prove that continuity caused the increase.

| Metric | Earlier GLM run | Latest live GLM run | Interpretation |
|---|---:|---:|---|
| Requests | 52 | 55 | Both incomplete; not equivalent controlled conditions. |
| Provider input tokens | 1,980,730 | 2,449,090 | Latest +23.6%; repeated input includes cache hits. |
| Input per request | 38,091 | 44,529 | Latest +16.9%; mixed task/context/schema costs. |
| Provider output tokens | 55,904 | 64,398 | Latest +15.2%. |
| Estimated cost | ~$0.3251 | ~$0.3996 | Latest +22.9%; settings/host differ. |
| Model receipt time, summed | 523.35 s | 479.36 s | Faster here; not a controlled latency improvement. |
| Verified complete website | No | No | Neither run demonstrates success. |

Historical blueprint estimates (e.g. ~7,939 fixed tokens per autonomous cycle and ~13,660 desktop) are configuration-specific estimates, not the provider-measured total above. The actual latest parent received **67 tool schemas / 60,809 schema characters on requests 3–55**; the older model estimates and newer actual schemas are not directly equivalent. The latest first request contained 17,923 provider input tokens, including task/context and schema, not persona alone. [Detailed causal analysis](CONTINUOUS_AGENT_ROOT_CAUSE_2026-11-02.md).

## Fixes applied in this pass

1. **Tool-call/result pairing:** `src/llm/request_sanitizer.py` no longer drops a distinct result and rewrites an earlier call to the later call ID when two outputs are identical. It retains both IDs and bodies. Retaining full content is deliberate: the proxy can trim *after* sanitization, so a short reference to an earlier result could lose its referent. This restores correctness but may send more duplicate text; it is not a token-saving claim.
2. **Advisory progress accounting:** `src/runtime/tool_middleware.py` recognizes a limited set of simple read-only shell commands only for progress bookkeeping, not authorization. The `terminal` and `run_terminal` aliases no longer count those reads as mutations. At the same advisory-ledger revision, exact repeated observations from the same tool/target no longer count as new information. Changed output or a later recorded mutation is new information. Shell constructs/unknown commands remain conservative; tools still execute and existing permission/safety checks are unchanged. This does not detect all overlapping/varied reads, nor make the process-local revision ledger authoritative.
3. Added regression tests at the sanitizer/proxy and durable middleware paths. No paid live run was performed.

## What remains unimplemented

1. **Parent overhead:** design an explicit permission-preserving parent tool profile/discovery path. `_resolve_bound_tools`, provider binding, `SafeToolNode`, alias repair, phase allowlists, MCP, browser, delegation and checkpoint/failover must agree. Avoid task-keyword-only filtering, which previously hid required tools. Measure schemas **and** catalog/discovery text, provider cache and added round trips.
2. **Actionable startup failures:** retain current startup/import failure as bounded revision-aware guidance separately from stable-check debt; define stale/clear/supersede semantics. Do not turn exploratory failures into permanent debt. Reproduce the `api_logout` failure and the old disposable-probe regression.
3. **Varied inspection loops:** reconcile the advisory ledger with graph revision and trace systems; research a task-aware, non-blocking strategy nudge for overlapping observations. Protect legitimate read-only and pagination tasks. Existing exact-cycle hard stop still exists; it is not an iteration-count boundary and was not modified here.
4. **Context operating target and accounting:** evaluate existing summarization/compaction before adding another mechanism. Account for complete serialized tool calls, actual provider usage/cache, summary cost and latency; preserve message pairs, intent, failures and discoveries. A large context window does not bound cumulative input spend.
5. **Proof:** run provider-free integration/replay tests first, then a separately approved same-model/provider/prompt/budget A/B. Compare both per-cycle fixed overhead and total time/tokens/cost to a verified outcome, including cache, tool-discovery calls, compaction and failed runs. Never claim success based only on a smaller schema or compilation.

## Verification in this pass

Focused offline suites: 126 tests passed (progress, sanitizer, tool cycle, execution evidence, streaming, continuity, child scope, delivery gates); 103 additional tests passed (toolsets, phase policy, cache visibility, child resume, verification classification, cancellation); and 55 tests passed in a follow-up covering the final sanitizer shape, compaction, parallel tools and budget dispatch. Some test selections overlap, so these are suite results, not a count of distinct tests. No full-suite or live-provider success is claimed. Existing independent reasoning configuration tests previously had two failures and were not retested here.

No source of funds or provider credentials was used. The workspace is uncommitted unless explicitly committed later.
