# Crusor full-stack benchmark

**Date:** 2026-10-27

**Task:** Build a complete SprintBoard website with a Python standard-library REST backend, SQLite persistence, and a responsive HTML/CSS/JavaScript frontend.

**Model:** `z-ai/glm-5.3-flash` through the existing generic custom-provider path

## Outcome

No website was accepted or committed. Both bounded live attempts ended honestly as incomplete because Agent Core never created an application file. The independent suite, immutable-test hash, allowlist, credential scan, and completion gate all remained active; no test was weakened and no result was fabricated.

| Measure | First attempt | Corrected-harness retry |
|---|---:|---:|
| Actions run | [40491108367](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40491108367) | [40491628045](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40491628045) |
| Provider calls | 12 / 12 | 12 / 12 |
| Runtime | 58 s | 54 s |
| Final reserve | Observed; evidence not ready | Observed; evidence not ready |
| Turn verdict | `turn_done`, `completed=false` | `turn_done`, `completed=false` |
| Application bytes | 0 | 0 |
| Tests immutable | Yes | Yes |
| Credential persisted | No | No |
| Token telemetry | 206,710; token breaker fired | 111,177; within retry ceiling |
| Tool trajectory | `read_file → run_terminal ×10` | `list_files ×2 → read_file ×2 → terminal ×7` |

The retry corrected the benchmark’s hidden-test placement, reduced the exposed tool menu, and removed the token-stop confounder. It still produced no `write_file` call, proving the remaining failure was in Agent Core’s routing contract rather than the grader.

## Root cause

Two general rules interacted badly before the first provider request:

1. `_begin_diagnostic_turn` asks `StepTracker` to create `diagnostics/traces/...` inside the active workspace. `_workspace_is_effectively_empty` counted that Agent Core-owned evidence as user project content, so a genuinely fresh build did not enter the structural forced-delivery phase.
2. The deterministic interest classifier gave any phrase matching “do not modify” global precedence. A normal scoped constraint—“build the application; do not modify the immutable tests”—therefore changed the whole turn to `change_policy=no_changes`, removing mutation tools even though the same instruction explicitly requested a build.

This explains the observed read/terminal-only trajectories and why the final evidence predicate remained false.

## Provider-free fix

| Before | After | Optimization — why |
|---|---|---|
| Runtime `diagnostics/` made a new workspace look populated. | Runtime-owned `diagnostics/` and dot-prefixed fixtures are ignored by the empty-workspace signal. | Agent evidence must not disable Agent Core’s own fresh-delivery guard. |
| “Do not modify the tests” cancelled “build the app.” | An independent positive mutation request wins while the protected artifact remains a recorded constraint. | Scoped immutability is not a global no-change instruction. |
| First turn exposed reads and terminals without a deliverable. | The exact benchmark entry state resolves to `forced_delivery` with only `write_file`. | File delivery becomes structurally available before exploration or verification. |
| Failed build could have been described as successful. | Call 12 remained tool-free, evidence readiness was false, and both runs ended `completed=false`. | Completion discipline remained honest under a harder failure mode. |

Explicit no-change commands such as “run the tests without changing code” remain `no_changes`; the fix does not weaken read-only requests.

## Local evidence

- edited modules and regressions compile with Python 3.11;
- focused interest/autonomous/completion gate: **155 passed**;
- expanded routing, artifact, finalization, progress, and trajectory gate: **240 passed**;
- full provider-free suite: **2,781 passed, 31 failed, 26 skipped, 1 xfailed**;
- 30 persistent failures match the known unrelated baseline; the one additional LSP timeout passed immediately in an isolated rerun (**1 passed**), confirming an environment-sensitive startup rather than a product regression;
- the exact state containing runtime diagnostics plus a hidden immutable test now binds only `write_file`;
- adding a real user file makes the workspace non-empty again;
- no provider-specific branch, prompt answer, expected application content, or model name is hardcoded in Agent Core.

No third provider run was made. Another paid full-stack attempt requires explicit user approval after this provider-free correction. The temporary workflow was removed, and no pull request, merge, deployment, or failed site commit was created.
