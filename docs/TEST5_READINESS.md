# Test 5 readiness review

**Reviewed:** 2026-08-25

**Integration branch:** `arena/01a03741-pulseairepo`

**Current verdict:** Attempt 11 live-validated bounded output-limit recovery and runner liveness, but falsely completed without verification and delivered a non-runnable product; **overall FAIL, not merge-ready, and no retry authorized**

## History and merge verdict

The old agent-development branch was not safe to merge wholesale: it predates the current R4 desktop tree and would regress hundreds of vendored Code OSS files. Its useful Test-5 commits were reviewed and selectively integrated instead.

Attempts 1–3, desktop run `test5-4b`, and guarded attempts `test5-5` and `test5-6` all failed runtime/product delivery. Attempt 6 was manually cancelled after 16 observed provider requests and more than 180 seconds with an empty workspace. Therefore **do not merge into `main` and do not delete branches**. A future separately authorized run must pass both runtime and independent product grading first.

## Attempt-4b root cause and repair

The failure was not caused by the bridge's 1 MiB frame limit; a roughly 30KB payload is well below it. The confirmed deadlock was an approval-policy mismatch:

1. `scripts/run_bridge_turn.py` enabled autonomous writes but did not answer `safety_request` frames.
2. The bridge enabled the approval channel while leaving `stream_agent` at its interactive `ask` policy.
3. `SafeToolNode` queued an ordinary workspace mutation and waited up to 300 seconds for a UI that the headless runner does not have.

The repair preserves interactive behavior while making the benchmark path explicit and fail-safe:

- the guarded runner sets `PULSEAI_BRIDGE_APPROVAL_POLICY=workspace_session`;
- the bridge validates and forwards that policy to `stream_agent`;
- the runner always answers any residual approval frame, auto-approving only warning-free `write_file`, `edit_file`, or `copy_file` operations contained by the run workspace and denying sensitive/escaping/other calls;
- outcome evidence records safety request, approval, and denial counts;
- model guidance applies Hermes' recovery rule: keep individual tool argument payloads below roughly 8K tokens, split naturally modular applications across files, and never repeat a dropped oversized payload unchanged.

No Hermes source was copied. The comparison was performed against NousResearch/hermes-agent commit `e5032945cbebb64b8a819b66ec831c1906297b81`.

## Deterministic regression evidence

The new regression drives a 35KB safe write through the real `SafeToolNode` policy/tool path and proves that the file lands without an approval wait. Separate tests pin bridge policy forwarding and fail-closed headless approval classification.

Focused verification on 2026-08-25:

- new approval/large-write regressions: **3 passed**;
- bridge transport, parallel tools, benchmark harness, prompt guard, and prompt-cache audit selection: **79 passed** with the prompt-size budget green;
- Python diff whitespace check: passed.

The provider-backed product test cannot run in this Arena sandbox because TLS to Sarvam fails. That is why these deterministic checks must precede exactly one guarded desktop attempt.

## Attempt 5 result — stop condition reached

Desktop attempt `test5-5` completed on 2026-08-25 with **RUNTIME FAIL / PRODUCT FAIL**. The Sarvam 105B model consumed the configured maximum of 20 LLM calls in a planning/search loop. Safety policy blocked a `curl` download attempt, no mutation landed, and the workspace remained empty. The operator reports approximately four credits consumed. Evidence was preserved and PR #9 was not merged.

This result proves the attempt-4b approval deadlock was not the attempt-5 boundary; the next boundary is model/tool strategy before the first file mutation. It does not yet prove whether the blocked download was itself incorrect or whether a supported dependency-vendoring pivot was available but ignored—the preserved frames must be reviewed before changing safety behavior.

Preserve `C:\test5-ws-attempt5`, `C:\test5-ws-attempt6`, and both evidence directories exactly. Attempt 6 was manually cancelled after more than 180 seconds and 16 observed LLM requests with zero files. Therefore human interventions were 1, and the missing outcome cannot honestly be attributed to a bridge crash: the runner did not catch `KeyboardInterrupt`, while the PowerShell wrapper used the redirected `Start-Process` path already proven capable of hanging.

The pre-delivery repair did activate too weakly: `execute_code` remained allowed, and Pulse mechanically copied Hermes' execute-code iteration refund without Hermes' surrounding guardrail posture. Four `os.walk` scripts could therefore inspect forever without advancing the counter. The corrected design counts every provider iteration, counts varied pre-delivery observations together, exposes only direct file mutations in forced-delivery mode, removes PowerShell stream redirection, records operator cancellation, and adds a runner-level no-file credit stop.

## Post-attempt-6 Hermes runtime audit

The counter bypass was real but not the complete reason Sarvam chose inspection. A minute-layer comparison found that Pulse's first Test-5 request combined a 16,445-character interactive persona, duplicate and contradictory task/style layers, multiple advisory planner calls, a system instruction appended after the human role, and 33 tools totaling 18,070 schema characters. The prompt explicitly promoted `think`, `execute_code`, explanation before action, clarification, replanning, and verification. Sarvam's observed meta/`os.walk` choices were valid under that overloaded contract.

The autonomous surface now uses a 1,234-character action contract, suppresses conflicting interactive context, bypasses advisory planning, pins the explicitly requested model/provider, orders all initial system guidance before the user message, and exposes only `write_file` for a fresh empty delivery workspace. The deterministic Windows Test-5 first-request construction is four messages / 3,084 content characters / one 591-character tool schema (the non-Windows variant omits the 313-character terminal contract). Exact post-sanitizer/post-trim payload capture and SHA-256 fingerprints are enabled for any future guarded run. Eager Hugging Face embedding initialization during graph import was also replaced with cache-only lazy memory.

See [`HERMES_RUNTIME_AUDIT.md`](HERMES_RUNTIME_AUDIT.md) for the complete layer matrix and causal chain.

## Attempt 8 desktop result

Attempt `test5-8-desktop` confirmed the repaired Windows request shape and
Sarvam called the sole exposed `write_file` tool. Pulse wrote one 4,995-byte
`index.html`, emitted a successful tool result, and then produced no second
provider request or graph-terminal frame. The watchdog killed it after 613.5
idle seconds. Static inspection proves the file is truncated mid-CSS and
non-executable, so both runtime and product verdicts are FAIL.

The first silent boundary is after `tool_call_end` and before request 2.
Autonomous progress still initialized optional semantic tool memory in that
path despite autonomous context never reading it; streaming cleanup also left
an async HTTP generator pending. These faults are repaired deterministically,
watchdog outcomes are now durable, and focused tests pass without a provider
call. See [`TEST5_ATTEMPT8_DESKTOP.md`](TEST5_ATTEMPT8_DESKTOP.md).

No new live authorization follows from these repairs; do not merge PR #9 or
delete branches.

## Attempt 11 result

OpenRouter Attempt 11 proved the repaired failure boundary live. Three repeated
`lengthlength` output-limit responses were canonicalized and continued; request
4 produced a complete tool call. Repeated Windows console `OSError 22` failures
were isolated in the fallback log, and the bridge reached 13 responses for 13
requests plus `turn_done`.

End-to-end delivery still failed. The graph marked the turn complete without a
successful verification receipt. The final response promised a later
inspection, the terminal call lacked a paired end event after a Windows encoding
exception, two required local Three.js modules were absent, and the scene shader
used an undefined macro. Independent product verdict: FAIL. See
[`TEST5_ATTEMPT11_REVIEW.md`](TEST5_ATTEMPT11_REVIEW.md).

A provider-free follow-up repairs completion-verdict propagation, final tool
event flushing, UTF-8 terminal pipes, and repeated complete finish reasons.
Focused contracts pass 144/144; see
[`ATTEMPT11_COMPLETION_REPAIR.md`](ATTEMPT11_COMPLETION_REPAIR.md). This does not
change Attempt 11's historical FAIL.

PR #9 remains unmergeable. No provider retry, branch deletion, or Agentic UI
work is currently authorized.
