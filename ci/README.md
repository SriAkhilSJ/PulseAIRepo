# CI configuration (staged)

`agent-core.yml` is the GitHub Actions workflow for the agent-core suite. It
lives here instead of `.github/workflows/` because the GitHub App that created
the audit-fix commit is not granted the `workflows` permission, so a push
touching a workflow file is rejected:

```
! [remote rejected] ... refusing to allow a GitHub App to create or update
  workflow `.github/workflows/agent-core.yml` without `workflows` permission
```

## Install it (one command, from a credential that can push workflows)

```bash
mkdir -p .github/workflows
cp ci/agent-core.yml .github/workflows/agent-core.yml
git add .github/workflows/agent-core.yml
git commit -m "ci(agent-core): run the hermetic suite"
git push
```

Alternatively, reconnect GitHub in Arena with the **Workflows** permission and
ask the agent to move the file — no manual step needed.

## What it runs

- **`agent-core`** (blocking): `bash scripts/run_tests.sh src/tests` on Python
  3.11 with the full dependency set (tree-sitter grammars, Pillow) plus
  `pyright`, minus the two desktop-build-output parity modules (see the comment
  in the workflow; they run in the informational job below).
- **`desktop-panel-parity`** (informational, `continue-on-error`): the pins that
  compare the tracked `desktop/vscode/out/**` build output against the current
  TypeScript sources. Fixing those needs a desktop rebuild, not an agent-core
  change.

## Bounded live-run monitoring

Controlled headless bridge runs use `scripts/run_bridge_turn.py`. Its local `outcome.json` keeps bounded request/tool status and timing receipts. In GitHub Actions, the runner publishes separate summary, request, and tool notices as independently parseable JSON capped at 3,500 characters each.

The publisher allowlists receipt fields and omits prompts, tool arguments, commands, file bodies, IDs, and full results. Configured secret values and secret-like result fragments are redacted before publication. This replaces the earlier single-annotation shape that GitHub truncated at 4,096 characters.

These notices are monitoring, not acceptance. Workflow success must still come from immutable evaluator-owned checks, and a failed check must remain failed regardless of what the agent says. The new multi-annotation path is provider-free tested but still needs retrieval confirmation in a future explicitly authorized Actions run. See [`../core.md`](../core.md) and [`../docs/CRUSOR_FULLSTACK_BENCHMARK.md`](../docs/CRUSOR_FULLSTACK_BENCHMARK.md).
