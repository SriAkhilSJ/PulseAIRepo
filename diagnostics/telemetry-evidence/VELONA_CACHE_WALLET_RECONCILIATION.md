# Velona prompt-cache billing evidence — wallet reconciliation

**Evidence date:** 2026-10-22
**Source:** Founder-relayed live probe on `https://velona.in/v1`; not independently re-run in this sandbox. This note records the supplied measurement without storing credentials or account identifiers.

## Decisive repeat probe

Two identical prompts of approximately 119,625 input tokens were sent through the same Velona route. The founder reports stable USD wallet reads before and after:

| Measurement | Result |
|---|---:|
| Stable-read wallet delta (actual billed) | **$0.0014** (also reported as ₹0.13 on the INR sub-ledger) |
| Ledger full-price projection (recomputed) | **$0.0043** |
| One-full / one-half-price projection | $0.0032 |
| Latency, first → second | 7.63s → 7.92s |

Token split (from the probe's raw usage payloads): both calls billed 119,625 prompt tokens and 8 completion tokens each. Recomputation: full pair = 239,250 × $0.018/1M + 16 × $0.121/1M ≈ **$0.0043**; half-model (call 1 full + call 2 at half) ≈ **$0.0032**. An earlier shared summary printed $0.0086 due to a script bug (the total was multiplied by call count twice); the $0.0043-figures replace it.

The wallet debit is about **32.5%** of the full-price projection and ~43% of the half-discount model. The measurements support the conclusion that repeated prefixes are billed substantially below both the engine's full-rate token estimate *and* a naive one-half cache discount on this warm route (effective repeat-call rate ≈ $0.0055/1M). Latency in this specific pair did not improve; earlier small probes reported 2.78s → 1.57s and 5.73s → 2.42s, so latency is suggestive but variable, not proof by itself.

**Arithmetic scope caveat (resolved):** the original probe summary printed a full-price projection of $0.0086 from a script that multiplied the already-summed token total by the call count a second time. The corrected token/cost basis above (2 calls × 119,625 input tokens, 8 output tokens each) reproduces the projection as $0.0043. The wallet delta is the supplied billing observation.

## Provider telemetry and small probes

- The response usage contained ordinary token counts but no cached-token counter (`prompt_tokens_details` / equivalent). This matches repeated probes and engine traces; cache usage is **not observable in Velona's usage payload**.
- Four calls of approximately 4,185 tokens each reportedly moved the USD display by $0.0004 total—at the display's $0.0001 unit resolution, where full-price cost per call (~$0.000076) is far below one visually-accountable unit, small probes cannot be reconciled reliably in USD. The INR sub-ledger is finer-grained for these debits.
- Therefore, for Velona, do not convert missing cache telemetry into a cache miss or a fabricated hit rate. The runtime's `N/A` is the honest result. Reconcile ledger-estimated costs against wallet deltas over sufficiently large batches; wallet movement is the external billing check, while the token ledger remains the per-call activity record.

## Decision for Knife #2 on Velona

No Knife #2 implementation is justified for this provider. The route appears to apply server-side prefix discounts automatically; `CRUSORAI_PROMPT_CACHE=1` is harmless but does not expose a billing/cache counter or add a provable benefit on this route. Keep the feature unclaimed and the usage display at **N/A** for Velona. This does not establish behavior for other providers.

**Guardrail:** this evidence note is not a wallet/credits integration request. Do not add account-credit polling or wallet UI without a separate founder order. The report fix in `dd2661e2` remains deliberately conservative: full-price rate-card estimates when cache usage is unreported, and no guessed cache discount.

The founder separately noted that remaining wallet headroom is around 75 average tasks and raised a possible top-up decision. Account balance and lifetime spend are intentionally not stored in this repository; wallet funding remains the founder's decision.
