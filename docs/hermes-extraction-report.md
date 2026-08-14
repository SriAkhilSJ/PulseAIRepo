# What PulseAI Should Steal From NousResearch `hermes-agent`

**Date:** 2026-08-06 (regenerated 2026-08-07 after sandbox wipe — all receipts re-verified against a fresh clone)
**Direction:** yours — *"READ AND EXTRACT THE VALUE OF THAT CODEBASE. DON'T BE SCARED OR CONCLUDE BY CODEBASE."*
**What I did:** cloned their repo (3,848 Python files), read the agent core: context engine, context compressor, conversation compression, iteration budget, curator, LSP manager, code-execution tool, session-search tool, delegate tool.
**How I ranked what to steal:** your 4 scoreboard metrics — **latency, context quality, token budget, fewer LLM calls**.

Everything below has a file:line receipt in THEIR tree so anyone can check I didn't make it up. ⚠️ Their `main` moved one receipt between Aug 6 and Aug 7 (the prompt-cache invariant slid from `context_engine.py:229-245` to `:249-263`); noted below.

---

## The short version

Hermes is a serious, battle-tested agent. They are **ahead of us on running cheap** (they treat every token and every LLM call like money). We are **ahead of them on finding code** (our code index is genuinely better than what they use). The plays worth stealing, in the order I recommend doing them:

| # | Steal | Our debt | Biggest win on your scoreboard |
|---|-------|----------|-------------------------------|
| 1 | **One-script tool calling (PTC)** | D18 | fewer LLM calls + tokens |
| 2 | **Zero-LLM session search** | D16 (redesigned) | LLM calls → ZERO for memory recall |
| 3 | **Prompt-cache audit** | D19 | tokens/cost (invisible leak) |
| 4 | **Sub-agent auto-deny** | D20 | safety + no deadlocks |
| 5 | **Aux-model housekeeping** | D21 | tokens + main-model cache |
| 6 | **Compaction hardening pack** | D22 | context quality on long sessions |

---

## STEAL #1 — Programmatic Tool Calling (PTC) → debt D18
**Receipt:** `tools/code_execution_tool.py:1-22` (+ `agent/iteration_budget.py` — PTC iterations are *refunded*, `:28-29`)

**What it is, plainly:** today, when our agent needs to do 6 steps (read file A → grep → read file B → edit → run test → read output), that's **6 separate LLM calls**, and every intermediate dump lands in the chat window forever. Their move: the model writes **ONE Python script** that calls the tools inside a sandbox, loops, filters, and only the script's final `print()` output comes back into the window.

**Literal example.** Instead of:
```
turn 1: read_file("a.py")        → 4,000 chars dumped into chat
turn 2: read_file("b.py")        → 4,000 more chars
turn 3: run_terminal("pytest")   → 9,000 chars of test output
turn 4: (model finally answers)
```
the model emits one script:
```python
a = read_file("a.py"); b = read_file("b.py")
out = run_terminal("pytest -q")
print(out.splitlines()[-5:])     # only THESE 5 lines re-enter the window
```
**Scoreboard:** 4 LLM calls → 1. ~17,000 chars parked in context → ~200. Context stays clean because intermediate junk never enters it.

**Their guardrails (copy all):** 300-second cap, max 50 tool calls per script, 50KB stdout cap, and PTC script runs are **refunded** from the iteration budget so a script doesn't eat the agent's turn allowance.

**Why we can do it CHEAPER than them:** they need Unix-socket/file RPC because their tools can live on remote machines (Docker/SSH). Ours are all in-process Python — our "RPC" is just a function call. No socket layer needed.

---

## STEAL #2 — Zero-LLM session search → debt D16 (SPEC CHANGED)
**Receipt:** `tools/session_search_tool.py:1-46`

**What it is:** searching your *past conversations* ("how did we fix the login bug last week?") using **pure FTS5 database search — no LLM call at all**. Three modes: DISCOVERY (search → top sessions, each with the matching snippet ±5 messages plus the first 3 and last 3 messages of that session as "bookends" so the model can judge relevance), SCROLL (walk up/down around any hit), BROWSE (recent sessions).

**The lesson that sold me (their issue #19434):** they USED to have the LLM summarize old sessions and index the summaries. A cron job later "demoted" those hand-written summaries and recall went bad — so they ripped the LLM out of the search path entirely. **Full text never lies; summaries drift.** That matches our own philosophy (verbatim audit ledger > vibes).

**Scoreboard:** this changes our D16 "cross-session playbook" from "spend LLM calls to remember" to "spend ZERO LLM calls to remember." Latency = one SQLite query.

---

## STEAL #3 — Prompt-cache prefix audit → debt D19
**Receipt:** `agent/context_engine.py:249-263` (was `:229-245` on Aug 6 — upstream moved it; text verified identical in substance), usage counting at `:140`/`:319`

**What it is, plainly:** LLM providers (Anthropic/OpenAI) secretlycache the *beginning* of your prompt. If the beginning is **byte-identical** turn-to-turn, the reused part costs ~10x less and responds faster. Hermes treats "the default path leaves the request **byte-identical**" as a hard invariant and actually counts `cache_read_tokens`.

**Our exposure:** our context engine builds a **16-layer composition per turn** — layer weights adapt, sections re-order, numbers update. If the front of our prompt jitters by even one byte, we silently lose the cache discount **every single turn**. We've never measured this.

**Plan is measure-first:** log estimated cache-break position per turn (first byte that differs vs previous turn). If the prefix is stable, file D19 as "measured, no leak." If it breaks early, re-order layers so stable stuff parks at the front.

**Scoreboard:** pure latency + cost. Zero behavior change.

---

## STEAL #4 — Sub-agent dangerous-command auto-deny → debt D20
**Receipt:** `tools/delegate_tool.py:63-91`

**The bug shape (we have it too):** when a *sub-agent* hits a dangerous command, it asks for approval... inside its own private conversation. **No human ever sees that prompt.** Hermes found it can even **deadlock** (worker thread waiting on stdin that the parent UI owns). Their fix: worker threads get a non-interactive callback installed at spawn: default = **auto-deny** (with a warning logged), opt-in = auto-approve for batch/cron mode.

**Scoreboard:** not a metric win — a "sub-agents can't hang forever or approve themselves" correctness win. Small change, high blast-radius protection.

---

## STEAL #5 — Housekeeping never on the main model → debt D21
**Receipt:** `agent/curator.py:17-18` — *"Uses the auxiliary client; **never touches the main session's prompt cache**."*

**What it is:** summaries, memory cleanup, skill gardening — all routed to a **cheap auxiliary model**, so (a) you don't pay flagship prices for janitor work and (b) the janitor's calls never perturb the main conversation's cache prefix (see D19). We should route SmartSummarizer-style jobs off the main model.

**Scoreboard:** token budget (cost) + protects D19.

---

## STEAL #6 — Compaction hardening pack (4 patterns, one debt) → debt D22
**Receipts:** two triggers `agent/context_engine.py:181-205` · placeholder `agent/context_compressor.py:399` · protected head/tail `agent/context_compressor.py:1319-1327` · iterative summaries + anti-thrash `:1319-1359`

Four small hardenings that together decide whether a 3-hour session stays sharp:

1. **Two triggers, not one.** A cheap **proactive prune** runs first — old tool outputs get replaced by `[Old tool output cleared to save context space]` (`context_compressor.py:399`) with NO LLM call. Expensive LLM summarization only fires when pruning isn't enough. (Today we only have the expensive path.)
2. **Protected head and tail.** Compaction never touches the first 3 messages (original instructions) and the most recent ~20K tokens (what you're doing right now). Summaries only cover the middle.
3. **Iterative, not rebuilt.** New summaries *extend* the old summary instead of re-summarizing the whole session from scratch — cheaper and doesn't drift.
4. **Anti-thrash telemetry.** They track when compaction fires too often and back off — a guard against the "summarize → stuff breaks → summarize again" doom loop.

**Scoreboard:** context quality on long sessions + fewer LLM calls (prune is free).

---

## Observed but NOT adopted (and why)

- **LSP diagnostics-delta** (`agent/lsp/manager.py:19-26`): snapshot errors *before* an edit, report only *new* errors after — lifted from Claude Code. Elegant, but it requires an LSP server layer we don't run. Parked; revisit if we add language servers.
- **Their RPC transport for PTC** (UDS/file-based): we skip it — our tools are in-process (see Steal #1).
- **Their README claims "FTS5 session search with LLM summarization"** — the current tool has NO LLM in the path (later PRs ripped it out, lesson #19434). README is marketing-stale; trust the code, not the README. We steal the *code* version.

---

## Where WE already lead (do not regress these)

- **Code intelligence:** per-symbol chunks, hybrid BM25 + vector KNN + RRF fusion, mtime-based incremental sync, **import-linked expansion across 6 languages** (our 🔍 detective mode). Their code understanding leans on raw file reads + LSP diagnostics. If a user asks "what breaks if I change this function," we answer from structure; they grep.
- **Learned layer weights:** our context engine learns which layers matter per repo from feedback. They hand-order.
- **Approval UX + crash net:** our tool crashes become graceful error messages (D17, shipped), never turn-death, with a human-readable approval flow. They hit the stdin-deadlock class of bugs in the wild.
- **This audit ledger:** every change we ship has a verdict, proofs, and a debt board. Their history is in commit messages and closed issues.

---

## Adoption order (recommended)

1. **D18 — PTC** (biggest lever on 2 of your 4 metrics)
2. **D16 — session search, zero-LLM shape** (LLM calls → 0 for recall)
3. **D19 — prompt-cache audit** (measure first; cheap to run, possibly free money)
4. **D20 — sub-agent auto-deny** (small, prevents a hang)
5. **D21/D22** — after the above land.

*Ledger mirror: §29 of `ARCHITECTURE_REVIEW.md` (repo). Debt board: D9, D10, D13, D14, D15-remainder, D16, D18, D19, D20, D21, D22, C1, P2.*

---

## SECOND PASS — 2026-08-07 (deep scan of the unmined subsystems)

Direction: founder — "AS I SAID U: CHECK HERMES AGENT, WHAT IT DOES, CAPTURE ITS VALUE AND IMPLEMENT IN THE PULSEAI."

| # | Steal | Status | Receipt |
|---|-------|--------|---------|
| 7 | **Shadow-git checkpoints** (transparent pre-mutation snapshots, one shared store, undo-the-undo restore) | **SHIPPED as D31** (§43, 13 pins, measured 20-30ms/turn) | `tools/checkpoint_manager.py:1-60, 239-277, 919-960, 998+` |
| 8 | **File-state staleness guard** (per-agent read stamps; subagent B's write can't be clobbered by A's stale read) | FILED **D32** | `tools/file_state.py:1-40` |
| 9 | **TRUE parallel sub-agents** (daemon ThreadPool, contextvars copies, `wait(FIRST_COMPLETED, 0.5)` — not as_completed, interrupt-honoring) | FILED **D33** — answers review-1's "sub-agents are synchronous" | `tools/delegate_tool.py:3208-3290` |
| 10 | **Parallel tool batches** (path-overlap checked `_should_parallelize_tool_batch`) | FILED **D34** (needs D32 first) | referenced from `file_state.py` docstring |

We added one guard they lack: `merge-base --is-ancestor` before restore — their shared object DB would happily restore project B's snapshot into project A. Parked items unchanged (LSP diagnostics-delta needs language servers; their RPC transport unnecessary for in-process tools).
