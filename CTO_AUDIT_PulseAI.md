# PulseAI — CTO Audit & Decision Memo
**From:** Office of the CTO · **Date:** 2026-08-11 · **Re:** Latency + "1 call = 1 tool" crisis, and how to actually beat the competition

---

## TL;DR (read this first)

You are not crazy. Both pains are **real and measured**, not vibes:

- **Latency:** 25–56 seconds per agent step, while the actual API round-trip is **0.5–1.1s**. The other ~99% is not the network — it's (a) a free-model proxy queueing/rotating models every call, and (b) **15,239 tokens of context rebuilt and re-sent on every single call.**
- **"1 call = 1 tool":** Confirmed. The parallel-tool *infrastructure* works (turn 1 of the chat-app run fired **6 writes in one turn**). But **the model then collapses to 1 call per turn** for the rest. The chat-app run (D5) did **34 calls / 50 turns** — that's your cost multiplier.

**Both pains share one root cause:** you are running the agent loop on **FreeLLM**, a rotating pool of free models with **no prompt caching** and **weak parallel tool-calling.** That single choice makes 73% of your tokens get billed full-price every call and forces serial tool use.

> **The headline decision:** *Free models are the most expensive choice a startup can make here.* They cost you more in aggregate (more calls, more tokens, failed runs you re-run) than a real provider with prompt caching. We fix latency, cost, **and** correctness in one move — change the model layer.

---

## Part 1 — The Receipts (what the lab data actually proves)

### Latency is NOT the API. It's the provider + your context weight.

| Run | Wall | Calls | Tokens | $/call wall | API round-trip |
|---|---|---|---|---|---|
| shadcn resume-2 | 760s | 26 | 413k | ~29s | **0.5–1.1s** |
| chat D5 | 864s | 34 | 408k | ~25s | ~1s |
| chat D6 | **1,859s** | 33 | 437k | **~56s** | ~1s |
| chat D8 | 1,641s | 30 | ~500k | ~55s | ~1s |

The gap between a ~1s API call and a ~55s step is your problem. Two ingredients:

1. **Provider queueing.** Your own report admits it: *"the 26 calls at ~29s each are dominated by the freellm proxy's model rotation/queueing… per-call cost would drop another ~10x with prompt caching on the serving side."* FreeLLM rotates models → **every call busts the cache** → you pay full latency and full token price every single time.
2. **Per-call context weight.** Every step re-sends **5,686 tokens of tool definitions + 3,654 context layers + 1,840 persona + ~4k history replay = ~15k tokens.** Your own analysis: *"73% of prompt tokens were static overhead re-sent every call."* On a provider **without caching**, that 73% is pure waste, reprocessed 30+ times.

### "1 call = 1 tool" is a model-behavior problem, not a missing feature.

`src/graphs/parallel_tools.py` is genuinely good work — conservative conflict-detection, deterministic ordering, the hermes `_uniquify_tool_call_ids` repair. **The machinery is there.** The chat-app transcript proves it works *when the model cooperates* (turn 1 = 6 batched writes).

But then turns 9→96 are **one tool call each.** Your report's own words: *"the model simply under-batched."* Models on the free pool (qwen, deepseek-flash, gpt-oss) are poor at emitting multiple parallel `tool_calls` in one assistant message. So N independent operations = N round-trips = N× the static-prefix tax. **That is exactly the cost you're feeling.**

### Bonus crisis you should know about: 4 failed runs in a row.

The flagship "build a chat app" task has **never passed** (D5, D6, D7, D8 all FAIL — app returns HTTP 500). Causes:
- Model **hallucinated a `finish` tool** that doesn't exist.
- Model **ignored the `"use client"` Next.js convention** repeatedly.
- `tsc --noEmit` **passes while the app 500s** — static verification cannot catch runtime errors.
- Iteration budget exhausted mid-fix every time.

This is more dangerous than latency. **A slow-but-correct IDE can compete. An IDE that ships broken apps that *look* finished cannot.** Same root cause as the other two: **the model is below the quality bar.**

---

## Part 2 — Root Cause (one sentence)

**You built a sophisticated agent runtime (29k lines, 132 modules, 40 "D-rounds" of fixes) and then bolted the weakest possible brain onto it — a rotating pool of free models with no prompt cache.** Every sophisticated feature (parallel tools, verify gates, cache-preservation) is correct in isolation, but it is all gated behind a brain that under-batches, hallucinates, and ignores advice. You are polishing a Ferrari and putting a lawnmower engine in it.

---

## Part 3 — The Plan (prioritized, decisive)

### 🔴 P1 — Move the agent loop off FreeLLM, onto one cached real provider. *(Fixes latency AND cost AND batching in one move.)*

This is the single highest-leverage change in the repo. Options, ranked by startup economics:

| Provider | Prompt cache? | Parallel tools? | Cache discount | ~Input $/M | Verdict for you |
|---|---|---|---|---|---|
| **DeepSeek V3** (official API) | ✅ disk cache | ✅ good | ~50–90% | $0.27 (cached $0.07) | **Best $→quality for a startup.** Cheap *and* cached. |
| **Anthropic Claude** (Sonnet) | ✅ 5-min | ✅ excellent | 90% read, 1.25× write | $3.00 (cached $0.30) | Best quality/batching. More $. |
| OpenAI GPT-class | ✅ | ✅ | 50% | $2.50+ | Fine, pricier. |

**The math that ends the "we can't afford it" worry:**
- Today: 30 calls × 15k static tokens × **full price every call** = you pay for ~450k tokens of static overhead *per task*. Plus failed runs get re-run.
- With DeepSeek cache: the 15k static prefix is cached after call 1. Calls 2–30 pay **~$0.07/M instead of $0.27/M**, and **don't get re-processed** (that's the latency win). Effective input cost drops **~60–70%** even though the *sticker* per-token price is higher than "free."
- "Free" is costing you more because: more calls (no batching), more tokens (no cache), and re-runs (failed verification). **The cheap option is the real provider with caching.**

**Action:** In `src/llm/factory.py`, set the agent loop to a single cached provider/model (not a pool). Keep FreeLLM only for the *auxiliary/janitor* path (summarization, self-curation) where quality doesn't matter and queueing is tolerable. Pin the model so the cache prefix stays byte-stable (you already built `cache_preservation.py` + a `VOLATILE_TAIL_PREAMBLE` sentinel — *use it on a caching provider* and it finally pays off).

### 🔴 P2 — Prove the cache is actually hitting. Make it a gate, not a hope.

You already have `prompt_cache_audit.py`. Stop trusting it works — **measure hit rate per run and set a target (≥70%).** On DeepSeek/Claude, a hit means the 15k-token static prefix costs ~10% and isn't re-processed. If hit rate is low, the cache-prefix split is wrong. This is where 73% of your token waste lives, and it's *already built* — it just needs a real caching provider underneath it.

### 🟠 P3 — Stop *begging* the model to batch; enforce it.

The model won't batch reliably → don't depend on it. Two tactical additions on top of the (good) `parallel_tools.py` gate:

1. **Upgrading the model (P1) likely fixes this by itself** — Claude/DeepSeek/GPT emit multiple `tool_calls` per turn routinely. Re-measure batching after P1 before building more.
2. **If still weak:** add a *plan-then-execute* node — after planning, emit all independent writes as **one forced assistant turn with N tool_calls** rather than hoping the model emits them. Your gate already executes disjoint writes concurrently and orders conflicting ones deterministically; you just need to *feed* it batches.

### 🟠 P4 — Fix verification for real: runtime proof, not typecheck.

Stop the whack-a-mole. `tsc` passing while the app 500s is a fundamental gap. Rules:
- **UI tasks** must prove a real browser render (non-empty snapshot) before finalize. You built the puppeteer MCP suite — wire it as *mandatory for UI*, keep `typecheck_workspace` for non-UI.
- A large fraction of the 4 failures will **disappear with a stronger model (P1)** that actually applies `"use client"` and doesn't hallucinate `finish`. Verify this before adding more gate complexity.

### 🟡 P5 — Converge. Stop the D41/D42/… treadmill.

`ARCHITECTURE_REVIEW.md` is **148 KB / 54 sections / 40 "D-rounds."** That's a symptom of patching faster than simplifying. `chat_graph.py` is **2,901 lines** — a god-file. **Freeze new features.** Pick one task ("build & verify a Next.js chat app, fast and correct") and converge until it's green, measured, and under your latency/cost budget. Then expand. Split `chat_graph.py` into `nodes/` modules so the next person can reason about it.

### 🟡 P6 — Sequencing: the desktop fork is RIGHT but NOT NOW (your own review says so).

§2 of your architecture review is correct: forking Code-OSS is how Cursor did it, and it's the right end-state. **But doing it now is the classic startup sequencing mistake.** The 15k-file `desktop/` fork already blew up your repo-map builder (the **O(n²)** bug that caused 600s hangs — now fixed, but it cost you). Nail the backend agent first (fast + correct + cheap on one task), **then** fork. Do not touch `desktop/` until P1–P4 are green.

---

## Part 4 — The one decision I need from you

Everything above hinges on a budget call:

> **Are you willing to spend ~$0.03–0.05 per task on a real cached API for the agent loop** (and keep free models only for janitor/summarization work)? 

If **yes** → I execute P1→P4. You likely see latency drop **3–10×**, cost drop **~60%** even at higher sticker prices, and the chat-app task go green — in days, not weeks.

If **no (must stay free)** → we can't "beat the competition" on this stack, period. We pivot the *positioning*: self-hosted open-source agent for privacy/on-prem, where "free" (use-your-own-keys, bring-your-own-model) is a feature, not a cost crisis. That's a viable business — but it's a different company than "better than Cursor."

**My recommendation: P1. The "free" path is the expensive one.**

---

## Appendix — What's genuinely strong (don't lose this in the rebuild)

Keep and build on:
- **`parallel_tools.py`** — correct, conservative, well-tested batch gate. Excellent.
- **Context engine v2** — task-aware layering, AST repo map, import graph, semantic dedup. This is real differentiation vs. typical OSS agents.
- **`cache_preservation.py` + sentinel split** — byte-stable prefix design. It's *ready* for a caching provider; it's been idling on a non-caching one.
- **Persistent SQLite vector memory + chunk index (sqlite-vec KNN + FTS5 BM25 → RRF).** This is the Cursor-gap closer the README claims, and it's real.
- **Durability** — surviving a disk-full crash and resuming in a new process is genuinely hard and you did it.

The bones are good. The brain is the problem. Fix P1 and the rest of this stack finally gets to show what it can do.
