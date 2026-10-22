# Phase 1 step 1 — first organic anatomy reading (founder laptop, 2026-10-21/22)

Source: `~/.crusorai/telemetry/calls-2026-10.jsonl` (copied alongside), engine `b9b66b54`,
provider Velona `z-ai/glm-5.3-flash`, desktop agent, one real flagship task.

## Monthly summary (python -m src.telemetry.call_ledger)

```
model calls: 21 ok, 0 failed; turns finished: 1 {'budget_exhausted': 1}
tokens: 616,091 in / 21,351 out (637,442 total)
cost so far: USD 0.0136161054         (≈ ₹1.28 at Velona's live rates)
request anatomy (avg/call over 20 anatomy-bearing calls):
  ~18,954 tokens = system 9,088 + tools 13,642 (static 116.3%) + conversation 9,866
- z-ai/glm-5.3-flash: 21 calls, 637,442 tokens, USD 0.0136161054, 465s model time
```

## The diet menu (measured, not guessed)

1. **Tool schemas: 14,200 tokens bound on EVERY call** (first call, before any history).
   63+ tool definitions × ~200 tokens each — the single biggest cut (lazy/toolset-scoped binding).
2. **System prompt: ~9k tokens/call** — static vs rarely-needed split is knife #2.
3. **Conversation: ~9.9k avg** — compression tuning last.

Average billed input per call: 616,091 / 20 anatomy calls ≈ 30.8k tokens billed
(anatomy estimate 18.9k — the gap is reasoning tokens billed into input and the
accounting overlap flagged below).

## Open flags for the branch

1. `static 116.3%` — static share >100% ⇒ the system+tools buckets overlap or share
   a wrong denominator; fix the normalization before scoring cuts against it.
2. `turns finished: {'budget_exhausted': 1}` — the founder's first anatomy turn ended
   on a budget guard, not a verdict; the 21st call billed ~28k tokens with no work.
   Metered proof of wasted laps — check with the empty-reply-loop caps (35deba2c).

## First call vs later calls (anatomy lines, verbatim)

- call 1 (thread session-c97a…): in 26,795, sys 8,773 + tools 14,200 + user 5,166 → est 13,939
- call 2: in 27,476, sys 8,807 + tools 14,200, +history (ai 38 + tool_result 356) → est 14,367

The schema tax is constant at 14,200 on every call — history barely moves the request
in the first laps; the static tax is the bill.
