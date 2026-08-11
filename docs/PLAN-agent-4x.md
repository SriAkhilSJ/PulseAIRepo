# 🎯 PLAN — Agent 4x: Test 2, solved structurally

**Direction (founder):** read hermes for the best agent, use the VS Code fork's MCPs/extensions/APIs, and make Test 2 pass in a fundamentally better way — **4x improvement**.
**Guiding thesis (founder, adopted):** the context engine decides capabilities — never "blame the model." Every failure is missing context (information, policy, or tool) and is ours to own.

---

## 1. What "4x" means (measured, not vibes)

Baseline = Test 2, recorded: **~50 tool/LLM calls, ~15 human interventions, ~5.7k tokens of tool definitions per call**, shipped 25 type errors (incl. `TS1005: '=>' expected`), required full rework.

| Metric | Test 2 baseline | 4x target | Status |
|---|---|---|---|
| Tool/LLM calls per task | ~50 | **≤12** | mechanism: batching + diagnostics-as-context |
| Human interventions | ~15 | **≤4** | mechanism: native diff approve + self-unblocking |
| Tool-def tokens per call | ~5.7k | **≤1.4k** | **2.6x done** (2.2k today; trim continues) |
| Broken code shipped | 25 errors | **0** | done (esbuild receipt + verify gate); LSP delta makes it structural |
| Retest first-pass success | failed | **pass** | benchmark harness proves it |

Composite calls×helps: 750 → 48 ≈ **15x**; the honest floor for "4x" is calls, tokens, and helps each ≥4x — the mechanisms below target that.

---

## 2. Test 2 failure modes → mechanism → source

| # | Test-2 failure | Mechanism that kills it | Source | Status |
|---|---|---|---|---|
| 1 | 50 calls (one-op-at-a-time) | PTC batching taught in persona + **iteration budget** (hard cap, PTC refunded) | hermes `iteration_budget.py`, `code_execution_tool.py` | persona done; budget = M1 |
| 2 | 15 human helps (asked instead of resolved) | **Native diff approve/refuse** (one click, no Q&A thread) + tests-as-oracle policy | fork contrib `electron-browser/` + engine policy | M4 fork / M1 policy |
| 3 | Shipped broken TSX | Write-path **syntax receipt** (esbuild) → landed; **delta-baseline LSP** (block write on NEW diagnostics) → structural | hermes `agent/lsp/manager.py` (Claude Code `beforeFileEdited` pattern) | receipt shipped; LSP = M2 |
| 4 | Declared Finished with known errors | **Verify gate hardened**: typecheck that runs-but-fails blocks Finish | engine | shipped |
| 5 | Faked verification (told to use a browser tool that wasn't bound) | **Real browser MCP** (`browser_mcp.py`, lazy stdio client) | engine (generalizes to any MCP server) | shipped; registry = M3 |
| 6 | Path double-nesting | Workspace-root path contract in `resolve_workspace_path` + persona rule | engine | on disk (uncommitted) |
| 7 | Rework loops (fix → break → rediscover) | **Diagnostics-as-context**: agent SEES errors without calling tools | fork extension host (tsserver) → M4 | planned |
| 8 | No measurement ("I feel it's weak") | **Benchmark harness** — fixed tasks, counted metrics per commit | new | M0 |

Every failure maps to context we failed to feed — exactly the thesis. Nothing on this table blames the model.

---

## 3. The three layers

### A. Engine-only, now (Python, no fork needed) — the 4x core
1. **M0 — Benchmark harness (first, non-negotiable).** 5 fixed tasks incl. a Test-2-class chat app; pass criteria + counters (calls, tokens, helps, first-pass correctness). Every milestone below is a number, not a claim.
2. **M1 — Loop policy.** Port hermes' `IterationBudget` (parent cap, per-subagent cap, PTC refund). Forced batching gate (script when ≥2 ops). Self-unblocking policy: resolve ambiguity via files/tests before asking.
3. **M2 — Delta-baseline LSP.** Port hermes `agent/lsp/manager.py`: snapshot diagnostics before write → block on NEW diagnostics after → fallback to in-process esbuild receipt. Lazy spawn, broken-set never-retry, off-by-default. **This is "is LSP strong" = yes, wired into the write path.**

### B. Context efficiency (still engine-only)
4. **M3 — MCP registry.** Generalize `browser_mcp.py` → config-driven stdio MCP loader (`.mcp.json`), same lazy-spawn/crash-net/degrade contract. Any MCP server (git, docker, linear…) becomes a tool with zero engine changes.
5. **Tool-result classification** (hermes): read-only tool results are discard-safe (never retried, summarizable); mutations verified structurally, not by model belief.
6. **Prompt-cache discipline** (hermes D19 audit — already in engine): keep the prefix byte-stable; measure break position per turn.

### C. Fork integration (P2 — the multiplier)
7. **M4 — `contrib/pulse/` sidecar** (locked roadmap, Phase 0.4 bridge exists): the engine spawns as the sidecar process; the fork feeds it:
   - **Diagnostics-as-context** from extension-host language features (tsserver) → agent sees live errors in its context, **zero tool calls** spent discovering broken code (the single biggest call-killer).
   - **Terminal streams as context** (Claude Code pattern) → output flows in, no polling loops.
   - **Native diff approve/refuse** → human helps collapse from Q&A threads to one click (15 → ~0-1).
   - **File-watch → index freshness** → repo map/vector memory never go stale, no re-scan calls.
   - **Checkpoint timeline** → "go back 3 turns" is one click, not rework.
   - **Native MCP host** — VS Code 1.133 chat contrib already speaks `mcpServers`; user-configured servers become agent tools for free (compounds with M3).

---

## 4. Sequencing & gates

| # | Milestone | Done when | Gate |
|---|---|---|---|
| M0 | Harness + Test-2 baseline re-recorded | 5 tasks, counters, baseline JSON | baseline committed |
| M1 | Iteration budget + batching/self-unblocking policy | Test-2 retest ≤20 calls, ≤6 helps | harness numbers |
| M2 | Delta-baseline LSP in write path | 0 broken files land in retests | harness + suite |
| M3 | MCP registry + tool-result classification | any `.mcp.json` server binds lazily | new tests |
| M4 | Fork: diagnostics/terminal/diff-approve feeds | Test-2-class task ≤12 calls, ≤2 helps | harness + fork build |

**Rule:** full engine suite stays green at every step (440 passed, 1 skipped today). No fork work until M0–M3 are proven by the harness — the fork multiplies a measured engine; it can't fix an unmeasured one.

## 5. Risks (measured)

- **Regression risk** — every port adds tests first; suite is the gate.
- **Fork latency** — M4 needs the fork build (tens of minutes first time); M0–M3 deliver 4x without it.
- **LSP phantom diagnostics** — avoided by hermes' delta-baseline + broken-set + off-by-default fallback (the esbuild receipt stays as the floor).
- **Scope discipline** — the locked P2 roadmap stands; this plan is the engine-era agent work that feeds it.
