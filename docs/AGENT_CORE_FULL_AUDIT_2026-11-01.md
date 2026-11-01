# Full agent-core audit — every pipeline, live evidence, root causes

**Date:** 2026-11-01 · **Model:** `z-ai/glm-5.3-flash` via Velona · **Branch:** `arena/0348f25c-pulseairepo`

Scope: the twelve pipelines a turn passes through, plus the harness that measures them.
Everything below is a receipt, not an impression: 4 live sessions, 6 offline runs of
`scripts/agent_core_checkup.py` (54 probes), 1 full test suite (3,209 tests collected), and 12 defects.

---

## 0. The one-line answer

The agent core **does not break**. Across 4 live runs and ~21 turns it never crashed,
never hung, never lost the workspace, and never ended a turn without a recorded reason.
What it does is **stop without admitting it**: three separate verdict surfaces
(the bridge frame, the finalize log, the CI job) each reported success on runs that had
failed. Nine of the twelve defects below are *reporting* defects, not behaviour defects.

| Dimension | Verdict | Evidence |
| :--- | :--- | :--- |
| Crash / hang stability | **healthy** | 0 crashes, 0 watchdog fires, 21/21 turns produced a terminal frame |
| Context & compaction | **works, too late** | history 2 → 129 messages; compaction fired (`context_engine_lines=4`) but the per-turn cap is fixed while prompts grow |
| Tool layer | **works, with one blind tool** | `read_terminal_output` failed every turn with no cause shown |
| Error classification | **was broken → fixed** | 5 of 7 vendors' auth bodies classified `unknown/retryable`; a connection reset **crashed** the classifier |
| Verdict honesty | **was broken → fixed** | `finalize done: completed` on budget-cut turns; CI green on a 0/7 run |
| Measurability | **was broken → fixed** | the harness's own 20-iteration cap was the binding constraint, not the agent |
| Import integrity | **was broken → fixed** | the core needed a **web-search package** and two provider SDKs to import at all |

---

## 1. The runs

| Run | Cap / config | Result | What it proved |
| :--- | :--- | :--- | :--- |
| `41288766831` | 600k, 20 iters | 4/7 completed, turns 5–7 cut | Baseline. Turns 5–7 hit `tokens 626–658k/600k` |
| `41290247998` | **1.2M**, 20 iters | 2/7, **halted at 6** | The cap was never the binding constraint: `iterations 20/20` ×3 |
| `41285084516` | — | 0/7 | `402 Balance ₹0.00` → classifier fix → halt path |
| `41285588347` | — | 0/7, 7.5s | Halt path verified; CI gate now correctly **red** |
| `41291666232` | 1.2M, **45 iters** | 0/7, 5.3s | **Blocked:** `402 Balance ₹0.00` again — the refill was consumed by the run above |

### 1.1 Run `41290247998` — the measurement that matters

```
turn 1  completed   4 calls   120,203 tok   74s
turn 2  completed  14 calls   352,513 tok   98s
turn 3  CUT        33 calls   716,050 tok  235s   verification=passed, 22 steps
turn 4  CUT        26 calls   852,945 tok  247s   verification=unverified, 35 steps
turn 5  CUT        27 calls   925,941 tok  279s   verification=passed, 44 steps
turn 6  FAIL       13 calls         0 tok    4s   "Wallet balance exhausted mid-stream"
turn 7  —                                   0s   not attempted (halt)
```

And the budget lines:

```
[budget] exhausted: iterations 20/20 >= budget      (three turns in a row)
tokens: 716,050 / 852,945 / 925,941 — against a cap of 1,200,000
```

**Read that carefully.** The turns were cut at **20 of 20 iterations** while the token cap
sat **unapproached**, and every cut turn had already **passed verification**. The model was
not failing to work. My harness had given it the same budget as a first turn.

### 1.2 The confound, stated plainly

`scripts/run_long_session.py` did this:

```python
env["AGENT_ITERATION_BUDGET"] = str(args.max_llm_calls)   # default 20
```

The agent's production default is **45**. So every "budget-cut" verdict this harness ever
produced measured a limit the harness chose — and my own 1.2M-token A/B was worthless
because raising the token leg left the iteration leg at 20.

**Fixed:** `--agent-iteration-budget` (45) and `--max-llm-calls` (60, a real safety stop that
now actually gates) are separate. When the safety stop fires, the verdict says
*"HARNESS ABORT — this measures the harness, not the agent."*

---

## 2. Every pipeline

`python scripts/agent_core_checkup.py` — offline, keyless, ~5 s, 54 probes.

| # | Pipeline | Checks | Result |
| ---: | :--- | ---: | :--- |
| 1 | Ingress (frames, malformed input, protocol version) | 3 | healthy |
| 2 | Session (id, `thread_id == session_id`, workspace re-bind) | 3 | healthy |
| 3 | Prompt assembly (`AGENTS.md` → prompt, system messages) | 3 | healthy |
| 4 | Context engine (unknown-model window, budget, cache prefix, attribution) | 4 | healthy |
| 5 | Compaction (prune, salvage, lock contention, fence, wiring) | 6 | healthy |
| 6 | Model call (factory, output cap, normaliser, redaction, orphan results, loops) | 7 | healthy |
| 7 | Failure recovery (classification, retry, compression, transport) | 5 | **2 defects fixed** |
| 8 | Tools (resolution, transaction, write guard, ordering) | 6 | healthy |
| 9 | Loop control (budget legs, no-tool loops, duplicate guards, finish gate) | 6 | healthy |
| 10 | Verification (evidence, derived status, contracts) | 4 | healthy |
| 11 | Persistence (checkpoint round-trip, pairing, watchdog) | 4 | healthy |
| 12 | Finalize (outcome fields, budget reason, error surface, cancel) | 4 | **1 defect fixed** |
| 13 | Hygiene (keyless import, orphans, missing packages) | 4 | **3 defects fixed**, 2 warnings |

---

## 3. The twelve defects, with causes

Grouped by **root cause**, because the grouping is the lesson.

### Cause A — carried-over hermes code that does not exist here (4 defects)

| # | Defect | Effect |
| :--- | :--- | :--- |
| 1 | `from agent.reasoning_timeouts import ...` **unconditional**, inside the server-disconnect branch | Classifying a bare **connection reset crashed** with `ModuleNotFoundError` — a recoverable blip became an unclassified crash |
| 2 | `from agent.error_classifier import ...` in the dashboard, inside `except Exception: return None` | **Every** API failure produced **no error surface**. A ₹0 wallet reported as "the agent did nothing" |
| 3–4 | `hermes_state.is_disk_full_error`, `agent.errors.MoAPresetNotFoundError` (guarded) | Guards prevent the crash, so the **features are dead**: disk-full is never named disk-full, MoA drift never recognised. The fallback is the real code and nobody tested it as such |

### Cause B — optional dependencies imported at module scope (3 defects)

| # | Defect | Effect |
| :--- | :--- | :--- |
| 5 | `src/llm/factory.py` imported **both** `langchain_google_genai` and `langchain_groq` at import | The core needed **every** provider SDK installed to import, even with provider `custom` |
| 6 | `src/tools/web_tools.py` imported `ddgs` at module scope | A **web-search library** was a hard prerequisite for `chat_graph`. This is why `pytest src/tests/` was **uncollectable** (43 `ModuleNotFoundError`s) |
| 7 | `src/graphs/basic_graph.py` built its client at import | Importing the graph package required credentials |

After the fix: **3,209 tests collect** (was: collection error), full suite **3,111 passed / 67 failed / 29 skipped in 394 s**.

### Cause C — a status value trusted instead of the record (3 defects)

| # | Defect | Effect |
| :--- | :--- | :--- |
| 8 | `402 Balance ₹0.00` classified `unknown`, `retryable=True` | Seven turns spent retrying a **terminal** billing failure. Now `billing`, non-retryable, one predicate instead of seven copy-pasted lists |
| 9 | Auth bodies: only 2 of 7 vendors matched | OpenAI / Anthropic / Gemini / OpenRouter bad-key bodies were **retried** instead of rotating the credential |
| 10 | `verdict` computed `budget_exhausted` only if `not verified_ok` | A **verified** budget-cut turn reported `finalize done: completed`. The UI, the ledger and the log all read that field |

### Cause D — the measurement was the thing being measured (2 defects)

| # | Defect | Effect |
| :--- | :--- | :--- |
| 11 | Harness wrote its own 20-iteration cap into `AGENT_ITERATION_BUDGET` | Every "budget-cut" result measured the harness. See §1.2 |
| 12 | The CI job never read `SESSION_EXIT` | A 0/7 run showed **✅ green**. Fixed with a gate after the evidence upload (verified red on `41285588347`) |

### Also found (not a bug, a decision)

`turn_model_wall(sid)` was replaced by the stronger `pop_turn_model_accounting(sid)` (which
attributes sub-agent model time), but two tests still pinned the **old symbol** — so a correct
receipt reported a red suite. Tests now pin the contract, not the identifier.

---

## 4. Why these defects survived so long

Four structural reasons, each visible in the evidence:

1. **No harness ever ran more than one turn.** Every green result in this repo was a first
   turn with an empty history. Context growth, compaction pacing and per-turn budgets are
   invisible in a first turn.
2. **Green tests over broken entry points.** After the `create_server()` refactor, all six
   unit tests passed while `python mvp/server.py` served **nothing** (endpoints `000`).
3. **Broad `except` on the error path.** Both `ModuleNotFoundError`s were inside
   `except Exception: ...` blocks. The error path is the least-tested code and the most
   catch-all.
4. **A 20-line test pinned symbols instead of contracts** (`turn_model_wall`), so a refactor
   produced a false red while a *real* regression (the budget-cut verdict) produced no red.

---

## 5. What the strongest OSS agent cores do differently

Read against the actual architectures, not the READMEs.

| Repo | What it does | Our equivalent | The gap |
| :--- | :--- | :--- | :--- |
| **OpenHands** | **Event-sourced** memory: immutable `EventStream`, `View.from_events()` replayed each step; condensation inserts a **CondensationAction tombstone** that forgets an event-ID range and inserts a summary — so compaction is itself an auditable event, with **10 pluggable condenser strategies** [2](https://gist.github.com/sam-saffron-jarvis/0f5e9b76942678019f15bdd1bd60bbb6) | `ContextEngine` + `HistoryCompactor` + `compression_fence` | We compact, but compaction is **not an event**: you cannot replay "what did the model see on turn 5". Ours is one strategy with heuristics, theirs is a pipeline of 10 chosen by config |
| **OpenHands** | The **agent can request condensation itself** via a `request_condensation` tool | No equivalent | The agent cannot say "my context is polluted, compact now" — the trigger is purely ours |
| **SWE-agent** | **ACI discipline**: a `search` tool that lists only *files with matches* ("showing the model more context about each match proved too confusing"), and empty output returns *"Your command ran successfully and did not produce any output"* [1](https://github.com/trilogy-group/SWE-agent-ti) | `build_failure` said `Tool failed: read_terminal_output` with **no output at all** | This is exactly the §3 defect: our failure notice is less informative than a 2024 paper's empty-output message |
| **Aider** | **Repo map**: tree-sitter tags + **PageRank** over the symbol reference graph, budgeted to **~1/8 of the window, clamped 1k–4k tokens**, binary-searched to fit, cached by mtime+hash [1](https://llms-technical-reviews.com/p/aider/) | `src/context/chunk_index`, `bounded_scan`, embedding cache | We spend context on **retrieved chunks**; they spend 1–4k tokens on a **whole-repo symbol ranking**. For a 227-module repo that is the difference between "here are 8 files" and "here is the shape of the project" |
| **Cline** | **Tools return errors as data** (`{success:false, error, isError:true}`), never throw; the docs state this is so "the agent [can] see the error and adjust" [1](https://docs.cline.bot/sdk/guides/going-to-production) | `build_failure` → recovery state | We do keep the loop alive (good) but stripped the cause (bad). Their contract is explicit; ours was accidental |
| **OpenCode** | Client/server split: `opencode serve` publishes an **OpenAPI 3.1 spec** at `/doc`, every UI is a client; provider-agnostic via Models.dev (75+) [2](https://medium.com/@gwrx2005/orca-pi-and-opencode-open-source-agentic-tools-and-the-changing-practice-of-software-development-e2a208d898ef) | `src/bridge/protocol.py` (hand-rolled line protocol, 2 versions) | Our protocol has no schema artifact a client can validate against. Theirs is generated and versioned |
| **Goose** | Rust core, **MCP-native**, donated to the Linux Foundation (vendor-neutral); 5-inspector pipeline | `mcp_client`, `toolsets` | Ours is MCP-capable, not MCP-shaped |
| **All of them** | A **loop/stuck detector** as a first-class component (OpenHands ships a 487-line `StuckDetector`; harness guides describe fingerprinting `(tool, result)` triples — "one production system saw the same answer repeated 58 times") [3](https://stevekinney.com/writing/agent-loops) | `loop_guards` + `progress_guard` + `repetition_guard` — **three** overlapping implementations | We have three guards that can disagree (a checkup probe exists purely to assert they agree), no single stuck detector |

**The pattern:** every mature core treats *"what the model sees"* as a versioned, auditable
artifact. We treat it as a function of current state. That single difference is what makes
their long sessions debuggable and ours a matter of bisecting logs.

---

## 6. Prioritised fixes

| P | Fix | Why it matters | Effort |
| :--- | :--- | :--- | :--- |
| **P0** | **Budget by history, not by constant.** The per-turn token cap must scale with the prompt the turn actually carries, or the cost leg must be the binding one (`AGENT_COST_BUDGET`). Evidence: turns needing 700–900k tokens were cut against a fixed number | A 7-turn session cannot finish work after turn 4 today, regardless of model | S |
| **P0** | **Compaction as an event.** Record `{range, summary, model, tokens_before/after}` in the journal (OpenHands' tombstone) | Turns `completed=false` would be replayable instead of inferred | M |
| **P1** | **One stuck detector.** Merge `loop_guards` / `progress_guard` / `repetition_guard` behind one fingerprinting interface | Three copies = three drift points (already diverging once) | M |
| **P1** | **Every tool failure carries its cause** — enforce at the `ToolOutcome` boundary with a test, not per-branch strings | The `read_terminal_output` defect was a *missing line in one branch*; the contract prevents the class | S |
| **P1** | **Delete the 5 orphan provider modules** (`src/providers/*_provider.py`) — dead, credential-hungry at import, and they look authoritative | Untested code that appears to be the provider layer | S |
| **P2** | **Aider-style repo map** (tree-sitter + PageRank, 1–4k token budget) alongside chunk retrieval | Cheaper than embeddings for "what shape is this project" | L |
| **P2** | **Agent-requested compaction** (`request_condensation` tool) | The agent knows when its context is polluted before we do | S |
| **P2** | **Schema artifact for the bridge protocol** (JSON Schema or OpenAPI, generated from `protocol_v2.json`) | A client can validate instead of discovering drift at runtime | M |
| **P3** | **Fail the body checkup on WARN** once the two standing warnings are fixed | WARNs are the next incident; today they are tolerated by design | S |

---

## 7. Honest limits of this audit

| Not covered | Why |
| :--- | :--- |
| MCP, LSP (10 modules), preview proxy, voice, A2UI, subagents' behaviour | Need a live host process or a real session; import-checked only |
| The other 73 modules of `src/context` (54 files) beyond the 5 probed | Behavioural probes sit on the single-turn critical path |
| Live behaviour with a *healthy* wallet | The refill was consumed mid-turn-6 of run `41290247998` |
| 67 full-suite failures | Pre-existing and **not yet triaged** — they are listed, not explained. Attempting that triage was interrupted; do not read them as "known-fine" |

**Wallet status — the refill bought less than one run.** Run `41290247998` (1.2M cap) drained
it at turn 6 mid-stream; the immediately following run `41291666232` died on turn 1 with
`402 Balance ₹0.00` in 4.1 s. Priced from the runs' own telemetry:

```
observed rate            $0.153 per 1M tokens  (run A: $0.0943 / 617,579 tokens)
a 900k-token turn   ~=   $0.14
one 7-turn session  ~=   $0.96
Rs 10 (the minimum top-up) ~= $0.11  ->  0.8 of one turn
```

So the ₹10 minimum buys **most of a single turn** of a mature 7-turn session. The
**45-iteration measurement is the one thing still unrun** — it needs ~$1 (≈₹90) of credit.
Until then, "does the agent finish all 7 turns when its budget is not the constraint?" is
**unanswered**, and this document does not claim otherwise.
