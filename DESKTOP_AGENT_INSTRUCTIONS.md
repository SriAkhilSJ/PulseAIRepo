# Desktop Agent Instructions — STOP after Attempt 11

**Updated:** 2026-08-25

**Required branch:** `arena/01a03741-pulseairepo`

**Attempt-11 evidence commit:** `989ab85ed36ca5985864cf1b349f996c6111a75c`

**Open PR:** #9 — do not merge

> Attempt 11 consumed its one OpenRouter probe and one live turn. No further
> desktop command, deterministic rerun, provider request, source repair, cap
> increase, PR merge, branch deletion, or Agentic UI work is authorized.

## Independent verdict

```text
Probe:                          PASS (HTTP 200, 2.65s)
Output-limit recovery:          PASS
Runner heartbeat isolation:     PASS
Bridge request/response liveness: PASS (13/13)
Autonomous completion integrity: FAIL
Product:                         FAIL
Overall:                         FAIL
```

The first three live responses exposed raw `lengthlength`, canonical `length`,
and `incomplete=true`. Request 4 then produced the first complete tool call.
Repeated console `OSError 22` events were preserved in the fallback log while
the bridge continued to `turn_done`. These are genuine live passes for the
narrow deterministic repairs.

They are not an end-to-end PASS. The graph emitted `completed=true` without a
successful verification receipt. Its final message said it would inspect next.
The delivered application imports two missing local Three.js files, and its
scene shader uses `MAX_STEPS_LOOP` without injecting the macro. It cannot run as
delivered.

Full independent review:

```text
docs/TEST5_ATTEMPT11_REVIEW.md
```

## Evidence to preserve

```text
C:\test5-ws-attempt11
bench-results\test5-11-desktop\
989ab85ed36ca5985864cf1b349f996c6111a75c
```

Also preserve all Attempt-5 through Attempt-10 workspaces and evidence already
listed in repository history. Do not alter or “complete” the Attempt-11 snapshot;
it is graded evidence.

## Evidence qualifications

- Eight tool starts have seven paired tool ends. The unmatched terminal call
  encountered a Windows `cp1252` writer-thread `UnicodeEncodeError`.
- No browser verification tool ran.
- The monitoring log does not demonstrate a strict 30-second cadence; observed
  gaps are commonly around 50–120 seconds.
- All 11 committed SHA-256 entries match their evidence files.

## Mandatory stop

- No provider probe, retry, fallback, or live turn.
- No evidence edits or generated-workspace repair.
- No source repair unless separately authorized.
- No PR merge or branch deletion.
- No Agentic UI work.
- Wait for explicit founder authorization.

```text
STOPPED — Attempt 11 independently reviewed; overall FAIL
```
