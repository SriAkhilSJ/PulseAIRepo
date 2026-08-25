# Test 5 readiness review

**Reviewed:** 2026-08-25  
**Source branch:** `arena/01a02a5c-pulseairepo` at `00d8ced8`  
**Integration target:** `arena/01a03741-pulseairepo`

## Verdict

The source branch was **not safe to merge wholesale**. It predates the merged R4 desktop work and differs from current `main` across hundreds of vendored Code OSS files; a tree merge would remove restored upstream files and current branding/discoverability changes.

Its six Test-5 commits were therefore reviewed and cherry-picked individually. The useful runtime, harness, and documentation changes are integrated without replacing the current desktop tree.

The agent is now a **candidate for Test 5 attempt 4**, not a claimed Test-5 pass. Attempts 1–3 remain honestly recorded as failures in `docs/HARNESS_STATUS.md`. A provider-backed attempt 4 is required for a product verdict.

## Integrated Test-5 work

1. Instrumented single-turn bridge runner with immutable JSONL evidence and credit circuit breakers.
2. Guarded Windows runner with provider preflight, hard wall-time cap, stall detection, and workspace/build activity checks.
3. Custom-provider generation timeout raised from 60 to 180 seconds (bounded to 10–300 seconds) with streaming support.
4. Terminal timeout handling tree-kills Windows child processes, bounds pipe cleanup, and permits cold package installs.
5. `execute_code` denial and tool documentation now teach the supported dependency-vendoring pivot.
6. General model-driven plan/task constraint validation with one bounded correction attempt.
7. `rm` safety detection no longer false-positives on `Format-Table` and still catches whitespace variants and bare `rm`.

## Defects found during integration review

The source branch was not accepted unchanged. This review fixed:

- **Constraint validation silently skipped real plans.** `TaskPlan.steps` contains Pydantic `TaskPlanStep` objects, but the branch called `step.get(...)`; the broad advisory exception handler converted that error into a false clean result. The validator now handles dictionaries and model objects.
- **Validator usage was not recorded for an initially empty ledger.** `usage_list or []` replaced an empty caller-owned list. It now preserves every provided list.
- **The runner's own timeout was not enforceable during silent output.** Blocking `stdout.readline()` could outlive `--timeout-s`. Stdout now feeds a queue on a reader thread, allowing the deadline loop to continue.
- **The interim `"rm "` safety fix was incomplete.** It missed tabs and a bare command. Token-aware matching now fixes the false positive without those bypasses.

Regression tests were added for the real Pydantic plan-step shape, usage accounting, and `rm` command boundaries.

## Verification completed

- Test-5 bridge runner echo smoke: `turn_done`, `completed=true`, zero provider calls.
- Test-5 planner/safety/harness/PTC selection: **66 passed**.
- Earlier focused selection covering planner, PTC, engine smoke, and review guards: **56 passed** before the additional integration fixes.
- Python compile check: passed.
- Diff whitespace check: passed.

The historical procedural `test_planner_manual.py` still performs a real provider call at import time and remains excluded by `src/tests/conftest.py`; it is not part of the deterministic readiness receipt.

## How to run attempt 4

On the configured Windows test machine, use a fresh workspace and run ID:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_test5_guarded.ps1 `
  -Workspace C:\test5-ws `
  -RunId test5-4
```

Do not reuse a run ID. Evidence is written under `bench-results/test5-4/`. Grade the generated product and runtime evidence; a clean harness exit alone is not a product pass.
