# P0.6.9 — Invocation Coverage

Scope: every real provider invocation reachable from Crusor Desktop / Agent
Core, with its P0.6.9 accounting state. "Fail-closed" means the acceptance-mode
proxy refuses the call before any request when no reservation scope exists.

| Path | Accounting | Reservation | Ledger record | Acceptance behaviour |
| --- | --- | --- | --- | --- |
| Engineering implementation | task governor | yes, before invoke | `subsystem=engineering`, `operation_type=implementation` | settled |
| Engineering repair | task governor | yes | `operation_type=repair` | settled |
| Automatic session title | session auxiliary governor | yes | `subsystem=session_titling` | settled (enabled, synchronous) |
| Chat graph / legacy agent | none | no | none | **refused before dispatch** |
| Conversation summarizer | none | no | none | **refused before dispatch** |
| Context compaction | none | no | none | **refused before dispatch** |
| Self-curation | none | no | none | **refused before dispatch** |
| Agent planner helpers | none | no | none | **refused before dispatch** |
| One-shot prompt runner | none | no | none | **refused before dispatch** |
| Inline completions | none | no | none | **refused before dispatch** |
| Basic graph / tool test | none | no | none | not part of the desktop runtime |
| Embeddings (local SentenceTransformer) | local, no provider bill | n/a | none | no network |

## Why the accepted path is complete

1. `ModelExecutionAdapter._dispatch_code_prompt` reserves, marks in-flight,
   invokes inside an `invocation_scope`, extracts authentic usage, settles and
   writes the ledger.
2. `GovernedProviderGateway.invoke` does the same for the auxiliary lane with a
   session-scoped governor and `max_attempts=1`.
3. `RetryLLMProxy.invoke` runs `assert_governed_for_acceptance()` before request
   preparation. In acceptance, a path in the "none" rows above cannot execute,
   so it cannot create an unaccounted charge.
4. The harness compares, for the run:
   `guard claims == settled invocation records == aggregate FinOps calls`, and
   sums task + auxiliary cost from the ledger against the aggregate FinOps
   files. A missing record, uncertain hold or duplicate settlement fails.

## Tests that pin coverage

| Guarantee | Test |
| --- | --- |
| Gateway reserve → usage → settle | `TestGovernedGateway.test_successful_call_reserves_usage_settles_and_records` |
| Unpriced call never reaches provider | `test_unpriced_model_is_refused_before_dispatch` |
| Post-dispatch error stays uncertain | `test_post_dispatch_error_is_uncertain_not_free` |
| Client construction failure releases | `test_client_construction_failure_releases` |
| Two calls = two settlements | `test_two_calls_are_two_distinct_settlements` |
| Zero budget refuses | `test_zero_budget_refuses` |
| Unaccounted proxy call fails closed in acceptance | `test_unaccounted_proxy_call_fails_closed_in_acceptance` |
| Accounted proxy call is allowed | `test_accounted_proxy_call_is_allowed_in_acceptance` |
| Ledger splits task vs auxiliary | `test_summary_splits_task_and_auxiliary` |
| Aggregate cost reconciles | `test_aggregate_finops_sums_task_and_auxiliary` |
| Bridge titler uses the gateway | `TestBridgeTitlingWiring` |
| Local fallback is not a provider call | `test_local_title_fallback_is_distinct_from_provider` |

## Explicit limitation

The legacy chat-graph and background lanes (`summarizer`, `compaction`,
`self_curation`, `agents/planner`, `prompts/oneshot`, `inline_completions`) are
**not financially governed outside acceptance mode**. They are refused in
acceptance, so they cannot appear in acceptance evidence, but production use of
those lanes still needs its own accounting context. This is reported in
FINDINGS.md as the remaining defect; it is not claimed as complete universal
coverage.
