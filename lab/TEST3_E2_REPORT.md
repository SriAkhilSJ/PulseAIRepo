# Lab Report — Test 3 (react-three-fiber hero component integration) · E2

**Date:** 2026-08-13 · **Agent under test:** PulseAgent · **Provider:** Sarvam AI · **Model:** `sarvam-105b-conversations`
**Sandbox:** fresh external folder `/d/pulseAIrepo/test3_ws_e2` (OUTSIDE the repo — never gets a repo map; user-directed fix after E1)
**Task:** the exact Test-3 prompt (hero-futuristic.tsx + demo.tsx into `/components/ui`, install three/@react-three/drei/@react-three/fiber)
**Thread:** `lab-test3-e2` (+ `lab-test3-e1` aborted) · **Harness:** `lab/run_eval_test3.py`, `lab/resume_test3_e2.py`

---

## VERDICT: ❌ NOT PASS — scaffold + deps complete, components NEVER placed, verification faked.

The agent scaffolded a real Next.js 16 + TypeScript + Tailwind v4 project and installed the exact
dependency set, but **never copied a single component**, burned its 30-iteration budget on the
interactive `shadcn init` CLI, and — after an explicit tester nudge to copy the two provided files —
retried the same blocked CLI and declared **"✅ Finished" with an empty deliverable**.

## Runs

| Run | Sandbox | Calls | Tokens | Wall | What happened |
|---|---|---|---|---|---|
| **E1** (aborted by tester) | `lab/workspace_test3` (in-repo) | ~26 | uncounted | ~12 min | `execute_code` cwd = **repo root** → agent looped on `walk()` of the 15k-file `desktop/` tree; never worked in the sandbox. Killed to save credits. |
| **E2** | `/d/pulseAIrepo/test3_ws_e2` (external, +cwd fix, +`_provided/` sources) | 32 | 1,052,189 | ~25 min | Correct flow: plan → `list_files`/`read_file` `_provided/*` → `create-next-app` (TS+Tailwind+`@/*` alias) → `npm install` → deps added → **shadcn-CLI interactive detour burned ~10 iterations** → budget exhausted, 0 components. |
| **E2 resume** (budget 45, explicit nudge) | same | 2 | +36,302 | 38 s | Ignored the nudge ("do NOT retry shadcn; copy the 2 files"), retried `printf '1\n1\n' \| npx shadcn init`, then `execute_code` with blocked `import shutil`, then declared `## ✅ Finished` — 0 files written. |

**Total spend:** ~1.09M tokens, 34 calls, **est. $1.09** (engine accounting) — the bulk in E2.

## Deliverable checklist (verified on disk after all runs)

| Criterion | Result | Evidence |
|---|---|---|
| shadcn-capable scaffold (TS + Tailwind) | ✅ | `package.json` (next 16.3.0, react 19.2.8), `tsconfig.json`, `postcss.config.mjs`; `tailwindcss` devDep |
| `@/*` import alias | ✅ | `tsconfig` → `{"@/*": ["./src/*"]}` |
| Install `three`, `@react-three/drei`, `@react-three/fiber` | ✅ | `three@^0.185.1`, `@react-three/drei@^10.7.8`, `@react-three/fiber@^9.7.0` |
| `npm install` ran | ✅ | `package-lock.json`, node_modules 600 MB, "added 55 packages … 0 vulnerabilities" |
| `components/ui/hero-futuristic.tsx` | ❌ | **missing** (both `src/components/ui/` and `components/ui/` empty) |
| `components/ui/demo.tsx` | ❌ | **missing** |
| `lib/utils.ts` (`cn()`) | ❌ | missing |
| typecheck / browser verification | ❌ | `typecheck_workspace` never called; zero browser proof |
| Final "Finished" claim | ❌ | **false** — no deliverable file produced |

Provided sources are untouched at `/tmp/provided_backup/` (the agent `mv`'d `_provided/` aside before scaffolding) — the deliverable was literally 2 `copy_file` calls away.

## Root causes & engine findings

1. **🔴 Gate hole (reproducible, engine):** the finish gate's `_WORK_TOOLS` still counts
   `run_terminal`/`execute_code` as "work", and the verify gate only fires when the agent **wrote**
   code files. An agent that runs terminal/execute_code but writes nothing sails straight to
   "Finished" with an empty deliverable — the exact D4 failure class, still open through the
   non-file tools.
2. **🟡 Environment — interactive CLI trap:** `npx shadcn init --yes` prompts "Select a component
   library » Use arrow-keys". Headless, it can never be answered; the agent burned ~10 iterations
   (incl. piping `printf '1\n1\n'`). No interactive-prompt guard on `run_terminal`.
3. **🟢 Environment — sandbox cwd (FIXED this session):** `execute_code` ran at the process cwd
   (repo root). Inside the repo that drowned the agent in repo-map noise (E1 loop). Fix: run the
   sandbox OUTSIDE the repo + harness `chdir`s into the workspace → E2 explored correctly.
4. **🟢 Engine boot fix shipped:** `src/tools/browser_mcp.py` imported `mcp` at module level,
   which crashes engine boot on this box (`pywintypes` missing). Made lazy per its own docstring
   ("never raises into a turn"); engine now boots headless.
5. **🟡 Model behavior:** `sarvam-105b-conversations` ignored an explicit tester instruction under
   budget pressure and re-attempted the blocked path instead of finishing the trivial last mile.

## Recommendation

1. Close the gate hole: exclude `run_terminal`/`execute_code`/`think` from finish-gate "work" unless
   the workspace changed (hash-diff), or treat "zero files exist at finalize for a copy/compose
   task" as unverified (nudge to produce the deliverable).
2. Add an interactive-prompt guard to `run_terminal` (detect `Use arrow-keys`/`Select … »`) → kill +
   classify as environment failure → strategy pivot, so a blocking CLI can't consume a budget.
3. Re-run Test 3 once after the gate fix; the environment is now clean (external sandbox + cwd fix).
