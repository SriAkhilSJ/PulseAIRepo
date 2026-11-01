# Why 20-ish calls emptied the account — cost & prompt-cache audit

**Date:** 2026-11-01 · Model `z-ai/glm-5.3-flash` via Velona · Evidence: runs `41290247998`, `41288766831`

---

## 0. First, the unit error: **1 LLM call ≠ 1 turn**

A *turn* is one message from you. A *call* is one trip to the model inside it — the model
reasons, calls a tool, sees the result, and comes back. That is a second call. One turn is
**many** calls:

| | turn 1 | turn 2 | turn 3 | turn 4 | turn 5 | total |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| LLM calls | 4 | 14 | 33 | 26 | 27 | **104** |

The "20" was never calls-per-session — it was `AGENT_ITERATION_BUDGET=20`, i.e. **20 calls
per turn**, which my harness wrongly imposed on the agent (production is 45). So the session
was ~104 calls, not 20.

---

## 1. It was not 20 calls. It was 104 calls and **2.97M tokens**.

The first turn makes 4 calls. A *mature* turn makes 26–33, and **every call re-sends the
whole transcript**. From the run's own telemetry:

| turn | calls | tokens billed | tokens **per call** | cumulative |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 120,203 | **30,051** | 120,203 |
| 2 | 14 | 352,513 | 25,180 | 472,716 |
| 3 | 33 | 716,050 | 21,698 | 1,188,766 |
| 4 | 26 | 852,945 | 32,806 | 2,041,711 |
| 5 | 27 | 925,941 | 34,294 | **2,967,652** |

`2,967,652 tokens × $0.153/M ≈ $0.45` for five turns. That is the whole refill, and it
died at turn 6.

**The shape is the problem, not the rate.** Each turn re-pays for its entire history:
turn 5 sent ~34k tokens *per call*, 27 times. Cost is therefore **O(turns²)** — turn 7
alone would have billed a full turn's budget before doing any new work.

---

## 2. The actual bankruptcy: 2.5M tokens were spent and then thrown away

This is the number nobody printed:

| | tokens | meaning |
| :--- | ---: | :--- |
| spent on turns that **completed** | 472,716 | 2 turns of real work |
| spent on turns that were **cut** | **2,494,936** (716k+852k+925k) | 3 turns that ended `budget_exhausted` |
| spend per **completed** turn | ~236k | |

**84% of the money bought nothing.** Not because the model failed — because the turn was
stopped at `iterations 20/20` (my harness's cap, since fixed) *after* it had already passed
verification. We paid to build the thing, then refused to let the turn say so.

That is what "bankrupt agent core" should mean here: not the price per token, but
**spend per completed turn**, which was 5× the price of a first turn.

Now printed on every run:

```json
{"tokens_spent_total": 2967652, "tokens_spent_on_cut_turns": 2494936,
 "tokens_per_completed_turn": 236358}
```

---

## 3. Why there is a prompt cache at all

Agent loops are the pathological case cache was invented for. You send the same 30k-token
prefix 27 times in a row; only the tail changes. Caching the KV state of that prefix means:

- **cheaper** — cached input bills at a steep discount (roughly 50–90% off, per provider),
- **faster** — no re-prefill of 30k tokens on every call.

Two flavours:

| Kind | Who does it | How |
| :--- | :--- | :--- |
| **Implicit** | OpenAI, most OpenAI-compatible gateways | automatic for prompts over ~1k tokens; matching prefix = discount. Nothing to declare |
| **Explicit** | Anthropic, Gemini, Groq | you place `cache_control` breakpoints on messages |

**Our repo has both, and the explicit one was OFF.** `src/context/prompt_cache_plan.py`
needs `CRUSORAI_PROMPT_CACHE=1`, plus `CRUSORAI_PROMPT_CACHE_CUSTOM=1` on a `custom`
route — and no workflow or driver ever set either. So every cached token in every run came
from **Velona/gateway implicit caching**, which we neither controlled nor configured.

### 3.1 And our cache hit rate *decays* exactly when it matters

| turn | cached / total | hit rate |
| ---: | :--- | ---: |
| 5 | 328,064 / 617,579 | **53%** |
| 6 | 286,627 / 626,404 | **46%** |
| 7 | 248,439 / 629,910 | **39%** |

Why it falls: **compaction rewrites the prefix**. This session compacted four times
(`context_engine_lines=4`). Every time history is reshaped, the cache key changes and the
*following* call re-prefills the whole 30k prompt at full price. We are paying full retail
for the largest prompts, then paying again to rebuild the cache we just destroyed.

Worse, the token cap counts those cached tokens at **full weight**, so compaction makes the
cap trip *earlier* — the budget punishes the very mechanism that was supposed to save money.

---

## 4. Do the best agents work "this trash"?

Same physics — context is re-sent, that is what an LLM API is. But mature harnesses bound
the quantity, keep the prefix stable, and never discard finished work.

| Harness | What it does about exactly this | Our gap |
| :--- | :--- | :--- |
| **OpenHands** | *Observation masking* — old tool outputs are replaced with a placeholder **in place**, so the prefix stays structurally stable instead of being re-summarised; plus 10 condenser strategies chosen by config | Ours re-summarises and re-writes, invalidating the cache |
| **OpenHands / Anthropic-style routes** | Condensation is a **tombstone event**, applied deterministically — the prompt can be reconstructed identically | Ours rebuilds history from scratch on each compaction |
| **SWE-agent** | ACI truncates observations by design and returns terse, uniform messages | `CRUSORAI_TERMINAL_MAX_OUTPUT_CHARS=12000` ≈ 3k tokens **per tool result**; 30 tool calls/turn = up to 90k tokens before any reasoning |
| **Aider** | Sends a **1–4k token repo map** instead of file contents; the map is cached by mtime+hash | We re-read files into the transcript and pay for them on every subsequent call |
| **Cline** | Tools return `{success, error}` as data — small, structured, cheap to re-send | Tool failures were plain strings; malformed ones could be large |
| **All of them** | Compact to a **fraction of the window** (Aider's map is 1/8th), well before the cap | Ours compacts at the cap — i.e. after the money is already spent |

So: no, they do not run this way. The difference is not a cleverer model, it is **bounding
what enters the transcript** and **not rewriting it afterwards**.

---

## 5. What will not happen again

Only things now enforced by code and a test. Everything else is listed as *not* guaranteed.

| Guarantee | Enforced by | Test |
| :--- | :--- | :--- |
| A session cannot drain the account silently — the driver sets a **money** cap (`AGENT_COST_BUDGET`), not just a token cap | `run_long_session.py --max-cost-usd` (workflow default **$0.60**) | `test_the_driver_sets_a_money_cap_not_only_a_token_cap` |
| The report always separates **tokens that did work** from **tokens that were discarded** | `summarize()` emits `tokens_spent_on_cut_turns`, `tokens_per_completed_turn` | `test_report_separates_tokens_that_did_work_from_tokens_that_were_discarded` |
| The harness can never again impose the agent's iteration budget | `--agent-iteration-budget` (45) vs `--max-llm-calls` (60, real stop) | `test_harness_ceiling_is_never_reported_as_an_agent_property` |
| A cut turn can never print `finalize done: completed` | verdict invariant | `test_budget_cut_turn_is_never_reported_completed` |
| A dead wallet halts the session in seconds | billing halt path | run `41291666232`: stopped turn 1, 5.3 s, 6 turns not attempted |
| A green CI tick cannot accompany a failed session | gate step | run `41285588347`: correctly red |
| The core imports without provider SDKs, web-search, or credentials | lazy imports | `test_core_imports_without_optional_provider_sdks`, body checkup |
| A tool failure always carries its cause | `build_failure` | `test_d9_build_failure_terminal_variants` |

### What is still **not** guaranteed — do not assume it

1. **That a 7-turn session finishes.** Untested at the agent's real budget; the money ran out
   first. That is the one open question.
2. **That cost stays bounded per turn.** No per-turn money cap exists; a mature turn can still
   cost ~$0.14 and there is no mechanism that stops a *single* turn spending more than that.
3. **That the cache is used well.** Explicit breakpoints remain off for `custom` routes and
   nothing enables them; hit rate is whatever the gateway decides (~39–53% measured).
4. **That compaction preserves the cache.** It provably does not — that is the §3.1 decay, and
   no fix has been written.
5. **That the 67 full-suite failures are harmless.** They are untriaged.

---

## 5b. What my "healthy" verdict actually covered — and the hole in it

The body checkup had **13 pipelines and zero economics probes**. It passed 54 checks and I
reported "the agent core does not break". Every word of that was true and it was the wrong
question: I audited *correctness and stability* and never once measured *cost*. A checkup
that can call a body healthy while it empties the account is not a checkup.

A **14th pipeline — `14 economics` — now exists** (7 probes, run it keyless with
`python scripts/agent_core_checkup.py`). It immediately reported three WARNs, i.e. the three
real cost problems, in a 5-second offline run:

| Economics probe | Finding |
| :--- | :--- |
| One tool result is token-bounded | **~3,000 tokens per result** (12,000 chars); 30 calls/turn ≈ **90,000 tokens before any reasoning** |
| Money is a budget leg | `AGENT_COST_BUDGET` parses but is **off by default** — a session runs until the provider refuses |
| Cached tokens are visible in the receipt | PASS — so "exhausted" can no longer read as "wasteful" |
| Spend per **completed** turn is reported | PASS — 2.5M discarded tokens are now named |
| Explicit prompt-cache breakpoints ON | **OFF** for `custom` routes; the 39–53% hit rate was gateway-implicit only |
| Compaction consults the cache plan | **Never** — it rewrites the prefix, so the next call re-prefills at full price |
| Agent's per-turn budget ≥ production | PASS — 45, with a 60-call safety stop |

`test_body_checkup_covers_every_pipeline` now fails if `economics` is removed, so this
blind spot cannot come back.

---

## 6. The next run: what to spend, and what it should answer

Do **not** re-run 7 turns to learn the same fact again. One cheap, decisive experiment:

| Setting | Value | Why |
| :--- | :--- | :--- |
| turns | **3** | Turns 1–2 already answer "does a fresh session cost ~25–30k/call?" |
| `--agent-iteration-budget` | 45 | the open question: does a turn *finish* when the budget is not mine |
| `--max-input-tokens` | 1,200,000 | stop early only on genuine runaway |
| `--max-cost-usd` | **0.40** | hard money stop; the wallet cannot be drained again |
| prompt cache | leave **off** (implicit only) | explicit markers on a generic OpenAI-compatible route risk a 400 |

Cost estimate: 3 turns × ~$0.14 ≈ **$0.42 ≈ ₹37**. If turn 3 completes, the agent is healthy
and the earlier cuts were entirely my harness. If turn 3 is cut at 45 iterations with the
token leg low, the cap design is the defect and **that** is the next fix — measured, not argued.

**Bigger lever, worth more than any more runs:** make compaction **mask** rather than
**rewrite** (OpenHands style). Same history, stable prefix, cache survives, and the token cap
stops punishing the mechanism that saves money.
