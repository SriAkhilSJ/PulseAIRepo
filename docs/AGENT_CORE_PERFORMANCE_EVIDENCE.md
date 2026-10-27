# Agent Core bounded debugging performance

**Date:** 2026-10-27

**Provider/model:** `custom` / `z-ai/glm-5.3-flash`

## Task

Agent Core received a deliberately broken, dependency-free Python slug library and six
immutable `unittest` cases. It was asked to inspect the implementation and tests, make only
production-code changes, run the complete suite, reread the final implementation, and finish
with evidence.

The tests required whitespace/punctuation normalization, accent transliteration, ASCII
letter/number preservation, empty-input handling, and stable suffixes for duplicate slugs.

## Before: observed completion defect

**Run:** [GitHub Actions 40474992092](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40474992092)

| Measure | Result |
|---|---|
| Independent functional grade | **6/6 tests passed** |
| Test integrity | Test file hash unchanged |
| Delivery | Production file hash changed |
| Runtime | 43 seconds |
| Provider turns | 8 requests / 8 responses |
| Completed tool calls | 6 |
| Tool sequence | `read_file → read_file → terminal → terminal → terminal → read_file` |
| Turn receipt | `turn_done`, but `completed=false` |
| Stop reason | Eight-call breaker fired before a successful completion handoff |
| Loop guard | No identical completed trajectory cycle detected |
| Credential handling | Key normalized in runner memory; not printed or persisted |

The frame stream had no telemetry frame, so this run provides no trustworthy token-count
measurement. A zero token field must not be interpreted as zero usage.

## After: evidence-backed completion handoff

**Run:** [GitHub Actions 40477838008](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40477838008)

**Commit:** `338f96bbbf2f7abdd4df3524401dc49f93489fb1`

| Measure | Result |
|---|---|
| Genuine Agent Core task step | **Succeeded** |
| Independent functional grade | **6/6 tests passed** (`Ran 6 tests`, `OK`) |
| Turn receipt | **`turn_done`, `completed=true`** |
| Test integrity | Test file hash unchanged |
| Delivery | Production file hash changed |
| Runtime | **32 seconds** |
| Provider turns | **6 requests / 6 responses**, inside the aligned 8-call ceiling |
| Completed tool calls | 6 |
| Tool sequence | `read_file → read_file → think → terminal → terminal → read_file` |
| Budget contract | `agent_iteration_budget=8`; no budget stop and no no-delivery stop |
| Telemetry | One telemetry frame; final cumulative input estimate `73,882` tokens |
| Stream evidence | 68 token frames, 25 tool-argument frames, 65 tool-output frames |
| Credential handling | `api_key_persisted=false`; secret value was not printed or uploaded |

Agent Core finished naturally on call 6, two calls before the ceiling, so the reserved
call-8 fallback correctly did not run. This demonstrates the desired primary behavior:
after work and verification, return the user-facing result instead of spending the entire
provider budget. Provider calls and tool calls are separate loop dimensions—a response can
request multiple tools, while tool results generally require a later provider response.

### Workflow conclusion caveat

The Actions run is shown as red even though the genuine task step and every task-quality
check above passed. The temporary grader incorrectly required
`final_response_reserve_observed=true` unconditionally. That is a fallback-only event and
must not appear when the agent completes naturally before call 8. The sole failed check was
therefore the over-constrained grader assertion; the receipt recorded all of these as true:

- `turn_done` and `completed`;
- aligned iteration budget;
- all six tests pass;
- immutable tests unchanged;
- production code changed;
- tool execution observed;
- provider/token bounds respected; and
- no budget stop.

No second paid run was made merely to force a safety fallback. The deterministic reserve
path is covered provider-free; the live run validates the more important normal completion
path.

## Comparison

| Dimension | Before | After | Optimization — why |
|---|---|---|---|
| Correctness | 6/6 | 6/6 | Completion work did not weaken repair quality. |
| Completion | `completed=false` | **`completed=true`** | Fresh verification can hand off to a concise final response. |
| Provider calls | 8 (cap consumed) | **6 of 8** | The agent stopped when the task was done rather than using calls as a quota. |
| Runtime | 43 s | **32 s** | Earlier truthful finalization removed wasted continuation time. |
| Hard-bound fallback | No final slot remained | Call 8 reserved tool-free | If natural completion does not happen, one legal response still remains. |
| Honesty | Functional work existed but receipt was incomplete | Independent tests, immutable-test hash, changed-production hash, and `completed=true` agree | Completion is tied to evidence, not prose. |

## Local validation supporting the live receipt

- focused completion, routing, runner, and honesty gate: **161 passed**;
- full provider-free suite: **2,773 passed, 30 failed, 27 skipped, 1 xfailed**;
- the same 30 known unrelated failures as the prior optimized tree, with 9 new passing contracts;
- Python compilation and scoped whitespace checks passed;
- diff-aware Ruff: 52 pre-existing findings before and after, with 0 in the new test file.

The temporary secret-bearing workflow was deleted immediately after this receipt. No
provider-specific application code, pull request, merge, or deployment was created.
