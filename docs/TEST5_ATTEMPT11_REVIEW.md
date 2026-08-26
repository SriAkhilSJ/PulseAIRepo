# Test 5 Attempt 11 — Independent Evidence and Product Review

Date: 2026-08-25

Evidence commit: `989ab85ed36ca5985864cf1b349f996c6111a75c`

Repair under test: `0bb00413f4a03b0172c4f6214018bad156fb1d2a`

## Verdict

| Layer | Verdict | Basis |
|---|---|---|
| Output-limit recovery | **PASS** | Three canonical `length` responses were continued; request 4 produced the first complete tool call. |
| Runner liveness | **PASS** | Repeated Windows console `OSError 22` events were isolated to the fallback log and did not terminate transport. |
| Bridge turn transport | **PASS** | 13 requests received 13 responses and the bridge emitted `turn_done`. |
| Autonomous completion integrity | **FAIL** | The graph emitted `completed=true` without successful verification; its final text said it was about to inspect rather than reporting completion. |
| Product | **FAIL** | Required local Three.js dependencies are absent and the scene shader has an uninjected compile-time macro. The website cannot render successfully. |
| Overall / merge gate | **FAIL** | PR #9 is not eligible to merge. |

Attempt 11 validates the deterministic repair's narrow runtime boundary, but it
does not establish end-to-end autonomous or product success.

## Evidence integrity

Arena independently confirmed:

- evidence commit `989ab85e` is a direct child of handoff commit `58665f64`;
- repair commit `0bb00413` and Windows deterministic evidence `352099c1` are
  ancestors;
- the commit adds only the Attempt-11 evidence directory and workspace snapshot;
- all 11 SHA-256 entries match the committed bytes;
- `outcome.json` records `turn_done`, `completed=true`, and no runner error;
- 13 `llm.request` and 13 `llm.response` frames exist;
- response usage sums to 86,160 input and 49,718 output tokens; and
- the evidence summary records $0.135878 cost, one successful probe, and no
  budget/no-delivery stop.

## What the repair proved live

The first three responses each exposed:

```text
raw_finish_reason: lengthlength
finish_reason:     length
incomplete:        true
output_tokens:     8192
```

The dedicated continuation budget allowed exactly three continuation calls.
The fourth response then produced a complete `write_file` call. This is direct
live evidence that duplicated output-limit metadata no longer falls through as
normal completion.

The runner also encountered `OSError: [Errno 22] Invalid argument` on nearly
every console heartbeat. Every event was written to
`runner_console_fallback.log`; bridge processing continued through all 13
responses and `turn_done`. This validates the heartbeat-isolation repair against
the original Windows failure mode.

OpenRouter budget discovery also worked through the custom route: bridge stderr
records a 1,048,576-token model window from `openrouter-api`.

## Why autonomous completion integrity failed

The run did not satisfy its own verification contract:

- eight `tool_call_start` frames have only seven matching `tool_call_end` frames;
- the unmatched `run_terminal` call hit a Windows `cp1252`
  `UnicodeEncodeError` in a subprocess writer thread;
- no `verify_ui_workspace` or `verify_ui_routes` call executed;
- no successful browser, console, shader, or static-server receipt exists;
- after the iteration budget was exhausted, the last two assistant responses
  said they would inspect or verify next; and
- the final `turn_done` message was: “Let me inspect the current state of the
  workspace to see what exists and what's missing.”

Marking that state `completed=true` is a completion-integrity failure even
though the bridge transport shut down cleanly.

## Product review

The prompt required local Three.js dependencies, all executable source, startup
instructions, verification results, and no black screen or unhandled console
errors.

### Missing executable dependencies

`js/main.js` imports:

```text
../vendor/three/three.module.min.js
../vendor/three/controls/OrbitControls.js
```

The delivered snapshot contains only five files and no `vendor/` directory. A
local static server returned HTTP 200 for `/`, but HTTP 404 for both imported
modules. Browser module loading therefore stops before application startup.

### Shader compile blocker

`js/shaders.js` uses `MAX_STEPS_LOOP` in the scene shader. The exported source
does not define that macro. A helper named `patchScene` could inject it, but
`js/main.js` constructs `sceneMat` directly from `FRAG_SCENE` and never calls
`patchScene`. Even with dependencies supplied later, the scene shader would not
compile as delivered.

### Missing required delivery material

There is no startup-instruction file and no product verification receipt. The
workspace has substantial HTML/CSS/JS source, but file count and byte count are
not evidence that the application runs.

## Additional evidence qualifications

- `monitor.log` is not a 30-second cadence. Gaps are commonly about 50–120
  seconds, including a recorded `alive=False` point. This does not erase the
  frame evidence, but the report must not claim strict 30-second monitoring.
- LangChain also produced duplicated `tool_callstool_calls` and `stopstop`
  metadata. These values were not misclassified as output limits, but they show
  that canonical normalization remains narrowly scoped to known incomplete
  reasons.
- The successful turn cost and token totals are supported by response frames;
  product quality is not.

## Final classification

```text
OUTPUT-LIMIT RECOVERY: PASS
RUNNER HEARTBEAT ISOLATION: PASS
BRIDGE TRANSPORT: PASS
AUTONOMOUS COMPLETION INTEGRITY: FAIL
PRODUCT: FAIL
OVERALL: FAIL
```

No provider retry, repair run, PR merge, branch deletion, or Agentic UI work is
authorized by this review.
