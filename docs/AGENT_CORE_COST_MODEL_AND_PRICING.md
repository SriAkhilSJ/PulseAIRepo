# Agent Core — Code, Product & Unit Economics (2026-10-31)

**What this answers:** where the code/product actually stands, how to make the
agent strong, and **what a month costs** — so pricing can be decided on
measurements instead of vibes.

Every cost figure below is **measured from the shipped prompt-assembly path**
(`scripts/cost_model.py`), not modelled from a README. Re-run it any time:

```bash
python scripts/cost_model.py                       # current tree
python scripts/cost_model.py --price-in 2.50 --price-out 10 --calls-per-turn 35
python scripts/cost_model.py --json                # machine-readable
```

---

## 1. The finding that decides the pricing

I measured the assembled system prompt through the real session path:

| | Tokens per provider call |
|---|---|
| Whole system prompt, **before** today | **22,067** |
| …of which the skills index | **19,078 (86.5%)** |
| Whole system prompt, **after** today's fix | **5,840** (−74%) |

Root cause, measured not guessed:

- `skills/` holds **241 `SKILL.md` files** (240 enabled after gating) — nested
  "architect" books.
- The index rendered **240 entries with full descriptions = 76,270 chars**.
- It is injected into the **volatile tail**, i.e. *after* the cacheable prefix,
  so providers re-bill it on **every call** (the graph budget allows 20–45 calls
  per turn).
- Upstream's names-only demotion tier (`compact_categories`) existed but **no
  caller ever passed it** — the block had no ceiling. That is the whole bug:
  a documented escape hatch that nothing drove.

That single block was **~73% of all billed input tokens** in a normal turn.

### The fix (shipped today)

`apply_skills_index_budget()` in `src/prompts/hermes/skills_index.py`:

- `CRUSORAI_SKILLS_INDEX_MAX_TOKENS` (default **3,000**; `0` = legacy unbounded, instant rollback)
- Every skill keeps its **name** — discovery is never lost; descriptions are
  spent **cheapest-first, round-robin across categories** until the budget fills
- Honest footer: *“N of M skills are listed by name only to fit the prompt
  budget — load one with skill_view(name).”*
- The budget is part of the cache key, so lowering it mid-process takes effect
  immediately instead of serving the expensive cached render

Pinned by `src/tests/test_skills_index_budget.py` (8 tests) and the existing
skills/parity suites (140 passed, 1 skipped).

---

## 2. Unit economics (measured prompt × configurable prices)

Assumptions are inputs, not claims: **25 provider calls/turn** (budget allows
20–45), 8k history tokens/call, 400 output tokens/call, 2,200 turns/month
(100 turns/day × 22 days — a heavy user).

| Input price tier | Before: $/turn | After: $/turn | Before: $/month | **After: $/month** |
|---|---|---|---|---|
| Cheap ($0.10 in / $0.40 out per 1M) | $0.0792 | $0.0386 | $174 | **$85** |
| Mid ($0.30 / $2.40) | $0.2495 | $0.1278 | $549 | **$281** |
| Frontier ($2.50 / $10.00) | $1.9792 | $0.9650 | $4,354 | **$2,123** |

Add prompt caching (90% of the prompt read at 0.1×) on top of the budget fix and
the mid tier goes **$0.2495 → $0.0923/turn** — a **63%** all-in reduction.

**Read this before setting a price:** at the same work volume, a $20/month seat
on a frontier model costs **~$2,123/month** to serve. Even cheerful mid-tier
pricing loses money on a flat seat if the user runs 100 turns/day. The seat model
only works if (a) heavy users are metered, or (b) calls/turn comes down, or
(c) the default route is the cheap tier with premium as an upgrade.

---

## 3. Pricing sheet you can defend (derived from §2)

Target **75% gross margin**. "Included turns" = what the monthly cost can afford:

| Plan | Price | Cost budget @75% | Included turns (cheap tier) | (mid tier) | (frontier) |
|---|---|---|---|---|---|
| Starter | $20 | $5.00 | ~129 | ~39 | ~5 |
| Pro | $50 | $12.50 | ~323 | ~98 | ~13 |
| Team (per seat) | $100 | $25.00 | ~647 | ~196 | ~26 |

Consequences that follow from the arithmetic, not from taste:

1. **Meter, don't promise unlimited.** Unlimited frontier seats are structurally
   unprofitable at 100 turns/day.
2. **Sell turns, not tokens** — the user thinks in tasks; meter `turn` units
   (already a first-class concept: `turn_controls`, `turn_done`).
3. **Default to the cheap tier, upsell premium per turn.** The router already
   supports it (`CRUSORAI_CHEAP_*`, `cost_router`); the default experience should
   be cheap-tier with an explicit "use a frontier model for this turn" switch.
4. **Make caching a headline number, not a setting.** `$0.2495 → $0.0923/turn`
   from cache + budget is the single cheapest reliability win you have.

---

## 4. State of the code & product (measured today)

| Dimension | State |
|---|---|
| Runtime | 151,074 LOC / 489 files; graph = **16 nodes**; **66** tools; 18 context layers |
| Tests | 62,523 LOC / 245 files; **3,108 passing, 0 failing** (provider-free) |
| Cost per call | **5,840 prompt tokens** (was 22,067) |
| Cost control | skills budget ✅ · cost router (cheap/standard/premium) ✅ · compaction ✅ · cache audit ✅ |
| Isolation | ❌ host execution (no sandbox) — blocks multi-tenant/enterprise pricing |
| Evidence | ❌ no public benchmark number — blocks credibility-based pricing |
| CI | ⚠️ 5 test files, not the 3,108-test suite |

## 5. The way to make the agent strong (and cheaper at the same time)

Ordered by measured payoff per unit of work. Each has an acceptance bar.

| # | Move | Why it pays | Bar |
|---|---|---|---|
| 1 | **Retrieval instead of an index dump** — inject the *bodies* of top-k relevant skills (the `SkillManager` and chunk retrieval already do this) and drop the 240-entry description list to names | kills the last 3k tokens/call **and** raises task quality (more relevant guidance, less noise) | prompt ≤ 3,000 tokens; task-success A/B on 30 pinned tasks |
| 2 | **Turn caching on by default** where the provider supports it | measured −66% input cost at 90% hit; the 18-layer design already keeps a stable prefix | cache-hit ratio ≥ 70% reported in receipts |
| 3 | **Fewer calls per turn** (tool batching / PTC, parallel tools) | cost is linear in calls: 25 → 15 calls is −40% cost and −40% latency | median calls/turn < 18 on the benchmark set |
| 4 | **Cheap tier by default, premium on request** | 3.3× cheaper per token at the mid tier vs frontier | premium turns < 20% of total |
| 5 | **Sandbox the body** (docker/namespace) | unlocks enterprise/multi-tenant pricing — the only way a $100+ seat is defensible | untrusted-repo run cannot touch `$HOME`/network |
| 6 | **One public number** (SWE-bench Verified-lite, failures included) | converts "trust me" into a price argument | ≥ 40% Verified-lite; publish false-done rate too |
| 7 | **CI runs the whole suite** | protects all of the above | 3,108 tests as the merge gate |
| 8 | **Split `chat_graph.py`** (8,033 lines) | velocity; every future cost/quality change lands here | no module > 2,000 lines |

Items 1–4 are **cost-and-quality negative-friction wins** that need no new
infrastructure. 5–8 are the ones that turn this from "impressive repo" into
"sellable product".

## 6. What a month looks like, by user profile (after today's fix, mid tier)

| Profile | Turns/month | Cost/month | If you charge |
|---|---|---|---|
| Casual (10 turns/day) | 220 | **$28** | $20 seat → −$8 |
| Regular (40/day) | 880 | **$112** | $50 seat → −$62 ❗ |
| Heavy (100/day) | 2,200 | **$281** | $100 seat → −$181 ❗ |
| Heavy + cheap tier | 2,200 | **$85** | $100 seat → +$15 ✅ |
| Heavy + cheap tier + caching | 2,200 | **~$60** | $100 seat → +$40 ✅ |

The whole pricing conversation reduces to one decision: **which tier is the
default**. Cheap-by-default with metered premium turns is profitable at every
profile above; frontier-by-default is not profitable at any flat seat price a
developer will pay.

> **Honesty notes.** Prompt sizes are measured; call counts and history sizes
> are stated assumptions you can override on the command line. Prices are
> inputs, not vendor quotes. No live model turn was run in this pass, and no
> TestSprite suite was executed (no API key) — so nothing here is a validated
> end-to-end cost, only a measured unit cost at the prompt layer.
