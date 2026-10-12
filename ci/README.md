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
