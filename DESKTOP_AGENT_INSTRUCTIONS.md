# Desktop Agent Instructions — authorized missing-check-only follow-up

**Updated:** 2026-08-25

**Branch:** `arena/01a03741-pulseairepo`

**Implementation commit:** `b82381d36662e2f0dc9262bafafbedd8508318d6`

**Original Windows evidence:** `503c1972884d6ee190aafb3d9fce7227ef255e84`

> The founder authorized exactly one zero-provider Windows run of the two
> targets omitted from the 42-test receipt. Do not repeat any of the 42 passing
> tests. Do not run Test 5, launch the app/bridge, call a provider, retrieve a
> credential, merge PR #9, delete branches, or begin Agentic UI work.

## Workspace and preconditions

Use only the existing correct repository:

```text
D:\pulseAIagent\PulseAIRepo
```

1. Confirm the existing checkout is clean and on
   `arena/01a03741-pulseairepo`.
2. Fetch and fast-forward it to
   `origin/arena/01a03741-pulseairepo`. Do not detach HEAD, reset, create a
   branch, or create another clone.
3. Record the full validation-parent commit and prove:

   ```text
   git rev-parse HEAD == git rev-parse origin/arena/01a03741-pulseairepo
   git merge-base --is-ancestor b82381d36662e2f0dc9262bafafbedd8508318d6 HEAD
   git merge-base --is-ancestor 503c1972884d6ee190aafb3d9fce7227ef255e84 HEAD
   ```

4. Create evidence only under:

   ```text
   bench-results/test5-stream-parity-validation-followup/
   ```

5. Ensure provider credentials are unavailable to the test process and network
   provider traffic is blocked. Do not load `.env`, README history, or any
   historical key.

If a precondition fails, write and commit a STOP receipt in the new follow-up
directory, push it, and stop. Do not improvise.

## Authorized command — run exactly once

First record the literal command, Python version, pytest version, start time,
working directory, branch, parent commit, and credential/network-block state in
the new evidence directory.

Run this as **one command line** so PowerShell continuation syntax cannot omit a
target:

```text
python -m pytest -q src/tests/test_bridge_protocol_v2.py src/tests/test_review_autopsy_fixes.py::test_d26_hashed_keys_match_builder_usage_ast
```

Expected collection is exactly **8 tests**: seven protocol tests plus one D26
AST test. Save complete stdout/stderr and the exit code. Do not rerun if the
count differs or a test fails; preserve the first result.

Then run `git diff --check` once and capture its output/exit code. This static
check is authorized only to prove the new receipt introduces no whitespace
error; it is not permission to rerun any prior test.

Provider-call count must remain exactly zero.

## Receipt requirements

Create a machine-readable summary and receipt manifest containing:

- validation-parent and implementation commits;
- exact literal pytest command;
- Python and pytest versions;
- timestamps and duration;
- collected/pass/fail/skip/warning counts;
- pytest and diff-check exit codes;
- provider-call count (`0` required);
- SHA-256 and byte length for every receipt/log file except the manifest itself;
- verdict `MISSING_CHECKS_PASS` only if exactly 8 tests passed, both exit codes
  are zero, and provider calls are zero; otherwise `MISSING_CHECKS_FAIL`;
- explicit statement that this is not a live-runtime/product PASS and does not
  authorize Attempt 9 or PR merge.

## Commit and push — mandatory

Confirm only the new follow-up evidence directory is modified, then commit and
push it on the existing branch:

```text
git add bench-results/test5-stream-parity-validation-followup/
git commit -m "evidence: complete Windows stream parity checks"
git push origin HEAD:arena/01a03741-pulseairepo
```

Report the full evidence commit hash and then STOP. If commit/push fails,
preserve the exact error and stop. Never force-push or switch branches.

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

## Mandatory stop after receipt

- No repeat of the 42 passing tests.
- No repeat of these 8 follow-up tests.
- No provider traffic, Test 5, or Attempt 9.
- No edits to preserved evidence.
- No PR merge or branch deletion.
- No Agentic UI work.
