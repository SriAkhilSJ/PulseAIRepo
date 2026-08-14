# Retest-3 — Hermes Runtime Pass (Cost-Guarded)

**Date:** 2026-08-14  
**Provider/model:** Sarvam custom endpoint / `sarvam-105b-conversations`  
**Verdict:** ⛔ **WATCHDOG-ABORTED at 181 seconds** — not a pass or completed run.

## Cost controls used

- `AGENT_ITERATION_BUDGET=12`
- `PROVIDER_SAFE_LIMIT=6000`
- Auxiliary LLM summarization disabled because a `custom` provider's default auxiliary model resolves to the same 105B model, not a cheap model.
- 30-second external watchdog
- Kill on three identical tool calls
- Kill after 60 seconds without events
- Kill at 180 seconds while either named deliverable is missing
- Absolute hard cap: 300 seconds

## 30-second monitoring record

| Time | Events | Tool calls | hero file | demo file |
|---:|---:|---:|---:|---:|
| 30s | 1 | 0 | missing | missing |
| 60s | 10 | 2 | missing | missing |
| 91s | 22 | 5 | missing | missing |
| 121s | 24 | 6 | missing | missing |
| 151s | 24 | 6 | missing | missing |
| 181s | 29 | 7 | missing | missing |

Watchdog action:

```text
KILL: named deliverables still missing after 180 seconds
process exit=143
```

## Work completed before termination

The model:

1. Listed the workspace.
2. Listed `_provided` and found both source components.
3. Produced an accurate plan.
4. Confirmed no `package.json` existed.
5. Tried `create-next-app` in the workspace root; it correctly failed because `_provided/` conflicted.
6. Retried with a child directory and successfully created a complete Next.js/TypeScript/Tailwind project.
7. Installed `three`, `@react-three/drei`, and `@react-three/fiber` successfully.

The generated project landed at:

```text
/home/user/test3_ws_final/test3_ws_final/
```

That nesting was not the requested final workspace structure. Neither component had been copied when the cost guard fired.

## Calls

- Recorded tool calls: **7**
- Approximate provider calls: **~9** (two planning calls plus seven tool-producing turns)
- Exact provider usage is unavailable because the process was terminated before final analytics were written.
- No auxiliary summarizer calls were intentionally made.

## Tool sequence

```text
list_files(.)
list_files(_provided)
think
execute_code(workspace inspection)
run_terminal(create-next-app in root; failed due _provided conflict)
run_terminal(create-next-app in nested test3_ws_final; passed)
run_terminal(npm install three/drei/fiber; passed)
```

## Root cause

The failure was primarily a **workflow-order and scaffolding-path problem**, not a provider outage:

1. The agent spent its early calls inspecting and planning instead of placing the two cheap, explicit `copy_file` deliverables.
2. `create-next-app .` cannot run in a workspace containing `_provided/`, so its first scaffold attempt failed predictably.
3. The recovery command used the workspace's own name as a child directory, producing `workspace/workspace/` rather than the requested root project.
4. Scaffolding and npm installation consumed about 70 seconds of tool wall time, plus model latency between calls. The dependencies finished only shortly before the 180-second guard.
5. The watchdog correctly treated “dependencies installed but zero named deliverables” as unsatisfactory and terminated the run.

## Offline fixes applied after the abort

- Added a task-gated `scaffold_nextjs` tool. It scaffolds with `--skip-install` in a temporary sibling, merges into the correct workspace root, preserves `_provided`, and installs dependencies exactly once.
- The tool refuses to overwrite an existing project and rejects invalid package names.
- Added a COPY-FIRST context rule: explicit `_provided` → `copy_file` deliverables are prioritized before expensive setup.
- Added planner rules forbidding both known-bad paths: `create-next-app .` with `_provided` and `<workspace>/<workspace>` nesting.
- `scaffold_nextjs` safely accepts copy-first files already placed under `src/components/ui/`.
- Added the tool only to UI-engineering profiles, not the general/core tool waist.
- Added approval, checkpoint, durable journal, verification-invalidation, and conflict-serialization integration for the new tool.
- Fixed tool-result projection so non-zero terminal exits are marked as errors rather than `status=ok`.
- Added focused scaffold regression tests and reran the README-equivalent suite: **589 passed, 1 upstream warning**.

## Assessment

The new runtime controls behaved correctly:

- progress was observable per session;
- tool intent/results were journaled;
- the run stayed within the configured iteration budget;
- no identical-call loop occurred;
- the external watchdog terminated the process at the agreed dissatisfaction threshold;
- no false `Finished` response was produced because the process was stopped while deliverables were missing.

The test did **not** demonstrate a Retest-3 pass. The dominant delay was scaffolding and dependency installation before the two cheap `copy_file` operations. The next Retest-3 attempt should either use a longer explicitly approved wall-time or change the benchmark to a pre-scaffolded workspace if the goal is to isolate component integration rather than package-install performance.
