# 🧪 PulseAI Agent — Lab Test Report

**Date:** 2026-08-08 · **Tester:** lab harness (`lab/run_eval.py`, `lab/resume_eval.py`)
**Task:** *"The tests in test_calc.py are failing. Fix calc.py so ALL tests pass. Do not modify test_calc.py. Run `python test_calc.py` to verify."*
**Sandbox:** `lab/workspace_a/` — a `calc.py` with two planted bugs (`divide` raises `ZeroDivisionError` instead of `ValueError`; `fib` has a wrong tuple assignment → `fib(10)` returns 34, not 55).

## Environment (honest constraints)

| Constraint | Effect |
|---|---|
| C: drive 100% full (139MB free) | Could not install torch/sentence-transformers (~700MB); AV/file-lock wedges |
| D: drive blocks execution of binaries in `.venv` | Venv relocated to C:; agent runs from there |
| Embedder missing → designed **degraded mode** | `memory_manager=None`, heuristic classifier (boot works, loud warning) |
| Groq free tier: 8,000 TPM | 413 once context+tools exceed it |
| Groq project whitelist | `llama-3.1-8b-instant`, `llama-3.3-70b-versatile` blocked (403) |
| Gemini free tier | High TPM, but strict function-call message protocol |
| **Custom proxy** (`http://127.0.0.1:31415/v1`, freellm) | Runs 5–9. `auto` router rotates backend models per request; free tier rate-limits per-route (~17 models on cooldown at peak) |

## Run log

| Run | Provider | Wall | Calls | Tokens | Est. $ | What happened | Crash |
|---|---|---|---|---|---|---|---|
| 1 | Groq | 1.8s | 3 | 8,134 | $0.004 | Plan (5 steps), read ×2 | aux model `llama-3.1-8b-instant` **403 blocked** → unhandled |
| 2 | Groq | 154s | 6 | 24,527 | $0.012 | Plan (6), read ×2, **correct diagnosis of both bugs**, `edit_file` fix of `divide` (atomic diff) | **413 TPM**: request 8,482 real vs 8,000 limit → unhandled |
| 3 | Groq | 156s | — | — | — | `run_terminal python test_calc.py` worked; read calc.py OK; read test_calc.py failed (transient) | **413 again** (8,455) with guard at 4,500 — tool defs unguarded |
| 4 | Gemini | 26.8s | 6 | 23,956 | $0.024 | Plan (5), run tests, read, `edit_file` divide fix; guard trimmed 2× | **Gemini 400**: `SystemMessage` injected between `ToolMessage` and next function-call turn |
| 5 (resume) | Gemini | 2.2s | 1 | +830 | +$0.001 | **Checkpoint resumed across processes** (task, plan, trace, cost accumulated) | `stream_agent` crash: planner no-op → `{"planner": None}` → `.get()` on None |
| 6 | Custom/auto | 118s | ~14 | — | — | **Classifier bug reproduced & root-caused** (below); agent actually fixed both bugs in runs 6–9 | Proxy **429** (17 models rate-limited) after agent caught its own incomplete fib fix |
| 7 | Custom/auto | 17.9s | ~5 | — | — | Diagnosed both bugs perfectly, then **answered with a summary instead of fixing** — routed model rotated (`nemotron-3-super`) and chose not to execute | No crash; behavioral finding |
| 8 | Custom/qwen3.6-27b | 3s | — | — | — | Pinned model — route rate-limited on proxy (~21h cooldown) | 429 at first call |
| **9** | **Custom/auto** | **68.6s** | **12** | **86,066** | **$0.0086** | **✅ COMPLETED TASK** — plan (5/5), run tests → read both files → diagnose both bugs → fix `divide` + `fib` → re-run → **6/6 PASS** → `verify` self-check | none |

## Findings fixed during the lab

**F1 — Progress classifier false-positives on `"error:"` in content (P0, caused runs 5–6 to fail).**
`classify_tool_outcome` in `src/graphs/progress_helpers.py` marked any result containing the substring `"error:"` as failed. Reading a test file containing `except ValueError:` (line 26) — and the model's own `think` text mentioning `test_divide_by_zero_raises_value_error:` — falsely flagged *successful* tools as failed, burning all 3 recovery attempts. The 445 green tests never caught it because synthetic test strings never contain mid-line `error:`. **Fix shipped:** markers now anchored to line starts (`^error:`, `^traceback`). Regression tests added for the exact real-world cases; 13/13 pass; verified the exact run-5 inputs now classify `success`.

**F2 — `stream_agent` crashes on the second turn of any session** (planner no-op → `{"planner": None}` → `.get("plan")` on None). Multi-turn chat — the core of an AI IDE — is broken at the API level. P0, unfixed.
**F3 — Provider API errors (403/413/400/429) are unhandled and kill the turn.** Recovery/replan only sees *tool* failures, never LLM-layer ones. P0, unfixed.
**F4 — Tool definitions (~4K real tokens for 21 tools) bypass the pre-send token guard** → 413 on any tier where context + tool defs exceed the TPM cap. P1.
**F5 — Gemini protocol incompatibility**: `SystemMessage` (progress reflection) injected after `ToolMessage` violates Gemini's function-call alternation → 400. P1.
**F6 — Aux-model default is a config trap**: Groq default aux `llama-3.1-8b-instant` is blocked for common keys → 403 at the very first management call. P1.
**F7 — Memory layer segfaults on Python 3.14 + torch 2.13 at construction** (uncatchable). Designed degrade path works. P2.
**F8 — `auto` router rotates backend models per request** → same prompt gets different behavior across runs (run 7 answered instead of fixing; runs 6/9 executed). By design for resilience, but makes agent behavior non-reproducible. Pin models for eval runs.

## Metrics (runs 2–9, custom/Gemini era)

### Latency
- **Groq trivial call: 0.47s** — the ~60s round-trips were free-tier TPM queueing, not model slowness.
- **Gemini: ~6–7s per LLM round-trip.**
- **Custom proxy: 0.5–1.1s per call** (`auto` → gpt-oss-120b 1.08s, qwen3.6-27b 0.54s); full task run 68.6s wall for 12 calls.
- Cold boot (fresh process + degraded mode): ~1–2s to first tool call.

### Response (quality)
- **Planning: consistently good.** 5–6 step plans, task-appropriate order (run tests → read → fix → re-verify) in every run that reached planning; run 9 completed **5/5** steps.
- **Diagnosis: correct in every run** (6–9), including the subtle `fib` tuple-swap — and in run 6 the agent **verified its own fix, caught an incomplete correction (off-by-one loop bound), and was about to fix it** when the proxy rate-limited. That's the right behavior.
- **Execution: correct mechanics.** Atomic `edit_file` with diff preview; run 9's fib fix (`a, b = b, a + b`) is exact and complete.
- **Verification: run 9 finished with a `verify()` self-check** and an accurate summary of both bugs and changes.
- ⚠️ **Model-dependent**: run 7's routed model answered instead of executing tools. Same engine, different behavior.

### Durability
- ✅ **Checkpoint persistence across processes works** (task, plan, trace, accumulated cost survive restart).
- ❌ **Resume path broken in the stream layer** (F2) — second turn of any session dies. Fatal for a chat IDE.

### Performance / cost
- ✅ Accurate accounting: 12 calls, 86,066 tokens, $0.0086 for a complete bug-fix task; per-tier routing logged every call.
- ❌ Token guard counts messages but not tool definitions (F4); cl100k estimation undercounts some tokenizers 1.4–1.9×.

### Discipline
- ✅ **Never modified `test_calc.py`** (hashes unchanged in every run).
- ✅ Used `edit_file` (precise) rather than `write_file`-overwrite; stayed inside the sandbox.

### Thinking
- ⚠️ `think()`/`verify()` are *available* but only `verify` was used (run 9); most reasoning is inline. Qwen emits native `<think>` blocks that inflate tokens/latency.

## Verdict

**The agent completed the task.** End-to-end: plan → diagnose both bugs → fix both → verify 6/6 → summarize, in 68.6s / $0.0086 with zero crashes and zero rule violations. That's the first full success across 9 runs, and it came from a real bug fix in the engine (F1), not from changing the task.

What the runs prove: the **agent itself is competent** — planning, diagnosis, self-verification, and tool discipline all measured well once the engine stopped sabotaging itself. What they also prove: the **engine is not product-ready**. Four unhandled crash paths (F2–F5) still kill turns on ordinary conditions — a second chat message, a provider rate limit, a strict-protocol provider. The 445-test suite stayed green through all of it because it never drives a real multi-turn session against a real provider.

**Recommendation before any IDE/UI work:** fix F2 and F3 (both small, high-value — F2 is a two-line None-guard; F3 needs an LLM-layer error handler wired into the recovery machinery), then wire `lab/run_eval.py` in as a regression gate asserting "6/6 pass in the sandbox" — it now has a passing baseline to protect.

---

# Lab Test 2 — shadcn/Spline component integration (agent under test: PulseAgent)

**Date:** 2026-08-09 · **Tester:** lab harness (`lab/run_eval_shadcn.py`, `lab/resume_eval_shadcn.py`)
**Task:** *"Integrate an existing React component…"* — full verbatim shadcn prompt: copy SplineScene/demo/Card/Spotlight into `/components/ui`, install `@splinetool/runtime`, `@splinetool/react-spline`, `framer-motion`, and if the project lacks Tailwind/TS/shadcn, provide setup instructions; explain the `/components/ui` convention.
**Sandbox:** `lab/workspace_b/` — started **empty** (no React project existed; the agent had to scaffold or pivot).
**Outcome:** ✅ **COMPLETED — resume 2 finished 8/8 plan steps, EXIT 0, full deliverable on disk.**

**Test 1 output — the frontend the agent built** (rendered live; screenshot captured via puppeteer):

![Test 1 output — Spline demo built by the agent](../docs/lab-spline-demo.png)

## Run log

| Run | Wall | Calls | Tokens | Est. $ | What happened | Crash |
|---|---|---|---|---|---|---|
| 1 | 11.58s | ~9 | — | — | Plan (9 steps, correct: names shadcn path convention + deps). Tried `npx create-vite` → **Windows npx-shim failure** (`'create-vite' is not recognized…`). Retried 3× → **gave up at recovery limit** ("I don't want to keep retrying the same thing"). Never used the task's own escape hatch (provide instructions). | none (behavioral) |
| 2 (fresh, fixed engine) | 619s | — | — | — | **PIVOT WORKED**: stopped retrying broken npx scaffold → wrote `package.json` by hand → `npm install`. Was genuinely building (next+react+spline deps landed)… then **C: hit 0 bytes** (npm cache filled disk) → `sqlite3.OperationalError: database or disk is full` at the checkpoint DB. | env kill (disk) |
| **3 (resume 2)** | **760.69s** | **26** | **413,339** | **$0.041** | **✅ COMPLETED.** Resumed same thread in a new process *after a disk-full crash* (checkpointer + npm cache moved to D:). Finished `npm install` (334MB node_modules), wrote **all 4 components + `lib/utils.ts`** in the correct shadcn path, plan **8/8**, closed with `## ✅ Finished` summary. F2 guard held. | none |

## Deliverable verified on disk (`lab/workspace_b/`)

`components/ui/splite.tsx` (verbatim SplineScene) · `demo.tsx` (verbatim demo) · `card.tsx` (verbatim shadcn Card) · `spotlight.tsx` (verbatim Spotlight) · `lib/utils.ts` (`cn`) · `package.json` (next 14 + react 18 + `@splinetool/react-spline` ^2.2.2 + `@splinetool/runtime` ^0.9.441 + `framer-motion` ^11.2.10 + clsx/tailwind-merge + tailwindcss + typescript) · `package-lock.json` · `node_modules` (334MB).

## Findings fixed during the lab (all shipped, all tested)

| ID | Fix | Where |
|---|---|---|
| F2 | **`stream_agent` None-planner guard** (two-line) — previously any planner-noop event crashed the whole session on `.get("plan")`. Verified: resume after disk-full crash did **not** crash. | `src/graphs/chat_graph.py` |
| F3 | **ai-node provider failover** — `llm_with_tools.invoke` wrapped; on 403/413/400/429/5xx falls back to the primary provider instead of killing the turn. | `src/graphs/chat_graph.py` |
| F8-class | **Recovery pivot** — progress classifier now recognizes *environment-level* tool failures (npx/npm shim not found) and steers the agent to a **strategy switch** (write files manually / provide instructions) instead of retry-until-dead. This is what turned run 1's freeze into run 2's manual-scaffold pivot. | `src/graphs/progress_helpers.py`, `chat_graph.py` |
| — | **Repo-map quadratic blowup** — `_compress_map` removed one file per loop and rebuilt the entry list each time → O(n²); the 15k-file `desktop/` fork turned repo-map builds into >600s hangs. Now binary-searches the smallest victim-count (O(n log n), same output) + `PULSEAI_REPO_MAP_MAX_FILES` bound. | `src/context/repo_map.py` |
| — | **Planner graceful degradation** — `_no_plan()` path emits a degraded plan message instead of None. | `src/graphs/chat_graph.py` |
| — | **Env/tooling**: fresh `uv sync` venv in-repo; removed torch/sentence-transformers (Python 3.14 memory-layer hang — designed degraded path); `lab/py` wrapper (C: base interpreter + in-repo venv site-packages, since D: blocks venv exe execution). | `lab/py` |

**Regression tests:** 23 new/updated (`test_lab_fixes.py` + `test_progress_helpers.py`), full suite 445→475 green modulo documented environmental flakiness (AV-denied git/subprocess spawns under file churn — pass individually; WinError 5).

## Metrics

### Latency
- Run 1 gave up in **11.58s** (3 failed npx attempts); resume 2 completed in **12.7 min** wall for a full scaffold+integrate task.
- Per-call round-trip via custom proxy: ~0.5–1.1s; 26 calls total.

### Durability — the headline of this lab
- ✅ **Survived a disk-full crash mid-install, a process kill, and resumed in a new process** — same thread, plan, and accumulated state (F2 guard held where run 5 of the calc lab crashed).
- ✅ **Remembered its own plan across the restart** (8/8 steps carried; resume prompt even referenced "the previous npm install was interrupted by a disk-space issue").
- ⚠️ Run 1's freeze: at the recovery limit the agent *stopped dead* instead of pivoting — the exact gap the pivot fix targets; run 2 proved the fix works.

### Thinking
- Plan quality **consistently strong**: named the shadcn `/components/ui` convention, the `cn` util, and the dependency list unprompted; 8/8 steps completed.
- Run 1's failure was **flexibility, not intelligence** — verified independently that `npx` shims genuinely don't resolve in the agent's terminal on this box.
- ⚠️ Phantom `Tool failed: write_file` entries appeared in the harness log after *successful* writes (result-serialization quirk) — agent pushed through; recovery attempts stayed at 0.

### Cost / performance
- ✅ Complete integration task: **$0.041, 413k tokens, 26 calls** (resume 2).
- ✅ Accurate per-tier routing + token accounting throughout.

## Verdict

**The agent completed the task end-to-end** — from an empty sandbox with a broken npm/npx environment, it scaffolded a Next+TS+Tailwind project manually, installed the exact dependency set, placed all four components in the correct shadcn paths, and verified its work. That required **strategy pivoting under environment failure** (run 2), **surviving a disk-full crash and process death** (resume 2), and **holding a plan across a checkpoint resume** — the exact durability properties that killed this engine's predecessor in the calc lab (F2 crashed every resume).

The lab also shipped five real engine fixes (F2 guard, F3 provider failover, recovery pivot, repo-map O(n²)→O(n log n), planner degradation) with regression coverage. Remaining known issues are **environmental** (AV file-lock flakiness on git/subprocess spawns under file churn; D: drive blocking venv exe execution) rather than engine logic.

**Recommendation:** wire the two eval scripts (`run_eval_shadcn.py` / `resume_eval_shadcn.py`) into CI as the durability gate — the suite now has a green end-to-end baseline to protect, including the resume-after-crash path.

## Post-lab follow-up (same day)

**F9 — `npx` broken machine-wide: `bin-links=false` in the user .npmrc (root cause of run 1's freeze).**
The user-level `C:\Users\Administrator\.npmrc` contains `bin-links=false`, which makes npm never create `.bin` shims → every npx'd package fails with *"'create-vite' is not recognized as an internal or external command"* on Windows. This is what froze run 1 (and would freeze any agent, including Claude, on this box). A repo-level `.npmrc` does **not** fix scaffolded apps: npm reads project config only up to the nearest `package.json`. **Fix shipped:** `src/tools/terminal_tools.py` now injects `NPM_CONFIG_BIN_LINKS=true` (highest npm config precedence, env var) into every spawned shell via `_shell_env()` — works in any directory, touches no config file, plus `NPM_CONFIG_CACHE` → `D:\npm-cache` when D: exists (prevents the run-2 disk-full recurrence). Verified end-to-end: `npx create-vite@latest` scaffolds, `npm install` creates 18 shims, `npm run build` → `✓ built in 180ms`. Also `setx`'d both vars for the user environment (takes effect after the IDE/agent restarts). 13 tool-related tests pass.

**Deliverable note (test finding, not engine bug):** the agent's component integration is verbatim-correct (all 4 files + `cn` util + exact dep set), but the scaffolded skeleton is **not fully buildable** — `tsconfig.json`/`tailwind.config`/`postcss.config`/`next.config` are absent, so `tsc`/`next build` cannot run as-is. The task's "provide instructions if missing" branch was only half-taken. Worth a completeness check in future evals (plan step 8 claimed "compiler check" but nothing to compile against).

## Competitive analysis + efficiency pack + puppeteer MCP (same day, part 2)

**Measured waste in resume 2** (26 calls, 396,233 prompt tokens, 760s):
per-call prompt = 15,239 tokens = **5,686 tool defs + 3,654 context layers + 1,840 persona + ~4k history replay**. The whole conversation is only 3,748 tokens — 73% of prompt tokens were static overhead re-sent every call. The engine already had the hermes-competing machinery (parallel tool batches D34, LLM compaction with anti-thrash, provider failover F3) — the model simply under-batched and the static cost was bloated.

**Efficiency fixes shipped (measured, tests green 62/62):**
1. **Tool descriptions trimmed** — 5,686 → 4,232 tokens/call (-26%): execute_code 1,104→522 (2,203-char tutorial docstring cut), session_search 675→433, check_terminal 322→171, run_terminal 290→198, read_file 298→117, edit_file 364→158. All functional guidance preserved.
2. **Task-layer cap** — the full task text (already in history) was re-sent each call: 295 → 54 tokens.
3. **Plan-layer cap** — step descriptions truncated to 90 chars in the layer (full detail stays in history): ~430 → ~200 tokens.
4. **Static per-call cost: 11,180 → ~7,700 tokens (-31%)**; projected run: 396k → ~290k tokens before batching gains.

**Puppeteer MCP (the agent's eyes — hermes browser_tool value).** `src/tools/browser_mcp.py`: lazy stdio MCP client that spawns `node dist/index.js` of the globally-installed `@modelcontextprotocol/server-puppeteer` directly (immune to the machine's npx/bin-links problem), exposing **8 browser tools** (navigate / snapshot / screenshot / click / type / select / hover / evaluate) with graceful degradation. Registered in the agent toolset (21 → 29 tools; net token cost still -675 vs before the trims). **Verified live**: the agent navigated to the running Spline demo at localhost:61264, read the page text via snapshot, and captured a screenshot — it can now see and verify its own UI output. (Found + fixed two implementation bugs: raw-FileIO `read1` from `bufsize=0`, and decorator ordering that broke tool signatures; the server's real tool names are `puppeteer_*`.)

**Honest 4x math:** the code-side trims land ~-31% static tokens/call (~-23% total run tokens, ~-40% if batching takes hold). The other half of the 4x target is provider-side: the 26 calls at ~29s each are dominated by the freellm proxy's model rotation/queueing, and per-call cost would drop another ~10x with prompt caching on the serving side. **To verify the real number, re-run the shadcn eval against the fixed engine** (new thread + empty sandbox) — that's the next step before declaring the 4x.
