# Continuous parent overhead and progress fixes — 2026-11-02

This updates the earlier **status at the time** in
`BLUEPRINT_STATUS_AND_FIX_PLAN_2026-11-02.md`. It addresses the actual parent
binding path, not only the unused task-profile resolver. Historical baseline
and reference caveats remain in the earlier report and the two HTML blueprints.

## Implemented

1. Continuous parent, neutral phase: bind a stable task-neutral core plus
   `discover_tools`; all other session-eligible registry tools can be searched
   and activated by exact name for the next model turn. No task-keyword
   filtering. Activation is recovered from real tool receipts in checkpointed
   graph history; provider-context compaction can omit the receipt without
   deleting the graph history. The exact disclosure surface is checkpointed
   across the model/tool edge and checked after alias normalization. Newly
   unavailable tools are removed again. Child scopes, explicit tool caps, and
   stricter state-driven phases retain their previous binding policy. Those
   restricted binding surfaces are also enforced after checkpointed dispatch;
   strict child-scope resolution now fails closed instead of falling back to
   the full registry when it raises. Discovery is not permission or side-effect approval. It can be disabled with
   `CRUSORAI_PROGRESSIVE_TOOLS=off`.
2. **Security bug found and fixed** at the shared autonomous/sub-agent batch
   dispatcher: when SafetyGuard initially allowed an action but the separate
   permission rule denied it, two verdicts could exist for one call ID and the
   old batching code could execute the earlier allowed verdict anyway. Denied
   IDs are now excluded from the safe remainder, while unrelated safe calls
   still run and results retain their original pairing/order. Covered with
   both a denied-only and a mixed-batch regression.
3. The continuous model gets a bounded, structured reminder for recent
   nonzero-exit startup tracebacks even if later read receipts bury them. It
   does not insert raw tool output into system instructions, impose an exact
   rerun obligation, or assert the error is still present. It expires after
   twelve receipts, a new user turn, or a possible intervening mutation. Only a
   small set of recognizable exception types is covered.
4. Advisory bookkeeping recognizes fully repeated subsets of simple literal
   `sed -n 'start,endp' path` observations when the returned lines match recent
   hashed line observations at the same **process-local** ledger revision.
   Changed/new lines, ambiguous syntax, truncated results and intervening
   recorded mutations do not get treated as duplicate information. No tool is
   suppressed. This is not a general semantic overlap detector or an
   authoritative workspace revision system.
5. Request-boundary telemetry now separately reports serialized message
   characters, tool-call/name/ID metadata characters, and whole snapshot JSON
   characters. These are deterministic local JSON snapshot counts, **not**
   provider wire bytes or billed tokens. Payload capture is still opt-in.
6. Prior fixes retain distinct duplicate call/result pair IDs and full result
   bodies through sanitization and use conservative read classification for
   advisory progress. Preserving full results can increase context size.

## Offline schema measurement

With the same local workspace/configuration and the same `convert_to_openai_tool`
serializer used by the provider-facing measurement, after initial delivery,
with browser available and no tsconfig:

| Measure | Full registry / switch off | Progressive / switch on |
|---|---:|---:|
| Bound schemas | 67 | 29 |
| Schema JSON characters | 60,809 | 25,021 |
| Difference | — | 35,788 fewer (58.9%) |

The catalog contained 39 deferred names. A full unfiltered listing was 6,570
characters; an exact single-name activation result was 323 characters. The
listing/activation tool call, additional provider round trips, conversation
history, subsequently activated schemas, provider tokenization and cache misses
are **not included** in the schema-only comparison. Therefore this is not a
claim that overall input tokens, latency, billed cost or task completion improved
by 58.9%. A comparable live A/B is still required.

## Validation and remaining limitations

Provider-free regressions cover the real resolver and `SafeToolNode`, explicit
permission denial and mixed safe/denied batches, checkpoint/resume via SQLite,
the real `ai_node` with compacted provider context, new-turn resets,
availability rechecking, forced-phase precedence, strict child scopes, operator
caps, cancellation, verification debt, sanitizer pairing and telemetry. Three
final targeted groups passed **126, 140 and 108 tests** respectively (not a
full-suite claim). No paid provider call or new end-to-end benchmark was run.

Still needed: a controlled same-provider/task/budget/cache A/B measuring
per-request input and output tokens, tool schemas and metadata, cache ratios,
wall time, actual/estimated cost, discovery rounds, delivery and verification;
long-running real-provider checkpoint-resume evidence; broader varied-read
coverage and reconciling the graph and process-local revision models. The
existing tested repeated-cycle guard, explicit budgets, permissions,
cancellation, and completion/verification gates still apply; continuous mode
is not a promise of unconditional completion.
