# Agent Core hardening slice — source decision and measurements

**Date:** 2026-10-23

**Baseline:** `590fe542306ef89547e7909b89da01a9c730e55c`

**Scope:** durable evidence safety, typed verification replay, deterministic bounded context selection, and lightweight measurement. This does not add release-verdict policy, deploy, activate, or change model routing.

## Decision

For this repository, the best narrow design is:

1. enforce recursive redaction and size bounds at each **durable write boundary**;
2. enforce tool-body omission centrally in `EventJournal.append`, not only in middleware;
3. retain useful operation metadata while replacing source/request bodies with typed omission metadata;
4. project verification state through one versioned `verification.updated` envelope for live UI and replay;
5. select the best `max_files` from the bounded candidate window with a fixed rank and bounded heap;
6. keep persistence measurements separate from provider token/cost claims.

“Best” here means the strongest fit for the current architecture and approved scope—not a claim that one policy fits every agent. PulseAI already has a central event journal and a separate verification database, so protecting those two sinks directly is safer and simpler than adding checks to every caller. Encrypting and retaining every raw body would still duplicate sensitive data, introduce key-management work, and use more storage; it is not justified for tool intent replay.

## Source verification against active coding-agent implementations

The review used source-only, depth-1 clones and inspected implementation code rather than README claims. Commits are pinned so the comparison is reproducible.

| Runtime | Pinned source evidence | Pattern used in this decision |
|---|---|---|
| [OpenCode](https://github.com/anomalyco/opencode/tree/f9f463be78312411618964a171c285c316d4b9fc) | [`session/compaction.ts`](https://github.com/anomalyco/opencode/blob/f9f463be78312411618964a171c285c316d4b9fc/packages/core/src/session/compaction.ts), [`session/usage.ts`](https://github.com/anomalyco/opencode/blob/f9f463be78312411618964a171c285c316d4b9fc/packages/core/src/session/usage.ts), [`token-usage.ts`](https://github.com/anomalyco/opencode/blob/f9f463be78312411618964a171c285c316d4b9fc/packages/schema/src/token-usage.ts) | Typed compaction/usage contracts; cache and token accounting are separate from durable evidence safety. |
| [Codex](https://github.com/openai/codex/tree/970111f6cb62cc02fe36a82ea7d71b37a2889c97) | [`compact_token_budget.rs`](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/core/src/compact_token_budget.rs), [`compact_retained_tool_outputs.rs`](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/core/src/compact_retained_tool_outputs.rs), [`thread_resume_redaction.rs`](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/app-server/src/request_processors/thread_resume_redaction.rs) | Explicit context budgets, retained-output policy, typed compaction lifecycle, and resume-specific redaction. |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli/tree/d968ea0a247b4709e23fc03b782eaa05ce1bf4d4) | [`adaptiveTokenCalculator.ts`](https://github.com/google-gemini/gemini-cli/blob/d968ea0a247b4709e23fc03b782eaa05ce1bf4d4/packages/core/src/context/utils/adaptiveTokenCalculator.ts), [`tokenLimits.ts`](https://github.com/google-gemini/gemini-cli/blob/d968ea0a247b4709e23fc03b782eaa05ce1bf4d4/packages/core/src/core/tokenLimits.ts), [`credential-leak-prevention.test.ts`](https://github.com/google-gemini/gemini-cli/blob/d968ea0a247b4709e23fc03b782eaa05ce1bf4d4/packages/core/src/agents/auth-provider/credential-leak-prevention.test.ts) | Bound work before expensive calls, calibrate token estimates from provider usage, and test credential-leak prevention independently. |
| [OpenHands](https://github.com/OpenHands/OpenHands/tree/11eba891cb2455f87253888d9d3bf3f6b0f12bc1) | [`redact-custom-secrets.ts`](https://github.com/OpenHands/OpenHands/blob/11eba891cb2455f87253888d9d3bf3f6b0f12bc1/src/utils/redact-custom-secrets.ts), [`redact-mcp-secrets.ts`](https://github.com/OpenHands/OpenHands/blob/11eba891cb2455f87253888d9d3bf3f6b0f12bc1/src/utils/redact-mcp-secrets.ts), [`event-service.api.ts`](https://github.com/OpenHands/OpenHands/blob/11eba891cb2455f87253888d9d3bf3f6b0f12bc1/src/api/event-service/event-service.api.ts) | Redact configured/known secret values as well as generic shapes; keep events queryable and bounded. |
| [Cline](https://github.com/cline/cline/tree/1619168bdeb570aa233d0f0a9af1d332d83a2816) | [`compaction.ts`](https://github.com/cline/cline/blob/1619168bdeb570aa233d0f0a9af1d332d83a2816/apps/cli/src/runtime/interactive/compaction.ts), [`redact-url.ts`](https://github.com/cline/cline/blob/1619168bdeb570aa233d0f0a9af1d332d83a2816/apps/vscode/src/utils/redact-url.ts), [`usage.ts`](https://github.com/cline/cline/blob/1619168bdeb570aa233d0f0a9af1d332d83a2816/sdk/packages/core/src/services/usage.ts) | Preserve canonical history separately from compaction, use focused URL redaction, and normalize typed usage/cost data. |
| [Goose](https://github.com/block/goose/tree/c3bfc5f7b0e230180ba3164ec1ee84fd951eaf0d) | [`ops_compaction.rs`](https://github.com/block/goose/blob/c3bfc5f7b0e230180ba3164ec1ee84fd951eaf0d/crates/goose/src/agents/state_machine/ops_compaction.rs), [`usage.rs`](https://github.com/block/goose/blob/c3bfc5f7b0e230180ba3164ec1ee84fd951eaf0d/crates/goose/src/agents/state_machine/usage.rs), [`provider_secrets.rs`](https://github.com/block/goose/blob/c3bfc5f7b0e230180ba3164ec1ee84fd951eaf0d/crates/goose/src/providers/provider_secrets.rs), [`canonical_cost.rs`](https://github.com/block/goose/blob/c3bfc5f7b0e230180ba3164ec1ee84fd951eaf0d/crates/goose/src/providers/canonical_cost.rs) | Account for unreported context, distinguish usage/cost sources, and keep secret references out of ordinary payloads. |
| [Aider](https://github.com/Aider-AI/aider/tree/5dc9490bb35f9729ef2c95d00a19ccd30c26339c) | [`repomap.py`](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/repomap.py), [`history.py`](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/history.py), [`models.py`](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/models.py) | Bound repo-map/history tokens, cache deterministic context work, and keep model/cost policy explicit. |

The shared pattern is layered rather than one oversized mechanism: durable evidence, model context compaction, provider caching, and token/cost accounting have different contracts. This slice therefore does not claim that redaction reduces model tokens or API price.

## Repository implementation

| Area | Change |
|---|---|
| `src/runtime/persistence.py` | One bounded JSON-safe sanitizer; secret-key masking; configured secret-value masking; cyclic/oversized value handling; recursive typed tool-body omission. |
| `src/runtime/event_journal.py` | Forced event-aware sanitization immediately before serialization/SQLite; callers receive the exact safe replay payload. |
| `src/context/verification_evidence.py` | Forced redaction before writes to the independent verification SQLite database. |
| `src/runtime/verification_events.py` | Schema-versioned evidence ID/kind/time envelope with explicit persisted/unavailable journal status. |
| `src/tools/file_tools.py`, `src/tools/terminal_tools.py` | Command/edit/explicit/unavailable updates all use the same durable envelope before live projection. |
| `src/bridge/__main__.py` | Restart/event replay maps durable `verification.updated` rows to Protocol v2 `verification_updated`. |
| `src/runtime/otel_tracing.py` | Tool attributes use the same body-omitting sanitizer instead of serializing raw arguments. |
| `src/context/bounded_scan.py` | Worst-first bounded heap selects the best output from all considered candidates; coarse size classes avoid byte-level rank churn; receipts expose candidate/retained counts and policy. |
| `src/utils/redact.py` | Opt-in non-reusable masking for durable boundaries; ordinary live-log masking is unchanged. |

## Measured effects

Command:

```bash
python scripts/agent_core_hardening_benchmark.py \
  --writes 200 --cpu-iterations 2000 --scan-runs 8
```

Host-local results from this branch (temporary SQLite databases, no provider calls):

| Measure | Unsafe/pre-change reference | Hardened | Change |
|---|---:|---:|---:|
| 50,059-character tool-intent payload | 50,165 B | 180 B | **-99.64%** |
| SQLite size after 200 body-heavy intents | 10,137,600 B | 90,112 B | **-99.11%** |
| Body-heavy encode/sanitize median | 68.382 µs | 45.748 µs | **-22.634 µs** (body omitted before JSON encoding) |
| Body-heavy durable append median | 0.4366 ms | 0.6092 ms | **+0.1726 ms** |
| Body-heavy durable append p95 | 1.0870 ms | 0.9204 ms | **-0.1666 ms** in this run (I/O variance; not an optimization claim) |
| Small verification encode/sanitize median | 2.261 µs | 28.123 µs | **+25.862 µs** |
| Small verification durable append median | 0.4462 ms | 0.5162 ms | **+0.0700 ms** |
| Small verification durable append p95 | 0.6291 ms | 0.6257 ms | **-0.0034 ms** in this run (effectively noise) |
| Priority scan, 120 files / output 10 | 0.3064 ms | 3.1572 ms | **+2.8508 ms** local bounded ranking work |
| Prefixes across 8 shuffled creation orders | 8 | 1 | deterministic for the fully considered window |

Interpretation:

- **Latency:** durable safety adds about 0.07–0.17 ms median per measured write. Ranking 120 candidates instead of accepting the first ten adds about 2.85 ms in this synthetic scan. Both remain local and bounded.
- **Cheapness/cost:** provider calls, provider tokens, and API cost are unchanged. Disk usage for the body-heavy journal workload falls 99.11%; that is the only demonstrated monetary/retention direction.
- **Performance:** body-heavy serialization itself is faster because omitted bodies are never JSON-encoded, but SQLite commit plus redaction adds a small net append cost. Context quality/reliability improves measurably from unstable `8/8` prefixes to one stable prefix; this is not an end-to-end agent-quality score.
- **Budget usage:** model context `max_files`, byte, and time ceilings remain enforced. Priority mode now spends up to the already-configured considered/visited ceiling to choose those files, instead of spending only an arbitrary filesystem prefix. Durable payload budget is substantially lower. Model token budget is unchanged.

## Validation and limits

Focused contracts cover:

- direct journal writes (so middleware cannot bypass omission);
- prefixed, structured opaque, configured opaque, header, URL, and nested secrets;
- cycles, binary values, oversized strings, and nested tool bodies;
- verification database writes, versioned journal rows, failure degradation, and bridge replay;
- adversarial ascending/descending `scandir` order;
- both previously failing clean-runner context-budget tests.

Final local validation snapshot:

- `129 passed, 2 skipped, 6 deselected` across persistence, bounded scan, full context-budget, journal/verification runtime, masked-success evidence, bridge protocol, OTel, and typecheck-project tests;
- both prior clean-runner failures pass;
- all edited Python modules pass `py_compile`, and `git diff --check` is clean;
- four deselections reproduce unchanged in a detached baseline worktree (two test import-order assumptions, absent optional `tiktoken`, and an absent baseline terminal constant);
- two graph-binding deselections require the uninstalled full LangGraph/provider stack and are assigned to desktop/runtime verification.

Known limits:

1. Existing historical database rows are not migrated or retroactively scrubbed.
2. An unlabeled opaque secret that is neither a configured provider value nor in an omitted body cannot be recognized with certainty; no regex can solve that generally.
3. Determinism is guaranteed over the bounded candidate window. If a directory contains more entries than the configured traversal may inspect, global ordering would require violating that traversal bound.
4. This slice does not benchmark model quality, desktop startup, provider caching, or API billing. Those remain desktop/runtime validation tasks.
