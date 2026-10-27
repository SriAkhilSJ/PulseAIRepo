# Agent Core completion discipline

**Date:** 2026-10-27

**Scope:** verification-to-final-response handoff; provider-neutral Agent Core behavior

> **Current follow-up (2026-10-27):** the inclusive final-response reserve remains in place. Commit `f8108ccd` adds a second completion requirement: unresolved non-environment failed checks survive edits and unrelated green checks until the same check identity passes. The latest full-stack live run remains failed and predates this follow-up. See [`../core.md`](../core.md).

## Simple result

| Area | Before | After | Optimization — why |
|---|---|---|---|
| Call budget | All `N` provider calls could remain tool-capable, so useful work could finish on call `N` with no call left for the user-facing result. | Calls `1…N-1` may use tools; call `N` is reserved for a concise tool-free response. | The configured budget is now an inclusive ceiling rather than a work budget plus an accidental `N+1` farewell. |
| API calls vs. tools | The external breaker treated provider-call count as if it were interchangeable with tool count. | Provider requests and tool executions are monitored separately; one response may request zero, one, or multiple tools, and results normally require another provider request. | Preserves the real agent loop instead of assuming a false one-call/one-tool relationship. |
| Truthful completion | A closing response at the wall could be mistaken for success merely because it contained completion language. | Clean completion at the reserve requires deterministic activity, delivery, fresh verification, plan, failure, and post-nudge evidence. | Wording cannot fabricate a successful receipt. |
| Pending work | A budget check could compete with an already-emitted tool call. | Pending calls route to tools before any budget-finalization check. | The reserve never drops work the model already requested. |
| Runner contract | Agent Core and the bridge could enforce different limits; the bridge cancelled at call `N` while Agent Core expected another summary request. | `--max-llm-calls N` is exported to Agent Core as the same inclusive ceiling; only `N+1` is treated as contract drift. | The final legal call can finish while the external breaker remains a hard backstop. |
| Python verification | `python -m unittest` was not classified as a static check. | `unittest` joins the provider-neutral terminal check vocabulary. | The benchmark’s real six-test pass can participate in the same evidence gate as `pytest`, `go test`, and other checks. |
| Monitoring | The handoff had no dedicated signal. | `context.status` emits `phase=final_response_reserve`, call/budget values, and the boolean evidence decision; runner outcomes record the aligned budget. | Operators can distinguish clean evidence-backed closure from a budget-cut report without exposing prompts or tool bodies. |

## Failed-check repair follow-up

The original reserve guaranteed a legal closing response, but a live 4/5 full-stack run exposed a different boundary: a failed acceptance check did not create a durable requirement to edit and rerun that same check.

| Before | After | Why |
|---|---|---|
| The newest passing static check could dominate status. | Every concrete non-environment failed check contributes a required `failed_checks` completion domain. | A weaker check cannot erase stronger red evidence. |
| An edit made evidence stale but did not preserve the failed check's identity. | Check identity is normalized and hashed; mutation marks repair landed but does not clear debt. | The obligation survives without copying commands into completion metadata. |
| Repair mode offered mutation and verification together. | `verification_repair_required` withholds verifier tools; `verification_recheck_required` withholds mutation tools after a landed repair. | Unchanged retry loops and unverified repair claims are structurally blocked. |
| Any green verification could restore completion. | Only success from the same failed check identity removes its debt. | Completion requires proof of the actual repair. |

Environment/toolchain failures remain outside source-repair debt and use the existing strategy-pivot path. The implementation is general; it contains no benchmark, SQLite, provider, model, or expected-output special case.

## Source check

The design was chosen only after re-checking current source from leading GitHub coding agents at pinned commits:

| Repository | Pinned source | Completion behavior used as evidence |
|---|---|---|
| OpenCode | [`f993a89d`](https://github.com/anomalyco/opencode/tree/f993a89d13c73ff6f6537d6b97e78e138a3ea363) | `SessionRunner` turns the maximum-step request into a final instruction with tools disabled (`toolChoice: "none"`). This is the direct precedent for the inclusive reserve. |
| OpenHands | [`311dc1be`](https://github.com/OpenHands/OpenHands/tree/311dc1be63758e51d61e43d6574d5c03c7a30688) | The explicit `finish` action is instructed to run only when work is certainly complete and tested. This supports evidence-gated completion rather than trusting completion prose. |
| Gemini CLI | [`363a1311`](https://github.com/google-gemini/gemini-cli/tree/363a13119a57354f469732577518b9d6b319d1d6) | Function results return control to the model and the loop ends on an assistant response with no tool calls. This confirms that a tool result generally needs a later provider response. |
| Cline | [`775d0398`](https://github.com/cline/cline/tree/775d0398039977ca5447ed39c1a7f178df69aa87) | A no-tool assistant response is terminal unless a completion guard requests bounded recovery. |
| Codex | [`2cab11ca`](https://github.com/openai/codex/tree/2cab11ca40aad193382348a7bda46da2fc47596a) | Function results lead to another sampling request; rollout reminders are useful before the limit but do not themselves guarantee a final response slot. |

No provider name, benchmark prompt, expected file content, or model-specific branch is part of the implementation.

## Contract

For an inclusive provider-call budget `N`:

```text
calls 1 … N-1: normal Agent Core turns, tools available
call N:         full conversation + final-response instruction, tools disabled
call N+1:       external contract-drift backstop (should never be needed normally)
```

The one-shot warning moves ahead of the reserve (`N-2` at the latest), allowing the penultimate call to either finish directly or request the last necessary tools. Tool calls emitted by that penultimate response execute before the reserved provider call.

Legacy persisted checkpoints that already reached the old wall retain one tool-free compatibility grace call. New aligned runs normally close within `N`.

## Evidence gate

The reserved response always reaches the user, but it receives a clean-wrap marker only when deterministic state says completion is ready:

1. the task is conversational/non-execution, **or** execution has real tool activity;
2. every named deliverable exists in the workspace;
3. all task-required verification domains have a fresh passing receipt;
4. every explicit plan step is complete;
5. the trailing tool batch has no unrecovered failure; and
6. if a work-demanding nudge fired, at least one tool action followed it.

If any condition fails, the same final call must report what is incomplete and finalization remains budget-cut/unverified. The reserve does not bypass failed or stale verification, missing artifacts, an open plan, or trajectory-loop protection.

## Implementation map

- `src/graphs/budget.py` — inclusive reserve boundary, final instruction, and earlier warning point.
- `src/graphs/chat_graph.py` — tool-free final request, monitoring, failover parity, and evidence-backed clean-wrap state.
- `src/graphs/gates.py` — deterministic completion-readiness predicate and `unittest` verification recognition.
- `scripts/run_bridge_turn.py` — one shared Agent Core/runner ceiling and `N+1` emergency backstop.

## Original completion-reserve provider-free receipt

| Check | Result |
|---|---|
| Python compilation | Passed for all edited source and test modules |
| Focused completion/runner/honesty gate | **161 passed** |
| Full `src/tests` suite | **2,773 passed, 30 failed, 27 skipped, 1 xfailed**; the same 30 known unrelated failures as the prior optimized tree, plus 9 new passing contracts |
| Diff-aware Ruff | 52 findings at `HEAD`, 52 after the change; 0 findings in the new regression file |
| Reserved slot | Unbound model used at `N`; bound tool model not invoked |
| Ready vs. incomplete attribution | Both paths covered |
| Pending boundary tool | Dispatches at `N-1` and at legacy exhausted checkpoints |
| Evidence blockers | Missing output, failed verification, open plan, trailing failure, and no post-nudge action covered |
| Runner ceiling | Calls `N-1` and `N` allowed; `N+1` stops |
| Existing trajectory guard | Included in the green focused gate and unchanged |

## Current follow-up receipt

| Check | Result |
|---|---|
| Affected repair/routing/annotation files | **34 passed** |
| Earlier broader completion/routing/progress/runner gate | **181 passed** |
| Clean final `main` full provider-free suite | **2,802 passed, 25 failed, 26 skipped, 1 xfailed** |
| Changed-module compilation and scoped whitespace | Passed |
| Diff-aware Ruff | 0 findings on added lines |
| Live validation of failed-check repair | **Not yet performed** |

A clean detached comparison found the same 25 failing test identities on final `main` and the pre-merge `main` baseline, with 0 new failures. The final tree has 2,802 passing tests versus 2,659 in the pre-merge baseline. Provider-free results establish deterministic contracts only, not live-model effectiveness.

## Bounded live receipt

After all provider-free checks passed, GitHub Actions run
[`40477838008`](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40477838008)
used the existing write-only `CUSTOM_API_KEY` with `z-ai/glm-5.3-flash`. The genuine task
completed successfully in **6 of 8 provider calls** and 32 seconds: all six independent tests
passed, tests stayed unchanged, production code changed, six tools completed, and no budget
stop fired. Because the agent completed naturally two calls early, the call-8 reserve event
was correctly absent.

The workflow's overall conclusion is red only because its temporary grader incorrectly made
that fallback event mandatory even for early completion; every task-quality and budget check
passed. No paid rerun was used to manufacture a reserve event. The full sanitized receipt and
caveat are recorded in `docs/AGENT_CORE_PERFORMANCE_EVIDENCE.md`.

That statement is scoped to the completion-reserve experiment. Later full-stack runs did occur;
the latest failed 4/5, and its follow-up repair is provider-free tested only. See
`docs/CRUSOR_FULLSTACK_BENCHMARK.md` and `core.md` for current status.
