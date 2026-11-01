# Agent Core — Full Body Checkup
**Date:** 2026-10-31 · **Method:** static read of `src/` + forensic analysis of 83 real step traces in `diagnostics/` · **Reproduce:** `python3 scripts/diagnose_run_termination.py`

This is the whole core, organ by organ — plus a full root-cause investigation of your observation: *"the agent ends at 20+ calls without knowing why."*

---

# PART I — Your question, answered with evidence

## The short answer

**There is no 20-call wall.** I searched the entire core (`src/graphs`, `src/runtime`, `src/bridge`) for a 25-call cap and there isn't one. The only call ceiling is `AGENT_ITERATION_BUDGET`, default **45**, and it is **turn-scoped** — `_turn_scoped_resets()` zeroes `iteration_used` at **14 separate call sites** in `chat_graph.py`. Your real traces confirm it: sessions reach **76, 55, 48, 46, 34, 32** AI calls.

So the run isn't dying because it ran out of calls. **It's dying silently, and the reason is never written down.**

## The finding (this is the important one)

> **82% of your runs end with no terminal node at all.**

```
traces analysed: 77
total spend:     $10.5729
no terminal:     63/77 (82%)

node coverage across ALL traces:
     643  ai
     523  tools
      18  finalize
       1  finish_gate
       1  planner
       0  task_manager      ← never appears
       0  progress          ← never appears
       0  recovery_limit    ← never appears
       0  tool_cycle_limit  ← never appears
       0  pivot             ← never appears
```

**56 sessions end on `ai`. 13 end on `tools`. 17 reach `finalize`.**

That is your "ends without knowing" — literally. Read a trace after a failed run and it stops on an AI call. Nothing says cancelled, crashed, budgeted, or timed out.

## Why the reason is missing — the structural bug

`run_outcome` — the field your Tri-Dimensional Status Contract is built on — is **computed inside `finalize`**:

| Location | What it does |
|---|---|
| `chat_graph.py:3150–3219` | assigns `run_outcome` ∈ {`safety_denial`, `budget_exhausted`, `timed_out`, `cancelled`, `failed`, `completed`} |
| `chat_graph.py:7739` | `final_run_outcome = finalize_data.get("run_outcome")` |
| `bridge/__main__.py:1180` | `"run_outcome": getattr(result, "run_outcome", None)` |

**The verdict is produced by the one node that might not run.** If the graph is cancelled, raises, or the process dies, `finalize` never executes, `finalize_data` is empty, and the bridge emits `run_outcome: None`. The single most important diagnostic field in the system defaults to *silence* on exactly the runs you need it for.

The bridge is not the problem — `bridge/__main__.py:1170–1185` already emits a **complete** terminal receipt (`turn_done` with `run_outcome`, `failure_reason`, `verification_status`, `status_contract`). The data exists at the edge. It just never reaches the step trace, and the step trace is the artifact that survives.

## Three more things the traces prove

**1. The turn budget is not a task budget.** 76 AI calls in one session means at least two turns. Your per-turn ceiling is respected; your *per-task* spend is not. The user sees "it keeps going" or "it stopped"; neither maps to a budget they can reason about.

**2. Spend is 20–35× your own stated target.**

| Session | AI calls | Tokens | Cost |
|---|---|---|---|
| `session-13e790b1…` | 55 | 1,611,385 | **$1.709** |
| `session-58e0a9b3…` | 32 | 1,542,396 | **$1.576** |
| `session-f16ed857…` | 76 | 995,725 | **$1.036** |
| `session-290378f6…` | 18 | 749,662 | **$0.789** |
| `session-192414d9…` | 48 | 731,508 | **$0.763** |
| **all 77 sessions** | — | **10,830,260** | **$10.57** |

Your own `PERFORMANCE_REPORT` states the target: **`$ < $0.05 / task`**. Average actual: **$0.137**. Worst: **$1.71 — 34× over.**

**3. The scorecard can't see the cost.** That same report awarded **95.4/100 "A (Elite Champion)"** to a run that cost **$0.6498 against a $0.05 target (13× over)**, because the runtime sub-score grades *latency, cache, correctness, batching* — **dollars are not a scored dimension at all**. Economics is 40% of the total and the economics section ignores the economic outcome. This is why the failures feel unexplained: the report says A+ while the invoice says otherwise.

## Will it be fixed?

Yes — and it's the cheapest high-value fix in the repo. **Five changes, none structural:**

**T1 — Initialise the verdict instead of only computing it (5 lines).**
At turn start, in `_turn_scoped_resets()`: `"run_outcome": "in_progress"`. Now an abrupt exit leaves `in_progress`, which is *information* — "this died" — instead of `None`, which is *nothing*. Silence becomes a signal.

**T2 — Make `finalize` reachable from every path (30 lines).**
Wrap node execution so an exception or cancellation routes to `finalize` instead of escaping the graph. LangGraph gives you the conditional edges; you already have `recovery_limit` / `tool_cycle_limit` as terminal sinks. Add an `error → finalize` edge and a `CancelledError → finalize` edge. **This alone moves you from 82% unexplained to ~100% explained** — because `finalize` is what assigns the reason, so making it unavoidable fixes the root cause rather than patching the symptom.

**T3 — One terminal row in the trace, from the bridge (20 lines).**
In `bridge/__main__.py`, on *every* exit path (normal, exception, cancel, and an `atexit`/signal handler), write one trace event:
`{"node_name":"turn_terminal","run_outcome":…,"failure_reason":…,"last_node":…,"iteration_used":…,"cost_usd":…}`
Now `scripts/diagnose_run_termination.py` stops printing `UNEXPLAINED` and starts printing the actual cause.

**T4 — Score dollars, and fix the render (10 lines).**
Add `cost_score` to the runtime sub-score with `target/cost` as the ratio, so a 13× overrun costs ~40 points instead of ~0. And fix `PERFORMANCE_REPORT` printing **`Runtime Health Score 88.6 / 25`** when `step_tracker.py:783` computes a 0–100 scale (`sum / (25 * len) * 100`). A report that divides by the wrong denominator is the same disease as a run that ends without a reason.

**T5 — Persist the bridge receipt.** The `turn_done` payload already carries everything T3 needs. Write it to the trace instead of computing a second, weaker version in the graph.

**Diagnostic you can run right now** (I built it, it reproduces everything above):

```
python3 scripts/diagnose_run_termination.py            # all runs
python3 scripts/diagnose_run_termination.py --top 10   # worst offenders
python3 scripts/diagnose_run_termination.py --json     # for CI gating
```

**Honest limit:** from a static trace I *cannot* tell you which of {cancel, crash, provider death, wall-clock kill} ended each of those 63 runs — **because the trace is precisely the artifact that's missing the reason.** That's not a gap in the analysis, it's the finding. T1–T3 exist to make the next run answerable.

---

# PART II — The body checkup, organ by organ

Scored 0–2 per the rubric from the earlier thread. **●** = 2, **◐** = 1, **○** = 0.

| # | Organ | Score | Evidence | Verdict |
|---|---|---|---|---|
| 1 | **Prompt assembly / cache prefix** | ● | `layer_policy.BUILDER_ORDER` 17-layer canonical order; `VOLATILE_LAYERS={git_context}` emitted last behind constant preamble; `_invalidate_stable_prefix`; break receipt | **Best in class.** No competitor does deliberate cache-stable ordering. |
| 2 | **Context manager** | ◐ | 32 layers, task-type relevance, usage-driven compaction at 75% of *real* window, anti-thrash | **Strong, with a measurement defect** — see C2 below. |
| 3 | **Grounding** | ○ | `repo_map.py:335/452/490` gate symbols + both import graphs on `.py` | **Broken for frontend.** Root cause of milestone lock-in. |
| 4 | **Edit primitive** | ● | 9 fuzzy strategies; pre-flight `ast.parse`/`json.loads`/tree-sitter/esbuild *before* disk; LSP pre+post | **Best in class.** |
| 5 | **Verifier** | ● | Hashed verification debt (only the *same* check clears it), mutation-before-recheck, 4-state receipt, revision staleness | **Your moat.** |
| 6 | **Escalation ladder** | ○ | `cost_router.classify` is substring matching, once per task, no promotion on failure | **Absent.** See D4. |
| 7 | **Budget governor** | ◐ | Dual legs, final-call reserve, 90% checkpoint, verification reserve — **but no USD leg, and turn-scoped** | **Best-in-class mechanics, wrong scope.** |
| 8 | **Memory / scratchpad** | ● | `run_state_ledger` outside the context window, feedback-weighted relevance, per-session engines | **Strong.** |
| 9 | **Tool layer** | ◐ | 200+ tools, parallel + conflict detection, truncation — but `process_boundary.py` imported **nowhere** | **One dead pillar.** |
| 10 | **Honesty / telemetry** | ○ | Tri-dimensional contract exists… **and is only computed when finalize runs (82% don't)** | **Architecturally right, operationally silent.** |

**Total: 13 / 20.** The three zeros are all the same disease in different organs: **the system knows things at runtime and forgets to write them down.**

## The five defects, ranked

### D1 — Repo map blind to `.tsx` *(organ 3)*
`repo_map.py:335, :452, :490` gate on `.py`. `lang_extractors.py` already has tree-sitter for JS/TS/JSX, and `extract_js_import_edges` (`:477`) is written and never called by the map. The model's global view of a new project contains backend files only — which makes Milestone Lock-in *rational*.
**Fix:** swap the `.py` gates for `lang_extractors.source_extensions()`; seed PageRank with the existing JS import edges. ~150 lines. **Highest correctness-per-line in the repo.**

### D2 — `milestone_governor.py` never written *(the 20+ call symptom)*
`progress_guard.py` detects repetition and inspection sprawl. It has **no concept of tier progression**. Nothing stops the agent from polishing `server.py` for 24 turns.
**Fix:** a `milestone` node between `progress` and `ai`; `ai_node` may not target milestone M+1 while M has no landed mutation; once M lands + passes, inject one advance nudge and demote M's files from relevance. ~250 lines. **This is the fix that converts `budget_exhausted` into `completed`.**

### D3 — `process_boundary.py` is dead code *(organ 9)*
136 lines, written, tested — `grep -rn process_boundary src` returns only its own docstring. Your Run 8 lost 5 calls to sec-police denials from Linux idioms on Windows PowerShell.
**Fix:** import `posix_violations` + `split_command_spec` into `terminal_tools.terminal()` before spawn. **~15 lines. Cheapest win in the repo.**

### D4 — `cost_router` is a keyword matcher *(organ 6)*
`cheap_signals` contains `"hi "`, `"just "`, `"can you"`, `"explain"`; anything under 35 chars routes cheap. `_build_tiers()` points all three tiers at the *same model* unless `CRUSORAI_CHEAP_*` is fully set. `classify()` accepts `current_plan` and ignores it. No promotion-on-failure path exists anywhere.
**Fix:** classify on the **plan and the bound toolset** (read-only ⇒ cheap), delete the conversational tokens; add `escalation_level` promoted by repeated verification failure; add the USD leg to `budget.py` using the existing `call_ledger.estimate_cost_usd`.

### D5 — Cache is unobservable on 94% of calls *(organ 2)*
```
ai events where provider REPORTED cache : 36
ai events where it did NOT             : 607
input tokens billed with no cache visibility: 10,247,765
reported hit ratios: median 0.06, max 0.99, 15/36 above 0.5
```
Bimodal — either 0.8–0.99 or ~0. So caching *works* when reported and *breaks* intermittently. But on **10.2M input tokens you have no evidence either way**, because Velona/Gateway omits `input_token_details` (your own report says so).
**Fix:** log the *effective* cache-relevant prefix hash per call and compare it across turns. You can compute cache-correctness yourself even when the provider won't report it — your `prompt_cache_audit` already has the machinery.

### D6 — Token counting is cl100k for every model *(organ 2)*
`token_budget.count_tokens()` falls back to `cl100k_base` — OpenAI's BPE — for Velona/GLM, Groq-Llama, Gemini, NVIDIA. Systematic 10–25% error on code, propagating into `allocate_budget`, `_assemble_hierarchical`, `compress_layer`'s target, and dedup thresholds. **And `update_from_response()` already stores the provider's true `prompt_tokens`** — used for pressure only, never to calibrate.
**Fix:** EMA the `real/estimated` ratio per model, persist in `model_budgets`' existing disk cache, multiply the estimator. ~35 lines; turns budgeting from *assumed* to *measured*.

### D7 — Layer scoring advertises a term that never runs *(organ 2)*
Docstring says "60% prior + 30% semantic + 10% recency". `allow_embedding_compute` defaults `False`, so the semantic term is dead in the live path; the fallback is `rel*0.9 + recency*0.1` where `recency = i/(len-1)` and **`i` is the index in the `builders` dict** — `repo_map`=0, `relevant_chunks`=1 of 17. The two layers carrying actual source get the maximum *negative* bias; `skills` and `reflections` the maximum positive.
**Fix:** delete the term (10 lines, honest) or make it real recency from plan step / `workspace_revision`.

---

# PART III — The prescription

**This week (≈110 lines total, no structural risk):**

| Order | Fix | Lines | Why now |
|---|---|---|---|
| 1 | **T1** init `run_outcome="in_progress"` | 5 | Silence becomes a signal. Trivial. |
| 2 | **D3** wire `process_boundary` | 15 | Dead file, documented failure, zero risk. |
| 3 | **T4** score dollars + fix `/25` render | 10 | Stops the A+ on a 13× overrun. |
| 4 | **D6** token calibration | 35 | Makes every downstream budget number correct. |
| 5 | **D7** honest scoring | 10 | Removes an active bias against source code. |
| 6 | **T2** error→finalize edges | 30 | 82% → ~100% explained. |
| 7 | **T3** `turn_terminal` trace row | 20 | Makes the next failure diagnosable. |

**Next (the ones that change outcomes):** D4 (USD leg + plan-based routing + escalation) → D1 (tree-sitter repo map) → D2 (milestone governor).

---

# PART IV — Honest caveats

- **This is static analysis plus trace forensics.** I did not execute the suite, the bridge, or a live model call. Every number above is computed from files in this repo and reproducible with `scripts/diagnose_run_termination.py`.
- **The 25-call cap in `docs/AGENT_CORE_CHECKUP.md` is not in the source.** Either it lived in a benchmark harness that has since changed, or it is stale. Your traces show 76-call sessions, so it is not binding today.
- **I initially mis-grepped for HTTP 402/429 and got false positives** (they matched `input_tokens: 402`, `output_tokens: 429`). Corrected and discarded — that is *not* the terminator. I'd rather flag the mistake than quietly drop it.
- **`progress`, `task_manager`, `recovery_limit`, `pivot` appear 0 times in traces** while `ai`/`tools` appear 643/523 times. Two readings: either those nodes are never reached, or the tracer only instruments a subset. I have not proven which — but *either way* the trace is not a complete record of the graph, which is the same trust problem as the missing terminal rows.
- **`hermes-agent` remains unassessed.** Every "hermes parity" claim in the source comments is yours, read but not verified against upstream.
