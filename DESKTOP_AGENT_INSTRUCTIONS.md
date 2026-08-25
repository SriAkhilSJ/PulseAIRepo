# Desktop Agent Instructions — STOP after 50-test deterministic PASS

**Updated:** 2026-08-25

**Branch:** `arena/01a03741-pulseairepo`

**Implementation commit:** `b82381d36662e2f0dc9262bafafbedd8508318d6`

**Initial Windows evidence:** `503c1972884d6ee190aafb3d9fce7227ef255e84`

**Follow-up Windows evidence:** `496591a10e93b13d32065b3ac04d74f89d9fecde`

> All authorized deterministic Windows work is complete. No additional desktop
> command, test, rerun, provider-backed run, probe, or source edit is authorized.
> Do not run Test 5, call a provider, access a credential, merge PR #9, delete
> branches, or begin Agentic UI work.

## Verified result

The two committed Windows receipts jointly prove:

```text
42 initial tests passed
+8 omitted-target follow-up tests passed
=50 focused tests passed
provider calls: 0
verdict: DETERMINISTIC_PASS
```

The follow-up specifically proves:

- `src/tests/test_bridge_protocol_v2.py`: 7/7 passed;
- `test_d26_hashed_keys_match_builder_usage_ast`: 1/1 passed;
- total: 8 collected, 8 passed in 2.83 seconds;
- Windows Python 3.14.4;
- provider calls: zero.

Arena independently verified:

- evidence commit parent and implementation ancestry;
- evidence-only commit scope;
- exact pytest targets, count, output, and duration;
- all three follow-up receipt entries against committed byte lengths/SHA-256;
- all ten initial receipt entries against committed byte lengths/SHA-256;
- initial Attempt-8 before/after evidence identity and unchanged committed tree.

This is a deterministic source-contract PASS only. It is not a live runtime or
product PASS and does not authorize Attempt 9 or PR merge.

## Preserve exactly

```text
C:\test5-ws-attempt6
C:\test5-ws-attempt8
bench-results\test5-5\
bench-results\test5-6\
bench-results\test5-8-desktop\
bench-results\test5-8-postmortem-validation\
bench-results\test5-stream-parity-validation\
bench-results\test5-stream-parity-validation-followup\
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
```

`C:\test5-ws-attempt5` is absent and must not be recreated.

## Mandatory stop

- No deterministic reruns.
- No Test-5 run, Attempt 9, or connectivity probe.
- No provider traffic or credential access.
- No edits to preserved evidence.
- No PR merge or branch deletion.
- No Agentic UI work.
- Wait for explicit founder authorization and a new committed instruction file.
