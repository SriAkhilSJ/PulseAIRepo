# PulseAI → Hermes Alignment: Analysis & Zero-Budget Roadmap
**From:** Office of the CTO · **Date:** 2026-08-11 · **Constraint:** No API budget now; keys arrive later · **North Star:** Build PulseAI in the image of Hermes Agent

---

## Part 1 — Hermes's Two Sacred Laws (and why they ARE your two pains)

Hermes's `AGENTS.md` opens by naming **two properties that shape almost every design decision**. Read them carefully — they are the exact diagnosis of your frustration:

> **Law 1 — "Per-conversation prompt caching is sacred."** *"A long-lived conversation reuses a cached prefix every turn. Anything that mutates past context, swaps toolsets, or rebuilds the system prompt mid-conversation invalidates that cache and **multiplies the user's cost**."*

> **Law 2 — "The core is a narrow waist; capability lives at the edges."** *"Every model tool we add is sent on every API call, so the bar for a new core tool is high."*

Now map them to your complaints:

| Your pain | Hermes law it violates | PulseAI's actual behavior |
|---|---|---|
| **Latency** (25–56s/step, API is 0.5–1s) | **Law 1** | Rebuilds a 16-layer context *every call*; 73% of tokens are static overhead reprocessed 30×. Runs on a non-caching provider. |
| **"1 call = 1 tool"** (cost multiplier) | **Law 2 + PTC** | Binds **all 26 tools every call** (no toolset waist); weak free models under-batch; PTC exists but isn't exercised. |

**The conclusion is liberating:** you don't have a latency problem and a tooling problem — you have **one problem: the architecture doesn't obey Hermes's two laws.** Fix the architecture and both pains dissolve *when a caching-capable model arrives.* The no-money phase is the perfect time to do exactly that structural work.

---

## Part 2 — Hermes Alignment Scorecard (mechanism by mechanism)

I audited PulseAI's source against Hermes's. Here's the honest scorecard:

| Hermes mechanism | Hermes does | PulseAI today | Gap | Budget to fix? |
|---|---|---|---|---|
| **Prompt-cache stability** (Law 1) | Byte-stable system prefix for the life of a conversation; only `/compress` ever mutates it | `cache_preservation.py` + sentinel exist, **but** a task-aware 16-layer rebuild reorders context per call → fights the cache | **High** | ✅ Code only |
| **Narrow waist / toolsets** (Law 2) | Tiny `_HERMES_CORE_TOOLS` + named toolsets + `check_fn` service-gating (tools appear only when configured) | **No toolset system.** All 26 tools bound every call (5,686 tool-def tokens/call) | **High** | ✅ Code only |
| **PTC (Programmatic Tool Calling)** | `execute_code` calls tools via **TCP RPC**; multi-step pipelines collapse into **one zero-context-cost turn** | Has `execute_code` with local tool-stub dispatch (good!) — but **explicitly "No RPC"**, and weak models never use it | **Med** | ✅ Code only |
| **Agent loop** | Dead-simple synchronous `while` loop, interrupt checks, iteration budget, one-turn grace call | LangGraph state machine, **2,901-line** `chat_graph.py` god-file | **Med** | ✅ Code only |
| **Delegation / subagents** | `delegate_task` (single + batch parallel), isolated context, leaf/orchestrator roles | Has `delegate_to_subagent` + `delegate_to_subagent_batch` | **Low** | ✅ Already close |
| **Skills (procedural memory, edges)** | `skills/` + `optional-skills/`, agent-curated, lifecycle curator, agentskills.io standard | Has `skill_manager` + lifecycle (D39) — **conceptually aligned** | **Low** | ✅ Close |
| **Model-agnostic, switch w/ no code** | `hermes model` — provider/model is config, not code | Has `providers/` (groq/openai/gemini/custom) — **aligned** | **Low** | ✅ Aligned |
| **Engineering discipline** | Footprint Ladder, behavior-contract tests (no change-detectors), dependency pinning, "verify the premise", E2E over mocks | 148KB review doc, 40 "D-rounds" of patches accumulating faster than simplifying | **Med** | ✅ Process only |

**The pattern is clear and encouraging:** PulseAI has already *stolen* a lot of Hermes's surface patterns (delegation, skills, PTC, cache-preservation scaffolding). What it has NOT done is adopt Hermes's **two load-bearing laws** and its **discipline**. That's the work — and none of it costs a rupee in API spend.

---

## Part 3 — The Zero-Budget Reality (what you CAN do now)

You have no money for models right now. That does NOT mean stalled. It means this is the **architecture phase.** Everything below is code structure, testable locally, and makes the eventual key-flip a one-line config change instead of a rewrite.

**Critical enabler — develop and validate WITHOUT API keys:**
- Stand up a **local model path** (Ollama / llama.cpp) pointed at your existing `custom` provider (`CUSTOM_BASE_URL=http://127.0.0.1:11434/v1`). Even a small local model lets you exercise the loop, the toolset system, the cache-stability tests, and PTC — all offline, all free. You don't need a *smart* model to validate *architecture*; you need the pipeline to run end-to-end.
- This is exactly how you de-risk Phase 1: when keys arrive, the only unknown left is model quality — not plumbing.

---

## Part 4 — The Phased Plan

### 🟦 PHASE 0 — Architectural Alignment (NOW · zero budget · code + tests only)

This is the productive no-money phase. Five workstreams, each independently shippable and testable offline:

#### P0-A · Build the toolset system (obey Law 2 — the narrow waist)
**This is the single biggest token-cost fix in the codebase and it needs no API spend.**
- Introduce `TOOLSETS` (a dict of named sets) + a tiny `_PULSEAI_CORE_TOOLS` list, mirroring Hermes's `toolsets.py`.
- Add `check_fn` service-gating: a tool (e.g. `browser_*`, `web_search`) only enters the schema when its prerequisite is configured.
- Refactor `chat_graph.py`'s `tools = [...]` (all 26) to resolve from the active toolset. Default coding tasks get a small set (`read_file, write_file, edit_file, search_code, list_files, run_terminal, execute_code, typecheck_workspace`); browser tools load only for UI tasks; web tools only when search is configured.
- **Measured target:** tool-def tokens/call drop from ~5,686 → ~2,000 for a typical coding turn. (Hermes keeps core tools minimal for exactly this reason.)
- **Test:** assert the resolved toolset for a coding session contains the core set and EXCLUDES browser/web until gated — a behavior contract, not a count snapshot.

#### P0-B · Make the prompt prefix byte-stable (obey Law 1 — caching sacred)
- Today: 16-layer task-aware rebuild reorders context every call → cache-busting. Hermes's rule: **the prefix never changes mid-conversation; only `/compress` mutates it.**
- Restructure into **two zones:**
  - **Stable prefix** (system prompt + persona + stable repo map + active toolset schemas) — emitted once, byte-identical every turn. You already have the `VOLATILE_TAIL_PREAMBLE` sentinel — promote it to the hard boundary.
  - **Volatile tail** (task-specific layers, recent history, current plan) — the ONLY thing that changes per turn.
- Move the task-classifier relevance scoring into the *volatile tail*, never the prefix.
- **Test:** run two consecutive turns on the same conversation and assert the prefix is byte-identical (a real cache-stability contract test). This is the test that, once green, guarantees Phase 1's cost drop.

#### P0-C · Elevate PTC to the default execution mode
- PulseAI's `execute_code` already has local tool-stub dispatch (`_PTC_MAX_TOOL_CALLS=50`). It works — the model just never uses it on free models.
- Make PTC the *taught default* in the persona: "to read 3 files and write 2, write ONE `execute_code` script that does all five and returns only the summary." (Hermes's exact philosophy: *"collapsing multi-step pipelines into zero-context-cost turns."*)
- Optionally adopt Hermes's **TCP RPC** pattern later (lets tools live on Docker/SSH backends) — but local dispatch is enough to get the win now.
- **Test:** a PTC script that calls `read_file` twice + `write_file` once returns one result message (not three turns).

#### P0-D · Simplify the loop toward Hermes's model
- Hermes's loop is ~15 lines: `while budget: call(); if tool_calls: handle+append; else: return`. PulseAI's is a 2,901-line LangGraph god-file.
- You don't have to abandon LangGraph — but **extract `chat_graph.py` into `nodes/` modules** (ai_node, tool_node, progress, verify_gate, finalize) so the budget/interrupt/cache logic is readable and testable in isolation. This is exactly the "refactor god-files into clean modules" work Hermes explicitly welcomes.
- Wire the iteration budget cleanly (you have `_iteration_budget()` — make it the single governor, recursion_limit the backstop, as you already intend).

#### P0-E · Adopt Hermes's engineering discipline
- **Footprint Ladder:** before adding any tool/feature, ask "can this be a skill or CLI command instead of a core tool?" Default to the edge.
- **Behavior-contract tests, not change-detectors:** stop writing tests that freeze counts/strings. Hermes bans source-reading tests outright — adopt that.
- **Dependency pinning:** add upper bounds to all deps (`>=floor,<next_major`). Hermes does this after a real supply-chain compromise (litellm) — do it before, not after.
- **Freeze the D-round treadmill:** stop accumulating D41, D42… Pick ONE task and converge.

**Phase 0 exit criteria (all offline, all testable):** byte-stable prefix test green ✅ · toolset resolution test green ✅ · PTC one-turn test green ✅ · `chat_graph.py` split into modules ✅ · local model runs the loop end-to-end ✅.

---

### 🟩 PHASE 1 — Flip to a Cached Real Provider (when keys arrive)

If Phase 0 is done, this is **a config change + a measurement**, not engineering:
- Point the agent loop at one cached provider (DeepSeek V3 is the startup-sweet-spot: prompt cache + strong tool-calling, ~$0.07/M on cache hits). Keep free models ONLY for the auxiliary/janitor path.
- **Measure cache hit rate** with the `prompt_cache_audit.py` you already built — set a target (≥70%). On a caching provider with a byte-stable prefix, the 73% static overhead you measured drops to ~10%.
- Re-run your shadcn + chat-app evals. Expected: latency **3–10× lower**, effective token cost **~60% lower** even at higher sticker prices, and the model now *actually batches* and *actually uses PTC*.

**Why Phase 0 makes Phase 1 cheap:** the byte-stable prefix (P0-B) is what lets the cache hit. The narrow waist (P0-A) is what makes each hit cheaper. Without Phase 0, a caching provider still busts its cache every turn and you'd feel none of the benefit.

---

### 🟥 PHASE 2 — Compete (with a real model proving the architecture)

Only now does "better than the competition" become real:
- The chat-app task goes **green** (a model that applies `"use client"` and doesn't hallucinate `finish`).
- The **skills learning loop** (Hermes's signature "self-improving" moat) activates — skills created from experience, curator lifecycle, cross-session session_search. PulseAI has the scaffolding; it needs a model smart enough to curate.
- **Delegation + parallel subagents** for real workstreams.
- Then — and only then — the VSCode desktop fork (your own architecture review §2 agrees: fork last).

---

## Part 5 — The Decision & Checkpoints

The plan above needs **no money and no keys to start.** Phase 0 is pure architecture work that makes the eventual key-flip trivial and de-risks everything via a local model.

**What I need from you to begin Phase 0:**

1. **Confirm the north star:** align PulseAI to Hermes's two laws + discipline. (I'm assuming yes — you said you're following Hermes.)
2. **Workstream order.** My recommendation: **P0-B (cache stability) → P0-A (toolsets) → P0-C (PTC) → P0-D (loop simplification) → P0-E (discipline)** in parallel with standing up a local model for validation. P0-A and P0-B together attack ~80% of your token/latency waste.
3. **Permission to start coding.** I can begin with **P0-B** (the byte-stable prefix + cache-stability contract test) since it's the highest-leverage and unblocks the Phase-1 cost win — or **P0-A** (the toolset system) if you'd rather cut the per-call tool-def cost first.

**One honest caveat to carry through:** the *latent* pain (4 failed chat-app runs, hallucinated tools, ignored conventions) will NOT fully resolve until Phase 1's stronger model. Phase 0 makes the architecture correct and cache-friendly; Phase 1 makes the brain capable. Sequence them honestly — don't expect a free model to pass the chat-app task even on a perfect architecture.

---

*The bones of PulseAI are good — you've already stolen the right surface patterns from Hermes. Now steal the two laws and the discipline that make those patterns actually pay. That's the path from "upset" to "competitive," and it starts today, for free.*
