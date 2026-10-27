# Agent Core tool-cycle optimization

**Date:** 2026-10-27

**Scope:** planning → execution → recovery reliability; no provider-specific code

## Simple result

| Area | Before | After | Optimization — why |
|---|---|---|---|
| Alternating loops | `A → B → A → B` bypassed the consecutive-call guard. | Cycles of 1–5 actions are recognized from completed tool outcomes. | Stops repetitive trajectories, not only one repeated call. |
| Recovery | The model could continue until a global turn/token limit. | At 3 identical cycles it receives one strategy-change warning. | Gives the agent one bounded chance to recover autonomously. |
| Hard bound | No trajectory-specific stop existed after the warning. | At 5 identical cycles the graph ends without another model request. | Protects time, tokens, and side effects while preserving session state. |
| False positives | A name-only cycle rule could block normal edit/test iterations. | The fingerprint includes canonical arguments, status, and the complete result. | Changed edits or changed test output are progress and break the cycle. |
| Privacy/memory | A naïve tracker could retain tool bodies/results. | State retains at most 25 `{tool, sha256}` samples. | Fixed memory; no prompt, arguments, output, or credential value is retained by the guard. |
| Monitoring | Alternating loops had no specific runtime signal. | Soft/hard detections emit `context.status` with tool names and cycle counts only. | The desktop/evidence stream can explain why recovery or stopping occurred. |

## GitHub source check

The design was selected after inspecting current source at these exact commits:

| Repository | Pinned source | Relevant pattern |
|---|---|---|
| Gemini CLI | [`363a1311`](https://github.com/google-gemini/gemini-cli/tree/363a13119a57354f469732577518b9d6b319d1d6), `packages/core/src/services/loopDetectionService.ts` | Hash tool name+arguments; recognize repeating cycles of length 1–5; reset for each prompt. |
| Cline | [`775d0398`](https://github.com/cline/cline/tree/775d0398039977ca5447ed39c1a7f178df69aa87), `sdk/packages/core/src/runtime/safety/loop-detection.ts` and `session-runtime-orchestrator.ts` | Canonical argument signatures; soft warning at 3; hard escalation at 5; reset on a fresh run. |
| OpenCode | [`f993a89d`](https://github.com/anomalyco/opencode/tree/f993a89d13c73ff6f6537d6b97e78e138a3ea363), `packages/core/src/v1/config/permission.ts` and `packages/tui/src/util/permission.ts` | Treat repeated-call continuation as an explicit `doom_loop` policy/decision rather than silently retrying. |
| Codex | [`2cab11ca`](https://github.com/openai/codex/tree/2cab11ca40aad193382348a7bda46da2fc47596a), `codex-rs/core/src/rollout_budget.rs` and `codex-rs/core/src/session/rollout_budget.rs` | Enforce an independent rollout budget and inject bounded remaining-budget reminders. |
| OpenHands | [`311dc1be`](https://github.com/OpenHands/OpenHands/tree/311dc1be63758e51d61e43d6574d5c03c7a30688) | Current tree was checked for stuck/loop/trajectory handling; no mechanism was copied without a clear current source contract. |

PulseAI already had rollout budgets, identical-read suppression, identical failed-command
nudges, empty-response convergence, and pre-delivery exploration bounds. Copying those
mechanisms again would add complexity without closing the actual gap. The selected change
combines Gemini's multi-action cycle shape with Cline's two-stage escalation, then makes it
safer for a coding agent by requiring identical **outcomes** as well as identical actions.

## PulseAI behavior

For every completed, progress-bearing tool result, Agent Core computes:

```text
sha256(tool name, canonical arguments, success/failure status, complete result)
```

Only the tool name and digest enter turn state. The detector examines a maximum of 25
samples (`5 actions × 5 repetitions`) and chooses the shortest repeated trailing cycle.

- Fewer than 3 cycles: no action.
- 3 or 4 identical cycles: emit one warning and ask the model for a materially different
  strategy.
- 5 identical cycles: route to `tool_cycle_limit`, mark the task unsuccessful, preserve
  workspace/session state, and stop before another provider request.
- Any changed call arguments, status, or result: no cycle.
- A new user turn: clear cycle history and escalation state.

## Validation contract

Provider-free tests cover:

- canonical argument ordering;
- no raw args/results in retained samples;
- 1-action and alternating 2-action cycles;
- soft and hard thresholds;
- cycles up to the fixed history bound;
- changed edit/test results as productive work;
- monitoring events without args/results;
- direct hard-stop routing with no extra model call;
- reset on every new user turn;
- compatibility with the existing duplicate-read, acknowledgement, user-interest, and stall guards.

### Measured keyless result

| Check | Result |
|---|---|
| Focused Agent Core compatibility gate | **158 passed** |
| Clean `d34879cb` full-suite baseline | **2,760 passed, 25 failed, 27 skipped, 1 xfailed** |
| Optimized working tree full suite | **2,764 passed, 30 failed, 27 skipped, 1 xfailed** |
| Regression comparison | All 9 new guard tests passed; the 25 baseline failures were unchanged, and the 5 additional failures map only to the 18 pre-existing generated desktop-output modifications. **No new Agent Core failure.** |
| Syntax / whitespace | `py_compile` and scoped `git diff --check` passed |
| Diff-aware Ruff | 49 findings before and after in legacy modules; zero added finding classes. The new test file passed Ruff. |
| Detector microbenchmark | 100,000 checks over a 10-sample `A/B × 5` history averaged **4.064 μs/check**; retained state was 10 fixed-size samples. |

The nonzero full-suite totals are reported rather than hidden by deselection. The clean
baseline proves those failures predate this optimization; five extra working-tree failures
come from generated desktop files that this Agent Core change deliberately leaves untouched.

A live-key test is intentionally last: implementation correctness and regressions must pass
without spending provider credits before one bounded genuine Agent Core turn is attempted.
