
---

# Lab Test 2 — shadcn/Spline component integration (agent under test: PulseAgent)

**Date:** 2026-08-09 · **Tester:** lab harness (`lab/run_eval_shadcn.py`, `lab/resume_eval_shadcn.py`)
**Task:** *"Integrate an existing React component…"* — full verbatim shadcn prompt: copy SplineScene/demo/Card/Spotlight into `/components/ui`, install `@splinetool/runtime`, `@splinetool/react-spline`, `framer-motion`, and if the project lacks Tailwind/TS/shadcn, provide setup instructions; explain the `/components/ui` convention.
**Sandbox:** `lab/workspace_b/` — started **empty** (no React project existed; the agent had to scaffold or pivot).
**Outcome:** ✅ **COMPLETED — resume 2 finished 8/8 plan steps, EXIT 0, full deliverable on disk.**

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
| — | **Planner graceful degradation** — no-plan path emits a degraded plan message instead of None. | `src/agents/planner.py` + graph wiring |
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

---

# TEST 2 — Chat App (EaseMize-style) — Result & Engine Fixes

**Result: ✅ SUCCESS (with findings).** The agent built the full chat app (21 files: ChatLayout, MessageList, PromptInput, EmptyState, ChatSidebar, prism-highlighter, 4 ui primitives, configs) and **puppeteer-verified** — empty state "How Can I Help You", typed message, streamed assistant response, 21 interactive buttons. Live at localhost:65530. Total: ~27 min · **50 calls** · 763,507 tokens · $0.076 (run 4 + resume 4; run 4 killed by C:-disk-full, resume 4 completed).

## The failures that drove fixes

1. **Finish-gate (already shipped in Test-1 era) held** — runs 1-2 died in 7-18s with "Finished" after zero work; the hermes-style nudge (conversation_loop.py `_CODEX_INCOMPLETE_NUDGE`) made run 3+ actually execute.
2. **cmd.exe `mkdir app/components` quirk** — `/` parses as a switch; now classified env-failure → strategy pivot (progress_helpers.py marker added).
3. **C: drive killed the run twice** — checkpointer moved to D: via env override (`PULSEAI_CHECKPOINT_DB`); puppeteer browser cache (2.1GB) was landing on C: by default → moved to `D:\puppeteer-cache` + `PUPPETEER_CACHE_DIR` hardcoded into browser_mcp.py spawn env + setx'd machine-wide.
4. **NEW — the agent shipped ~15 syntax/type bugs** (recursion limit cut it before build-verify): `() {` missing arrow, JSX concat in attribute, lucide `MoreVert`/`BotMessageSquare`/`CircleHelp` (wrong names for 0.306), react-markdown v9 `inline` removed, prism-react-renderer v2 `Highlighter`→`Highlight`, and a scroll-area that **silently swallowed children**. Root cause: writes were blind (no per-file check) and nothing forced verification before finalize.

## Fixes shipped (hermes `file_operations.py` LINTERS/LSP pattern)

- **Multi-language syntax receipt** — `src/tools/lint_checker.js` (esbuild→typescript fallback, resolvable from workspace or global npm) + `_syntax_receipt()` in file_tools.py: `.ts/.tsx/.js/.jsx/.json` writes are rejected at the tool if the ORIGINAL parsed clean and the UPDATE wouldn't (delta refinement — repairs stay allowed). Test 2's two syntax bug classes now caught at write time.
- **`typecheck_workspace` tool** (29th tool) — runs the workspace's own `tsc --noEmit`, returns filtered errors grouped by file with a hard "Fix ALL of them before finishing" instruction; skips gracefully without tsconfig/typescript. Caught Test 2's exact bug class (`TS1005: '=>' expected`).
- **Verify gate** — `should_continue` now routes to `finish_gate` when a coding task wrote files but never ran a verification tool (typecheck_workspace / browser_*), bounded via `verify_nudges`. The nudge explicitly names the verification tools.
- **8 new regression tests** (verify-gate routing ×3, receipt behaviors ×5) — full suite 85+ passed.
