# Desktop Agent Instructions — one zero-provider stream-parity validation

**Updated:** 2026-08-25

**Branch:** `arena/01a03741-pulseairepo`

**Source to validate:** `b82381d36662e2f0dc9262bafafbedd8508318d6`

**Attempt-8 evidence:** `6586d7afab1558274353dd34256f1783503b83c1`

**Prior Windows validation evidence:** `6b8a90b40ff2b5a8244198957669a6e561b787a1`

> Exactly one deterministic validation of source `b82381d36662e2f0dc9262bafafbedd8508318d6` is authorized.
> No provider-backed run or probe is authorized. Do not run Test 5, call
> Sarvam or any other provider, expose/use a credential, modify preserved
> evidence, merge PR #9, delete branches, or begin Agentic UI work.

## Workspace and preconditions

Use only the existing correct repository folder:

```text
D:\pulseAIagent\PulseAIRepo
```

Do not create a second clone or generated Test-5 workspace. In particular, do
not recreate absent `C:\test5-ws-attempt5`.

1. Confirm the repository is on `arena/01a03741-pulseairepo` and clean.
2. Fetch and fast-forward that branch from origin.
3. Confirm `git rev-parse HEAD` is exactly
   `b82381d36662e2f0dc9262bafafbedd8508318d6`.
4. Record byte length and SHA-256 for every tracked file under
   `bench-results/test5-8-desktop/` before validation.
5. Create evidence only under
   `bench-results/test5-stream-parity-validation/`.
6. Ensure provider keys are unavailable to the validation process. Do not load
   the historical key from README or Git history.

If any precondition fails, record a STOP receipt, commit/push it, and stop. Do
not improvise a checkout, reset, clone, workspace, or provider probe.

## Authorized checks — run once

Capture commands, stdout, stderr, exit codes, start/end timestamps, Python and
PowerShell versions, and `git status --short` in the evidence directory.

1. Parse `scripts/run_test5_guarded.ps1` with the PowerShell parser without
   executing it.
2. Run `python scripts/generate_bridge_protocol.py --check`.
3. Run `python -m compileall -q` for these changed Python modules/directories:
   `src/llm/factory.py`, `src/graphs/chat_graph.py`, `src/graphs/gates.py`,
   `src/context/context_engine.py`, and `src/bridge/`.
4. Run this deterministic focused suite once:

```text
python -m pytest -q \
  src/tests/test_retry_proxy_stream_cleanup.py \
  src/tests/test_autonomous_runtime_contract.py \
  src/tests/test_bridge.py \
  src/tests/test_bridge_protocol_v2.py \
  src/tests/test_iteration_budget.py \
  src/tests/test_review_autopsy_fixes.py::test_d26_hashed_keys_match_builder_usage_ast \
  src/tests/test_test5_guarded_script.py
```

5. Run `git diff --check`.
6. Recompute the Attempt-8 tracked-file byte lengths and SHA-256 values and
   prove the before/after trees are identical.
7. Record that no bridge, app runtime, guarded Test-5 wrapper, connectivity
   probe, or provider-backed command was launched. Provider-call count must be
   exactly zero.

Do not rerun a failing command. Preserve the first result and report it.

## Required receipt and disposition

Write a machine-readable manifest plus a concise Markdown report containing:

- validated full source commit;
- each command and exit code;
- test pass/fail/skip counts and duration;
- parser, generator, compilation, and diff-check results;
- before/after Attempt-8 evidence hashes;
- provider-call count (`0` required);
- final verdict: `DETERMINISTIC_PASS` only if every check passed and evidence
  was unchanged, otherwise `DETERMINISTIC_FAIL`;
- explicit statement that this is not a live-runtime/product PASS and does not
  authorize Attempt 9 or PR merge.

Commit only the new validation evidence, push it to
`origin/arena/01a03741-pulseairepo`, report the commit hash, then STOP.

## Preserve exactly

```text
C:\test5-ws-attempt6
C:\test5-ws-attempt8
bench-results\test5-5\
bench-results\test5-6\
bench-results\test5-8-desktop\
bench-results\test5-8-postmortem-validation\
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
```

## Mandatory stop after the receipt

- No Test-5 run or connectivity probe.
- No provider traffic.
- No repeated deterministic validation.
- No edits to preserved evidence or generated products.
- No PR merge or branch deletion.
- No Agentic UI work.
