# Velona prompt-cache billing evidence — wallet reconciliation

**Evidence date:** 2026-10-22
**Source:** Founder-relayed live probe on `https://velona.in/v1`; not independently re-run in this sandbox. This note records the supplied measurement without storing credentials or account identifiers.

## Decisive repeat probe

Two identical prompts of approximately 119,625 input tokens were sent through the same Velona route. The founder reports stable USD wallet reads before and after:

| Measurement | Result |
|---|---:|
| Stable-read wallet delta (actual billed) | **$0.0014** (also reported as ₹0.13 on the INR sub-ledger) |
| Ledger full-price projection | $0.0086 |
| One-full / one-half-price projection | $0.0065 |
| Latency, first → second | 7.63s → 7.92s |

The wallet debit is about **16.3%** of the reported full-price projection. The measurements support the conclusion that repeated prefixes are billed substantially below the engine's full-rate token estimate on this warm route. Latency in this specific pair did not improve; earlier small probes reported 2.78s → 1.57s and 5.73s → 2.42s, so latency is suggestive but variable, not proof by itself.

**Arithmetic scope caveat:** the probe summary does not include each call's input/output token split or the exact ledger rows used for the $0.0086 projection. Two calls × 119,625 input tokens × $0.018 per million alone would be about $0.0043 before output tokens. Preserve the reported $0.0086 as the founder's ledger projection; reconcile the exact token/cost basis against the original call rows before using that projection as a reproducible benchmark. The wallet delta is the supplied billing observation.

## Provider telemetry and small probes

- The response usage contained ordinary token counts but no cached-token counter (`prompt_tokens_details` / equivalent). This matches repeated probes and engine traces; cache usage is **not observable in Velona's usage payload**.
- Four calls of approximately 4,185 tokens each reportedly moved the USD display by $0.0004 total—at the display's cent-level resolution, small probes cannot be reconciled reliably in USD. The INR sub-ledger is finer-grained for these debits.
- Therefore, for Velona, do not convert missing cache telemetry into a cache miss or a fabricated hit rate. The runtime's `N/A` is the honest result. Reconcile ledger-estimated costs against wallet deltas over sufficiently large batches; wallet movement is the external billing check, while the token ledger remains the per-call activity record.

## Decision for Knife #2 on Velona

No Knife #2 implementation is justified for this provider. The route appears to apply server-side prefix discounts automatically; `CRUSORAI_PROMPT_CACHE=1` is harmless but does not expose a billing/cache counter or add a provable benefit on this route. Keep the feature unclaimed and the usage display at **N/A** for Velona. This does not establish behavior for other providers.

**Guardrail:** this evidence note is not a wallet/credits integration request. Do not add account-credit polling or wallet UI without a separate founder order. The report fix in `dd2661e2` remains deliberately conservative: full-price rate-card estimates when cache usage is unreported, and no guessed cache discount.

The founder separately noted that remaining wallet headroom is around 75 average tasks and raised a possible top-up decision. Account balance and lifetime spend are intentionally not stored in this repository; wallet funding remains the founder's decision.
