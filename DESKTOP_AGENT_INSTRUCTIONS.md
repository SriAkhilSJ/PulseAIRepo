# Desktop Agent Instructions — STOP after OpenRouter Attempt 10

**Updated:** 2026-08-25

**Branch:** `arena/01a03741-pulseairepo`

**Attempt-10 evidence:** `e344bc00e6de2961a2695d4fc7cfa7401ad64c87`

> Attempt 10 consumed its one OpenRouter probe and one live turn. No desktop
> command, deterministic rerun, second probe, provider request, source edit,
> Test-5 attempt, PR merge, branch deletion, or Agentic UI work is authorized.

## Verified result

```text
Probe:          HTTP 200 in 2.70s
Model:          stealth/ox-alpha
Live requests:  1
Responses:      1
Finish reason:  lengthlength
Incomplete:     false (incorrect classification)
Content/tools:  0 / 0
Files:          0
Runner result:  OSError [Errno 22] Invalid argument
Verdict:        RUNTIME_FAIL / PRODUCT_FAIL
```

The endpoint saw one probe plus one live-turn request. No request 2 occurred.
No tool call existed and no file was delivered.

Arena independently verified the evidence-only commit scope, exact frame
sequence, all six manifest byte lengths/SHA-256 values, and zero delivered
files. The evidence does not include the required monitor log, full foreground
transcript, preserved-evidence comparison, or traceback. Therefore it supports
neither an active 30-second-inspection claim nor a causal claim that the
malformed finish reason itself raised the OSError.

The confirmed source boundary is that repeated output-limit metadata
`lengthlength` was classified as `incomplete: false`. No live retry is
permitted. Any repair/validation requires a new explicit founder instruction.

## Preserve exactly

```text
C:\test5-ws-attempt6
C:\test5-ws-attempt8
C:\test5-ws-attempt9
C:\test5-ws-attempt10
bench-results\test5-5\
bench-results\test5-6\
bench-results\test5-8-desktop\
bench-results\test5-stream-parity-validation\
bench-results\test5-stream-parity-validation-followup\
bench-results\test5-9-desktop\
bench-results\test5-10-desktop\
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
```

`C:\test5-ws-attempt5` remains absent and must not be recreated.

## Mandatory stop

- No OpenRouter/Sarvam/other provider traffic.
- No probe or retry.
- No evidence edits.
- No PR merge or branch deletion.
- No Agentic UI work.
- Wait for explicit founder authorization.
