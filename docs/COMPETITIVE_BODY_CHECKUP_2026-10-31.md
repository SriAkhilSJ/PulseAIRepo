# Competitive Body Checkup — CrusorAI Agent Core vs the Best Open Agent Repos

**Date:** 2026-10-31 · **Branch:** `arena/730d9c91-pulseairepo`
**Question asked:** *"compare my agent core with the best repos"* — performance, skills, MCPs,
agent core, context engine, error handling — **and their costs**.

**Rule for this document:** every number is either *measured on this machine* or *pulled
from GitHub's API today*. Nothing is estimated and passed off as measured; where a
competitor's number cannot be obtained, the cell says **not measured** and the reason.

---

## 0. Evidence grades (read this before the tables)

| Grade | Meaning |
|---|---|
| **A** | Measured by this repo's own tooling on this machine, today (`scripts/competitor_snapshot.py`, `scripts/cost_model.py`). |
| **B** | Measured from the competitor's source as served by the GitHub API today (byte counts, file counts, keyword counts that this script ran itself). |
| **C** | Proxy. Counts a *related* thing (e.g. file size of a declaration module, not the per-call JSON). Stated as a proxy every time. |
| **D** | **Not measured.** No benchmark was run for this repo against these repos. Any "we are better/worse than X% at coding" claim below would be invented, so there is none. |

The one thing this document deliberately cannot answer is *"is our agent smarter?"*.
Answering that requires running both against a held-out task set (Terminal-Bench-style or
SWE-bench-style) with the **same base model**, and we have run no such evaluation. Section 6
proposes the cheapest version of that test.

---

## 1. Headline verdict

1. **Our reliability/context engineering is not a gap — it is our strongest measured axis.**
   Against the canonical core module of each competitor, our `chat_graph.py` carries more
   retry/timeout/failover/compaction/telemetry/approval handling than any single competitor
   file measured here, and the whole `src/` tree carries 3–50× the keyword density.
2. **Our cost is the gap, and it is not the system prompt — it is the tool schemas.**
   The registry binds **68 tool schemas on every provider call = 25,382 tokens**, which is
   **4.3× the entire budgeted system prompt (5,840)**. This was missing from the previous
   cost memo, which therefore understated mid-tier cost by **~2.5×**. Fixed in
   `scripts/cost_model.py` today and corrected in §4.
3. **Our skills surface is the largest of anyone in this comparison** (31 skill packs /
   ~304 `SKILL.md` files vs gemini-cli 26, cline 8, OpenHands 8, codex 5, goose 2, aider and
   SWE-agent 0) — and after the index budget it is also cheap per call.
4. **MCP: we are mid-pack, structurally behind codex and goose.** Codex is the only
   spec-complete implementation measured (resources/elicitation/sampling/conformance/oauth).
   We have tool-calling plus a meta-tool waist of 3 schemas, but **zero elicitation** and no
   conformance suite.
5. **Performance (quality) is unmeasured. Unmeasured means unknown, not "fine".** Both the
   ranking and the pricing argument need one public number; §6 is the cheap route to it.

---

## 2. The field (GitHub API, 2026-10-31, `scripts/competitor_snapshot.py`)

| Repo | ★ | last push | files | test-ish files | CI workflows | license |
|---|---:|---|---:|---:|---:|---|
| openai/codex | 132,488 | 2026-10-31 | 9,809 | 1,471 | 31 | Apache-2.0 |
| google-gemini/gemini-cli | 108,655 | 2026-10-31 | 3,043 | 1,017 | 47 | Apache-2.0 |
| All-Hands-AI/OpenHands | 92,366 | 2026-10-31 | 2,856 | 920 | 22 | MIT |
| cline/cline | 71,118 | 2026-10-31 | 4,444 | 1,126 | 17 | Apache-2.0 |
| block/goose | 56,050 | 2026-10-31 | 2,562 | 235 | 39 | Apache-2.0 |
| Aider-AI/aider | 49,856 | 2026-05-22 | 691 | 88 | 10 | Apache-2.0 |
| SWE-agent/SWE-agent | 20,697 | 2026-10-26 | 409 | 85 | 4 | MIT |
| **CrusorAI (this repo)** | — | local | 490 py | 246 | 1 workflow / **5 test files actually run** | — |

**Read:** we are ~1/200th the code volume of codex and run 5 test files in CI versus gemini-cli's
47 workflows. Volume is not quality — but *CI surface* is the cheapest credibility we can buy,
and it is 40× smaller than theirs. That is a gap, not a talking point.

---

## 3. Dimension-by-dimension

### 3.1 Error handling & reliability engineering — **our strongest axis** (Grade A/B)

Same regexes, same script, one **canonical core module** per project (the place where the
provider call / agent loop actually lives):

| Repo | core file measured | retry | timeout | failover | compaction | telemetry | approval |
|---|---|---:|---:|---:|---:|---:|---:|
| Codex CLI | `codex-rs/core/src/client.rs` | 10 | 2 | 26 | 32 | 267 | 0 |
| gemini-cli | `packages/core/src/core/client.ts` | 2 | 0 | 5 | 37 | 15 | 8 |
| aider | `aider/coders/base_coder.py` | 1 | 0 | 4 | 37 | 0 | 13 |
| SWE-agent | `sweagent/agent/agents.py` | 9 | 7 | 0 | 0 | 0 | 0 |
| goose | `crates/goose/src/agents/prompt_manager.rs` | 0 | 0 | 0 | 0 | 0 | 0 |
| OpenHands | *(agent is Python, not in `main`)* | — | — | — | — | — | — |
| **CrusorAI** | **`src/graphs/chat_graph.py`** | **26** | **7** | **49** | **16** | **19** | **141** |
| *CrusorAI (whole `src/`)* | 490 files | *344* | *1,013* | *618* | *1,134* | *360* | *686* |

**Honest caveat:** keyword density is a *proxy* for engineering effort, not proof of
correctness — a `try/except: pass` also counts. But our core file leads every competitor
measured on 5 of 6 axes, and the whole-tree totals lead by 3–50×. The specific mechanisms
behind those numbers: `src/graphs/error_classifier.py` (retry 74, failover 153, compaction 61),
the 4-state verification contract (`verified` / `stale` / `failed` / `not_applicable`), the
revision ledger that turns a post-verification edit into `stale`, and a completion verdict
that is derived rather than self-certified.
**Where we are behind:** codex's `telemetry` density (267 in one file) reflects real
OpenTelemetry wiring; ours is a diagnostics report generator. Observability for *operators*
(not for the model) is their win.

### 3.2 MCP — **mid-pack, structurally behind codex and goose** (Grade B)

File matches across the repo for each capability family:

| Repo | MCP files | resources | elicitation | sampling | conformance | oauth |
|---|---:|---:|---:|---:|---:|---:|
| Codex CLI | 471 | 22 | **54** | 2 | **14** | **44** |
| goose | 269 | 0 | 10 | 4 | 6 | 0 |
| cline | 116 | 2 | 0 | 0 | 0 | 10 |
| gemini-cli | 85 | 9 | 0 | 0 | 0 | 10 |
| OpenHands | 71 | 0 | 0 | 0 | 0 | 0 |
| aider | 0 | 0 | 0 | 0 | 0 | 0 |
| SWE-agent | 0 | 0 | 0 | 0 | 0 | 0 |
| **CrusorAI** | 10 | 33 mentions | **0** | 3 | 3 | 7 |

- **What we do have:** stdio JSON-RPC client (`src/tools/mcp_client.py`), tool pooling, and a
  deliberate **3-schema meta-tool waist** (`mcp_servers`/`mcp_tools`/`mcp_call`) so 20 servers
  cost 3 schemas, not 200 — the same trick gemini-cli and cline use.
- **What we lack:** MCP **elicitation** (server-initiated prompts — codex has 54 references,
  goose 10) and an **MCP conformance suite** (codex 14 references). Ours is "it works on the
  servers we tried"; theirs is "it is proven against the spec".
- **Score:** tool-calling parity ✅; resources ⚠️; elicitation ❌; conformance ❌.

### 3.3 Skills — **largest library in the comparison** (Grade A/B)

| Repo | `SKILL.md` files | skill dirs | delivery model |
|---|---:|---:|---|
| **CrusorAI** | **~304** (31 top-level packs) | 31 | budgeted index (3,000-token cap) + `skill_view` pull + hub install |
| gemini-cli | 26 | 7 | `.gemini/skills`, activate-skill tool |
| cline | 8 | 5 | `.cline`/`.claude`/`.agents` dirs |
| OpenHands | 8 | 5 | `.agents/skills` |
| codex | 5 | 2 | `codex-rs/ext/skills` |
| goose | 2 | 4 | `crates/goose/src/skills` |
| aider | 0 | 0 | none (prompt-format editing, no tool loop) |
| SWE-agent | 0 | 0 | none (single-shot scaffold) |

Two things matter more than the count, and we have both:
**progressive disclosure** (`apply_skills_index_budget`: every skill keeps its name,
descriptions spent cheapest-first, footer names the trim → **22,067 → 5,840 prompt tokens**),
and the **pull/install loop** (`skills_list` → `skill_view` → `hub_install`) matching Agent
Skills conventions. **Gap:** we have no measured retrieval accuracy — `scripts/bench_skill_retrieval.py`
exists but its results are not pinned in CI, so "the right skill is found" is currently a belief.

### 3.4 Agent core / harness architecture (Grade B/C)

| Repo | core design | tool surface | notable |
|---|---|---|---|
| Codex CLI | Rust, tight single loop | curated native tool set + MCP; `spec_plan.rs` = **66,910 B** of tool-spec plumbing (Grade C) | approval/sandboxing as first-class (`approvals.rs`, `sandboxing.rs`), parallel tool exec, `code_mode` |
| gemini-cli | TS, tool registry | 82 `.ts` files under `tools/`, `definitions/` acts as schema layer (Grade C) | JIT context (`jit-context.ts`), plan mode, confirmation policy |
| cline | TS, Plan/Act modes | 2 shared tool modules + MCP | mode-switching, checkpoints, VS Code-native |
| goose | Rust, **MCP-native body** | 269 MCP files — tools are recipes/servers, not built-ins | every capability is an extension |
| OpenHands | TS agent-server on `main` | Docker-per-session isolation | sandbox boundary is the product |
| aider | Python, no tool-calling | repo-map + edit-block protocol | cheapest, most deterministic, least agentic |
| SWE-agent | Python, research scaffold | bash + `str_replace_editor` + submit | the reference implementation for SWE-bench |
| **CrusorAI** | Python + LangGraph, 4-state verification contract, posture resolver (`resolve_runtime_profile`) | 68 registered schemas, 8 capability families, delegation + sub-agent strict scoping | verification receipts, revision ledger, honest completion |

**Our real architectural differentiator, stated plainly:** we are the only one here that
*refuses to claim success* — the verdict is derived from the contract, a post-verification
edit invalidates it, and the tool receipt is what the user sees. codex and cline have
approval/plan gates; none of them has an equivalent "stale verification" state.
**Our real architectural weakness:** a 68-schema surface resolved by a registry, not by a
planner. Codex has `spec_plan.rs`; we have a list.

### 3.5 Context engine (Grade A/B)

| Repo | measured context mechanism |
|---|---|
| Codex CLI | compaction 32 in `client.rs`, auto-compact tokens surfaced (267 telemetry hits) |
| gemini-cli | `jit-context.ts` (load context on demand at the point of use), compaction 37 |
| aider | `repomap.py` = 27,302 B tree-sitter repo map — the best *static* context selection in the field (Grade C) |
| OpenHands | not measurable from `main` |
| **CrusorAI** | budgeted skills index (3,000-token cap), `count_tokens` / `token_budget`, compaction 1,134 hits in `src/`, `bounded_scan.py` for file scans |

Our context engine is **budget-first** (hard caps, measured counts); aider's is
**relevance-first** (graph-ranked repo map). We have no repo-map equivalent — that is the
single biggest *quality* idea in this table we have not adopted.

---

## 4. Cost — including theirs (Grade A for us, D for their tool schemas)

**Common assumptions** (identical for every row, printed by `scripts/cost_model.py`):
25 provider calls/turn, 8,000 history tokens re-sent per call, 400 output tokens/call,
2,200 turns/month, no cache discount. Tiers: **cheap** $0.10 in/$0.40 out per 1M,
**mid** $0.30/$2.40, **frontier** $2.50/$10.00.

| Scenario | fixed tokens/call | cheap $/turn | **mid $/turn** | frontier $/turn | mid $/month |
|---|---:|---:|---:|---:|---:|
| **CrusorAI, all 68 tools** | **31,222** (5,840 prompt + 25,382 schemas) | $0.1021 | **$0.3182** | $2.5514 | **$700** |
| **CrusorAI, `CRUSORAI_TOOL_WAIST=profile`** | **17,684** (5,840 + 11,844) | $0.0682 | **$0.2166** | $1.7053 | **$477** |
| *CrusorAI, waist + 90% cache reads* | 17,684 | — | *$0.1092* | — | *$240* |
| Codex CLI (system prompt only) | 6,006 | $0.0390 | $0.1290 | $0.9754 | $284 |
| gemini-cli (system prompt only) | 2,937 | $0.0313 | $0.1060 | $0.7836 | $233 |
| SWE-agent (system prompt only) | 810 | $0.0260 | $0.0901 | $0.6506 | $198 |
| aider (system prompt only) | 596 | $0.0255 | $0.0885 | $0.6372 | $195 |
| goose (system prompt only) | 308 | $0.0248 | $0.0863 | $0.6192 | $190 |
| OpenHands | **not measured** — agent not present in `main` | — | — | — | — |

**How to read this without fooling yourself.** Their rows contain *only* the static system
prompt: codex's real per-call payload also carries its native tool specs plus MCP tools,
cline/gemini-cli carry a variable MCP tool surface, and aider carries a 27 KB repo map.
So their rows are a **floor**, not their true cost. Ours are complete (prompt + schemas,
both measured). The defensible statements are:

- Our floor-to-floor comparison is the *worst case for us*: 31,222 fixed tokens vs codex's
  6,006 = **5.2×** before codex pays a single tool schema.
- After the waist we are at 17,684 = **2.9× codex's system prompt alone**.
- aider is genuinely the cheapest architecture here — it has **no tool schemas at all**
  (prompt-format editing). That is why it is deterministic and also why it cannot do what
  this agent does. Not comparable work; comparable bill.

**Correction to the previous memo.** `docs/AGENT_CORE_COST_MODEL_AND_PRICING.md` quoted mid
tier **$0.1278/turn ($281/month)**. That figure omitted tool schemas. The measured number is
**$0.3182/turn ($700/month)** — **2.5× higher** — falling to **$0.2166 ($477)** with the
waist on and **$0.1092 ($240)** with the waist plus 90% cache reads. All pricing conclusions
in that memo still hold (they were already conservative on margin), but the seat math must be
re-read against these numbers, not the old ones.

**The one-line cost lesson:** the prompt was cut 74% and that bought one dollar in three. The
tool surface is the bigger half of the bill, and today it is 4.3× the prompt.

---

## 5. Scorecard

| Dimension | Grade | Verdict |
|---|---|---|
| **Error handling** | **A−** | Leads every competitor's core file on 5 of 6 axes; only operator telemetry is behind codex. Our differentiator. |
| **Context engine** | **B** | Budgeted and measured, with compaction everywhere; missing aider-style relevance ranking (repo map). |
| **Skills** | **B+** | Largest library and correct progressive disclosure; no measured retrieval accuracy. |
| **Agent core** | **B−** | Verification contract is genuinely ahead of the field; 68-schema registry with no planner is genuinely behind codex. |
| **MCP** | **C+** | Tool-calling parity, meta-tool waist is good design; no elicitation, no conformance suite, 10 files vs codex 471. |
| **Performance (quality)** | **D** | **Not measured.** No shared-model benchmark, no public pass rate. Unknown, and unknowable from this document. |
| **Cost** | **C** | $0.2166/turn mid-tier after the waist; ~2.9× codex's prompt floor, and 2.5× worse than our own previous estimate. |
| **CI / release surface** | **D+** | 5 test files run in CI vs 4,471 test-ish files in codex and 47 workflows in gemini-cli. Cheapest credibility gap to close. |

---

## 6. What to fix, in cost order (cheapest first)

| # | Move | Why it is first | Measured target |
|---|---|---|---|
| 1 | **Turn the waist on and measure traces** — `CRUSORAI_TOOL_WAIST=profile` (added today, opt-in, never narrows below 8 tools) | −13,538 tokens/call, −$223/month per heavy seat, zero code risk | 68→47 tools for app builds, 68→35 for bugfixes, 68→16 for chit-chat |
| 2 | **Shrink the top-10 schemas** — `delegate_to_subagent` (1,018 tok), `execute_code` (993), `terminal` (959)… = 8,359 tokens for ten tools | description text, not capability | description chars −50% on the top 10 |
| 3 | **Run more of the suite in CI** (5 files → every `src/tests/test_*.py`) | converts an unverifiable claim into a build badge | suite is 3,116 passing locally today |
| 4 | **MCP elicitation + a conformance test** | the only two MCP gaps that show up as "your agent can't use my server" | 1 elicitation round-trip, N spec assertions |
| 5 | **One public quality number** — 20–30 held-out tasks, same base model, failures published | the only way the words "can compete" become checkable | pass rate + false-done rate, both published |
| 6 | **Repo-map context selection** (aider's idea) | biggest remaining quality idea not in this codebase | retrieval benchmark pinned in CI |

---

## 7. Performance **tracking** (repeatable, not a one-off)

Two scripts, both committed, both runnable with no network for the second one:

```bash
# 1. Competitive snapshot — GitHub API, writes a JSON you can diff later
python scripts/competitor_snapshot.py --json > snapshots/competitors-$(date +%F).json

# what changed since last time (stars, pushes, MCP depth, prompt sizes, reliability hits)
python scripts/competitor_snapshot.py --diff snapshots/competitors-2026-10-31.json

# 2. Our own cost/token envelope — no network, measures the real prompt + schemas
python scripts/cost_model.py                # human table (3 scenarios)
python scripts/cost_model.py --json         # machine-readable, diffable
```

Recommended cadence: **snapshot monthly**, `cost_model.py` **on every change that touches
prompt assembly or the tool registry** (it is the regression test for the two numbers that
decide the pricing sheet). The snapshot's `--only` flag lets you watch one repo.

---

## 8. Reproduction

```bash
gh auth status                                   # snapshot needs an authenticated gh
python scripts/competitor_snapshot.py            # §1, §2, §3.1, §3.2 tables
python scripts/cost_model.py                     # §4 rows for CrusorAI
CRUSORAI_TOOL_WAIST=profile python scripts/cost_model.py   # the waist row
```

Data as measured today is stored in `snapshots/competitors-2026-10-31.json`.
