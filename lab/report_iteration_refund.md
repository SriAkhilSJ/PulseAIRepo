# Report: Hermes Iteration-Refund + Test-3 Retest

Date: 2026-08-13
Author: opencode

## 1. Claim under test (HERMES-7)
"An agent turn whose ONLY action is `execute_code` is refunded — it does not
consume the iteration budget. Fixes the Test-3 graceful-termination 400 crash
where 42 `execute_code` calls blew the budget and forced a grace call."

## 2. Implementation
File: `src/graphs/chat_graph.py` (in `ai_node`)

- `iteration_used`/`iteration_budget` are read from state. `budget_exhausted`
  is computed BEFORE the model call.
- If `budget_exhausted` is False AND the model returns a result whose ONLY
  tool calls are `execute_code` (and >=1 of them), the increment is undone:
  `next_used = iteration_used` instead of `iteration_used + 1`.
- All other paths (mixed tools, text-only, exhausted) keep the normal +1.

This is intentionally ONE-turn only: the next turn re-evaluates fresh, so a
multi-turn `execute_code` binge still gets charged on subsequent turns that
also do other work.

## 3. Tests
File: `src/tests/test_iteration_budget.py` (3 new tests)
- `test_ai_node_refunds_execute_code_only_turn` — refund applies.
- `test_ai_node_no_refund_on_mixed_tools` — mixed turn still +1.
- `test_ai_node_no_refund_on_grace_path` — exhausted turn still +1.

Result: full suite `75 passed` (incl. 6 pre-existing budget tests,
`test_lab_fixes.py`, `test_review_autopsy_fixes.py`). No regressions.

## 4. Live re-validation (the ACTUAL finding)
Ran `lab/run_eval_test3_retest.py` with `AGENT_ITERATION_BUDGET=50`.

### 4a. Did the refund fix the crash?
YES. `error` field empty, no 400, run terminated cleanly as `recovering`.
The 42 `execute_code` turns were refunded, so the run did NOT hit budget
exhaustion / the grace-call path. The graph-level claim is verified.

### 4b. Did the eval pass? NO — but for a different, deeper reason.
The run still ends in `recovery` (`failures.count=3`, recovery limit).
The model gets stuck in a **guard-wall loop**:

1. `run_terminal: npx create-next-app .`  -> FAIL (dir conflicts with `_provided/`)
2. `run_terminal: mkdir -p /tmp/...`        -> FAIL (POSIX cmd rejected by R3-1 guard)
3. `run_terminal: which npx`                -> FAIL ("which" not on Windows)
4. `execute_code: import subprocess ...`    -> REJECTED ("import subprocess disabled")
   -> retries the same banned import 42x, never pivots.

The sandbox returns these as SOFT error strings (not crashes), so the graph
continues and the model interprets "rejected" as "try a different spelling".
Result: 42 near-identical `execute_code` calls, 16 of them blocked by the
`subprocess` validation. Zero `copy_file` calls — the model never even
attempts the real deliverable.

Root cause is SCENARIO/model-behavior, not a gate bug:
the workspace is EMPTY except `_provided/`, so the model sees "no codebase"
and tries to scaffold, but every scaffold avenue is walled off
(root conflict, POSIX guard, subprocess ban). It loops.

## 5. Pre-scaffold attempt (BLOCKED)
Next step was to pre-scaffold the workspace so `_provided/` + a real
`src/components/ui/` target make `copy_file` the obvious move, removing the
walls that trigger the loop.

Attempt: `npx create-next-app@latest .` into a temp dir.
Result: FAILED — `npm error network read ECONNRESET` (errno -4077).
The npm registry is currently unreachable from this environment, so
dependencies cannot be installed. Pre-scaffold cannot be completed offline.

## 6. Status & recommendations
- [DONE] Iteration refund implemented + tested (75 pass). Claim verified at
  graph level.
- [DONE] Live eval confirms the refund removes the 400 crash.
- [BLOCKED] Pre-scaffold of the sandbox — needs network. Retry when the npm
  registry is reachable, or copy a pre-built Next.js tree from a cache.
- [OPEN] Even after pre-scaffold, consider hardening the `execute_code`
  rejection message to say "use run_terminal or write_file instead of
  subprocess" — would break the 42x spelling loop earlier.

## 7. Files touched
- `src/graphs/chat_graph.py` — refund logic in `ai_node`
- `src/tests/test_iteration_budget.py` — 3 new refund tests
- `lab/run_eval_test3_retest.py` — existing harness (read only)
- `lab/report_test3_retest.json` — last live run artifact
