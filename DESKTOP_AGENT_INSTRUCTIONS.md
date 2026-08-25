# Desktop Agent Instructions — STOP after Arena Test 5 Attempt 7

**Updated:** 2026-08-25

**Branch:** `arena/01a03741-pulseairepo`

**PR:** `https://github.com/SriAkhilSJ/PulseAIRepo/pull/9`

> No provider-backed run is currently authorized. Do not run or retry Test 5,
> including on the founder's desktop. Do not merge PR #9, delete branches, or
> begin Agentic UI work until the founder explicitly reviews Attempt 7.

## Attempt-7 result

The founder authorized one Arena run using `test5.py` and a separate empty
workspace. That authorization is consumed.

- Run ID: `test5-7-arena`
- Workspace: `/home/user/test5-workspace-attempt7`
- Evidence: `bench-results/test5-7-arena/`
- Result: `turn_failed`, `completed=false`
- Error: `Connection error.`
- Provider attempts recorded: 5 bounded transport retries
- Model/tool responses: 0
- Tool calls: 0
- Delivered files: 0
- Budget/no-delivery/operator stops: all false
- Safety requests: 0
- Human interventions: 0

The repaired request boundary was confirmed on all five identical attempts:

- model `sarvam-105b-conversations`;
- 3 messages / 2,770 content characters on Linux;
- one tool, exactly `write_file`;
- 591 tool-schema characters;
- SHA-256 `3692fdcac5be75f15c35440a55ce6030ebb815d87e9e58652b1dd299df81e52a`;
- no system role after the human task.

The connection failed before any model response. This run therefore validates
Pulse's repaired request construction but cannot grade Sarvam instruction
following or the requested product.

## Preserve

Do not alter or delete:

```text
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
C:\test5-ws-attempt5
C:\test5-ws-attempt6
bench-results\test5-5\
bench-results\test5-6\
```

## Stop rules

- No retry or connectivity probe.
- No desktop Attempt 7/8.
- No provider calls.
- No PR merge or branch deletion.
- No Agentic UI implementation.
