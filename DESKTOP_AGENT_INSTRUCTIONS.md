# Desktop Agent Instructions — STOP after stream-parity validation receipt

**Updated:** 2026-08-25

**Branch:** `arena/01a03741-pulseairepo`

**Implementation commit:** `b82381d36662e2f0dc9262bafafbedd8508318d6`

**Desktop evidence commit:** `503c1972884d6ee190aafb3d9fce7227ef255e84`

> The one authorized deterministic Windows validation has been consumed. No
> additional desktop command, rerun, provider-backed run, probe, or source edit
> is authorized. Do not run Test 5, call a provider, merge PR #9, delete
> branches, or begin Agentic UI work.

## Recorded desktop result

The committed receipt records:

- PowerShell parser: PASS;
- bridge protocol generator check: PASS;
- changed Python compilation: PASS;
- 42 pytest tests: PASS in 16.63 seconds with one warning;
- `git diff --check`: PASS;
- Attempt-8 Windows evidence bytes: identical before/after;
- provider calls: zero.

Arena independently verified:

- evidence commit parent is exactly `55111f4f8af7a2b8f9af8cab1f0e62b9ff00fb26`;
- implementation commit `b82381d3...` is an ancestor;
- the evidence commit contains only the new validation directory;
- all ten receipt-manifest entries match committed byte lengths and SHA-256;
- the before/after Attempt-8 receipt files are byte-identical;
- the committed Attempt-8 tree did not change.

## Independent qualification

The desktop receipt labels itself `DETERMINISTIC_PASS`, and every command it
records passed. However, its pytest log collected 42 tests from only these five
targets:

```text
src/tests/test_retry_proxy_stream_cleanup.py
src/tests/test_autonomous_runtime_contract.py
src/tests/test_bridge.py
src/tests/test_iteration_budget.py
src/tests/test_test5_guarded_script.py
```

The authorized handoff also required these two targets, which are absent from
the Windows pytest log:

```text
src/tests/test_bridge_protocol_v2.py
src/tests/test_review_autopsy_fixes.py::test_d26_hashed_keys_match_builder_usage_ast
```

Those omitted targets account for the difference between the expected 50 and
recorded 42 tests. They passed in Arena, but were not proven on Windows by this
receipt. The evidence also does not preserve the exact command lines/version
capture requested by the handoff. Therefore Arena records the independent
verdict as:

```text
RECORDED_CHECKS_PASS / REQUIRED_VALIDATION_INCOMPLETE
```

This is not evidence of a source regression, and it does not authorize a
rerun. The founder must separately authorize any missing-check-only Windows
follow-up.

## Preserve exactly

```text
C:\test5-ws-attempt6
C:\test5-ws-attempt8
bench-results\test5-5\
bench-results\test5-6\
bench-results\test5-8-desktop\
bench-results\test5-8-postmortem-validation\
bench-results\test5-stream-parity-validation\
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
```

`C:\test5-ws-attempt5` is absent and must not be recreated.

## Mandatory stop

- No deterministic rerun or missing-test follow-up without explicit founder
  authorization.
- No Test-5 run or connectivity probe.
- No provider traffic or credential access.
- No edits to preserved evidence.
- No PR merge or branch deletion.
- No Agentic UI work.
