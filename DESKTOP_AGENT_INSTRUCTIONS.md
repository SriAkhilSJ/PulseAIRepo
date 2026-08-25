# Desktop Agent Instructions — STOP after Test 5 Attempt 8

**Updated:** 2026-08-25

**Branch:** `arena/01a03741-pulseairepo`

**Evidence commit:** `6586d7afab1558274353dd34256f1783503b83c1`

> No provider-backed run, probe, or retry is authorized. Do not rerun Test 5,
> merge PR #9, delete branches, modify preserved evidence, or begin Agentic UI
> work. Only deterministic, zero-provider validation explicitly requested by
> Arena is allowed.

## Verified Attempt-8 result

- Run ID: `test5-8-desktop`
- Workspace: `C:\test5-ws-attempt8`
- Runtime: FAIL — stalled after first successful `write_file`
- Product: FAIL — sole HTML file is truncated mid-CSS and non-executable
- Provider requests: 1
- Tool calls: 1 (`write_file`, reported successful)
- Delivered files: 1 (`index.html`, 4,995 Windows bytes)
- Terminal frames: none (`turn_done=0`, `turn_failed=0`)
- Watchdog: killed after 613.5 idle seconds
- Human interventions: 0
- Runner outcome: missing because the wrapper killed the runner tree before it
  could write `outcome.json`

The repaired first request was correct: four messages (three system + one
human), 3,083 message characters, and exactly one 591-character `write_file`
schema. Sarvam followed that narrowed surface. Pulse then failed between
`tool_call_end` and request 2.

## Deterministic repair under review

Attempt 8 exposed that autonomous `progress_node` still initialized semantic
tool memory after the first tool result even though autonomous context does not
consume memory. Repairs now under Arena validation:

- skip semantic tool-memory recording in autonomous workspace sessions;
- disable optional long-term memory in the guarded Test-5 process;
- drain streaming async generators before closing the request event loop;
- write a fallback watchdog `outcome.json` on hard-cap/stall termination;
- include LLM/file/byte counts in every 30-second watchdog line.

These changes do **not** authorize Attempt 9.

## Preserve exactly

```text
C:\test5-ws-attempt5
C:\test5-ws-attempt6
C:\test5-ws-attempt8
bench-results\test5-5\
bench-results\test5-6\
bench-results\test5-8-desktop\
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
```

## Evidence caveats

The console itself contains 30-second watchdog output, but the manually created
`monitor-30s.jsonl` starts at +240 seconds and has only six grouped samples.
Do not claim that every interval was actively inspected.

Git normalized committed text evidence from CRLF to LF. Seven of eight manifest
hashes can be reconstructed by restoring CRLF; the mixed-line-ending console
transcript cannot be byte-verified after checkout. Do not alter the evidence to
hide this limitation.

## Mandatory stop

- No provider traffic.
- No Test-5 rerun.
- No product repair in the preserved workspace.
- No PR merge or branch deletion.
- No Agentic UI work.
- Wait for founder review and explicit authorization.
