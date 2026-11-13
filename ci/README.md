# CI configuration

`agent-core.yml` **now lives at `.github/workflows/agent-core.yml`** (moved there
by T-18). This directory is kept for the history of why it was staged here.

It previously lived in `ci/` because the GitHub App that created the audit-fix
commit is not granted the `workflows` permission, so a push touching a workflow
file is rejected:

```
! [remote rejected] ... refusing to allow a GitHub App to create or update
  workflow `.github/workflows/agent-core.yml` without `workflows` permission
```

**If a push is rejected with that message**, the relocation did not reach GitHub:
reconnect with the **Workflows** permission and push again. Until that happens,
no GitHub-hosted run of this workflow exists, and a local run is not a substitute.

## What it runs

- **`agent-core`** (blocking): `bash scripts/run_tests.sh src/tests` on Python
  3.11 with the full dependency set (tree-sitter grammars, Pillow) plus `pyright`.
  As of T-18 it runs the **entire** suite, including the two desktop parity
  modules that were previously excluded and parked in a non-blocking job.
  Nothing in the workflow is allowed to conceal a failure: no `continue-on-error`,
  no `|| true`, no ignored directories.

## Bounded live-run monitoring

Controlled headless bridge runs use `scripts/run_bridge_turn.py`. Its local `outcome.json` keeps bounded request/tool status and timing receipts. In GitHub Actions, the runner publishes separate summary, request, and tool notices as independently parseable JSON capped at 3,500 characters each.

The publisher allowlists receipt fields and omits prompts, tool arguments, commands, file bodies, IDs, and full results. Configured secret values and secret-like result fragments are redacted before publication. This replaces the earlier single-annotation shape that GitHub truncated at 4,096 characters.

These notices are monitoring, not acceptance. Workflow success must still come from immutable evaluator-owned checks, and a failed check must remain failed regardless of what the agent says. The new multi-annotation path is provider-free tested but still needs retrieval confirmation in a future explicitly authorized Actions run. See [`../core.md`](../core.md) and [`../docs/CRUSOR_FULLSTACK_BENCHMARK.md`](../docs/CRUSOR_FULLSTACK_BENCHMARK.md).
