---
name: ci-cd-architect
description: Architect-level CI/CD pipeline design — stage ordering and parallelisation, caching that is safe, secret and permission scoping, artefact promotion instead of rebuilding, and the gates that make a red pipeline mean something. Use when designing or repairing a build and deploy pipeline.
license: MIT
compatibility: GitHub Actions / GitLab CI / Buildkite or equivalent
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/testing-and-deployment-architect/ci-cd-architect
  crusor-origin: original
  crusor-sources: "docs.github.com/actions; 12factor.net/build-release-run; slsa.dev"
  crusor-triggers: "ci cd, pipeline, github actions, build pipeline, deployment pipeline, artefacts, caching ci, gates"
  crusor-verified-on: "2026-10-30"
---

# CI/CD Architect

A pipeline is **the contract between "merged" and "in production"**. If it can be
skipped, it is a suggestion.

## When to use

- Setting up CI for a new repo.
- Pipelines are slow, flaky, or bypassed with admin merges.
- Deploys need multiple manual steps or a specific person.

## When NOT to use

- Deciding what the tests should assert (see `test-strategy-architect`).

## Decision 1 — Stage order

```
1. guard     path filters, required checks, PR metadata
2. fast      lint · typecheck · unit tests          (< 3 min)
3. build     compile/bundle, produce one artefact   (~5 min)
4. verify    integration · contract · e2e on the artefact
5. deploy    staging (auto) → production (approved or flagged)
6. confirm   smoke test, error rate, rollback ready
```

- Cheap failures first: never spend 12 minutes building before linting.
- Independent jobs run in parallel; dependencies are explicit.
- The artefact built in stage 3 is the one deployed — no rebuilds downstream.

## Decision 2 — Determinism and caching

- `--frozen-lockfile`/`npm ci`; no version resolution at build time.
- Cache dependency downloads and build outputs keyed on the lockfile hash — never
  cache across an environment boundary in ways that leak.
- Pin runner images and tool versions; `latest` in CI is a surprise release.
- Timeouts on every job; a hung job must fail, not occupy a runner for six hours.

## Decision 3 — Permissions and secrets

- Default token permissions read-only; grant per-job write scopes explicitly.
- No secrets exposed to fork PRs; never `pull_request_target` with checkout of
  PR code.
- Third-party actions pinned to a commit SHA.
- Deploy credentials in the platform secret store, scoped per environment.
- Log masking on; never echo an environment variable wholesale.

## Decision 4 — Gates that mean something

- Required checks are enforced by branch protection, not convention.
- A flaky gate is fixed or removed within a sprint; retrying to green is a
  data-loss event for trust.
- Security gates: dependency audit, secret scan, SAST — blocking on high
  severity.
- Coverage and performance budgets gate only what the team is willing to fix.

## Decision 5 — Deploy mechanics

- One-click and fully automated for the happy path; approvals only for
  production risk, not for routine.
- Deploy is idempotent; re-running it is safe.
- Rollback is a first-class job in the pipeline, one step, tested monthly.
- Environments promoted in order; production never deploys an artefact that did
  not pass staging.

## Decision 6 — Observability of the pipeline itself

- Every deploy records: artefact digest, commit, initiator, duration.
- Failure notifications go to the owning team, not a firehose channel.
- Pipeline duration tracked over time; creeping CI is an invisible tax.

## Failure modes at scale

- 45-minute pipeline → developers batch changes → deploys get riskier.
- Actions pinned to `@v3`, run with a token that can write to the org.
- Staging deploys a rebuild, production deploys a different rebuild.
- Required check removed during an outage and never restored.
- Rollback "documented in the wiki" and never executed.

## Verification receipts

1. Stage timing breakdown; total under the team's target.
2. One artefact hash promoted across environments (same digest).
3. Permission review: default read-only, per-job escalation, SHA-pinned actions.
4. Rollback job executed in a drill with a timestamp.
5. Red-pipeline test: a deliberate failing check blocks merge.
