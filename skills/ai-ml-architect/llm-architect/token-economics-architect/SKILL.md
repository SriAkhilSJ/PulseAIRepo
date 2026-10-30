---
name: token-economics-architect
description: Architect-level token cost modelling — input versus output pricing, context growth in conversation, caching economics, reasoning-token overhead, per-tenant budgets and caps, and the unit-economics view that connects a feature to a bill. Use when AI features must be priced, capped, or made cheaper.
license: MIT
compatibility: Any provider with per-token pricing
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/llm-architect/token-economics-architect
  crusor-origin: original
  crusor-sources: "platform.openai.com/docs/pricing; docs.anthropic.com/en/docs/about-claude/pricing; ai.google.dev/gemini-api/docs/pricing"
  crusor-triggers: "token cost, pricing, cost per request, context window cost, prompt caching cost, llm budget, unit economics, cost per user"
  crusor-verified-on: "2026-10-30"
---

# Token Economics Architect

Token cost is **a product constraint that belongs in the design doc**. A feature
without a cost model is a feature whose economics are discovered by finance.

## When to use

- Pricing a feature or setting per-tenant limits.
- Costs growing faster than usage.
- Choosing a model, a context strategy, or a caching layer.

## When NOT to use

- Prototype with ten users — measure later, but instrument now.

## Decision 1 — The arithmetic

```
cost/request = (input_tokens × in_price) + (output_tokens × out_price)
             + cached_input_adjustment + reasoning_tokens (if billed)
cost/user    = cost/request × requests/user/day × 30
```

- Output tokens usually cost 3–5× input; verbose answers are expensive.
- Reasoning/thinking models bill tokens you never show the user — budget them.
- Every hop in a chain multiplies; count the hops in the design.

## Decision 2 — What grows silently

| Growth | Fix |
|---|---|
| conversation history resent each turn | summarise, window, or cache |
| retrieved chunks growing per query | cap k, rerank, trim |
| system prompt bloating over time | review quarterly, it is code |
| tool outputs pasted whole | truncate + summarise |
| retries and repair loops | bound attempts, measure the rate |
| multi-agent chatter | fewer agents, tighter handoffs |

- A 10-turn conversation with full history is quadratic in tokens; that is the most
  common surprise.

## Decision 3 — Caching

| Cache | Saves |
|---|---|
| provider prompt cache | repeated prefix tokens |
| exact-match response cache | identical requests |
| semantic cache | near-duplicate requests (risky) |
| application-level summaries | re-computation |

- Prompt caching pays only when the prefix repeats inside the provider's TTL.
- Exact-match caching is safe; semantic caching trades correctness for savings and
  needs its own eval.
- Log cache hit rate; a 0% hit rate usually means an unstable prefix.

## Decision 4 — Budgets and caps

- Per-request cap (max tokens) and per-tenant monthly cap, enforced in code.
- Hard stop with a clear message, not a silent degradation.
- Alert at 80% of budget, anomaly-detect at 3× hourly baseline.
- Rate limits per tenant prevent one account from consuming the pool.

## Decision 5 — Unit economics

- Cost per active user, per successful task, per tenant — not just per token.
- Compare against the value delivered (conversion, time saved, ticket deflection).
- Fail rates matter: a retried request costs twice and delivers nothing.
- Price tiers from measured p50 and p95 usage, not average.

## Decision 6 — Reduction levers, in order

1. Shorten outputs and constrain format.
2. Trim context; rerank and cap retrieval.
3. Route to a cheaper model where evals allow.
4. Cache stable prefixes.
5. Fine-tune a smaller model for narrow, high-volume tasks.

Do them in that order — fine-tuning first is the classic expensive mistake.

## Failure modes at scale

- Full history resent every turn; cost grows 4× by message ten.
- No per-tenant cap; one customer's automation consumes the month's budget.
- Semantic cache returning a stale answer after a pricing change.
- Reasoning model in a chat feature; visible latency and invisible cost.
- Costs tracked per provider, never per feature, so nobody knows what to cut.

## Verification receipts

1. Cost model per request with input/output split and hop count.
2. Usage dashboard by feature and tenant, with caps configured.
3. Cache hit rate and the savings attributed to it.
4. Cost per successful task before and after the reduction pass.
5. Budget alert exercised with a synthetic volume spike.
