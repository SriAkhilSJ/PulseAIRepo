# Desktop Agent Instructions — STOP after Attempt-8 validation

**Updated:** 2026-08-25

**Branch:** `arena/01a03741-pulseairepo`

**Attempt-8 evidence:** `6586d7afab1558274353dd34256f1783503b83c1`

**Windows validation evidence:** `6b8a90b40ff2b5a8244198957669a6e561b787a1`

> No provider-backed run, probe, deterministic rerun, or additional desktop
> work is authorized. Do not run Test 5, call Sarvam, modify preserved evidence,
> merge PR #9, delete branches, or begin Agentic UI work.

## Verified validation result

- Existing Windows clone: `D:\pulseAIagent\PulseAIRepo`
- Validated source: `8b1de14c`
- PowerShell parser: PASS
- Guarded-wrapper static contract: PASS
- Focused tests: 72 passed on Windows Python 3.14.4
- Python compilation: PASS
- `git diff --check`: PASS
- Attempt-8 evidence tree before/after: byte-identical
- Provider calls: zero
- Validation receipt manifest: all nine committed entries independently
  SHA-256 verified after checkout

These results validate the deterministic patch mechanics. They do not prove
Hermes-equivalent streaming completeness and do not authorize Attempt 9.

## Preserve exactly

```text
C:\test5-ws-attempt5
C:\test5-ws-attempt6
C:\test5-ws-attempt8
bench-results\test5-5\
bench-results\test5-6\
bench-results\test5-8-desktop\
bench-results\test5-8-postmortem-validation\
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
```

## Mandatory stop

- No Test-5 run or connectivity probe.
- No provider traffic.
- No repeated validation command.
- No edits to generated products or evidence.
- No PR merge or branch deletion.
- No Agentic UI work.
- Wait for explicit founder authorization and a completed Hermes stream-parity
  repair before any future live attempt.
