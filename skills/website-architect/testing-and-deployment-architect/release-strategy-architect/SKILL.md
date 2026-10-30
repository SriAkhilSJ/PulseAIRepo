---
name: release-strategy-architect
description: Architect-level release practice — small-batch delivery, feature flag and canary strategy, expand/contract database changes, rollback versus roll-forward decisions, and the versioning and communication that keep releases boring. Use when deciding how code reaches users.
license: MIT
compatibility: Any stack; feature flag service optional
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/testing-and-deployment-architect/release-strategy-architect
  crusor-origin: original
  crusor-sources: "12factor.net; martinfowler.com/articles/feature-toggles.html; sre.google/workbook/canarying-releases"
  crusor-triggers: "release strategy, feature flags, canary, blue green, rollback, rollout, deployment frequency, versioning"
  crusor-verified-on: "2026-10-30"
---

# Release Strategy Architect

A release is **a reversible step**, not an event. If it cannot be undone in one
action, it is not a release — it is a gamble.

## When to use

- Planning how changes reach users, or deploys feel risky.
- Adding flags, canaries, or multi-environment rollout.
- A rollback is impossible because a migration already ran.

## When NOT to use

- Choosing the pipeline stages themselves (see `ci-cd-architect`).

## Decision 1 — Small batches

- Deploy often and small; batch size is the strongest predictor of incident
  duration.
- Separate **deploy** (code present, switched off) from **release** (users
  affected).
- A change that needs a maintenance window is a design that skipped this rule.

## Decision 2 — Flags

| Flag type | Lifetime | Owner |
|---|---|---|
| release flag | days | the team shipping |
| experiment flag | weeks | product |
| ops/kill switch | permanent | on-call |
| permission flag | permanent | entitlements (not a flag) |

- Every flag has an owner and a removal date; stale flags are debt with a blast
  radius.
- Flag evaluation must be fast and fail-safe: on error, serve the last known
  good state.
- Never use flags to choose a database schema shape you cannot migrate.

## Decision 3 — Rollout mechanics

| Strategy | Use when |
|---|---|
| all-at-once | low risk, easy rollback, non-critical internal services |
| canary (1% → 10% → 50% → 100%) | user-facing changes with metrics to judge |
| blue/green | need instant cutover and instant revert |
| ring/cohort | enterprise customers and staged exposure |

- Canary needs a judge: error rate, latency, business metric — defined before
  rollout, not eyeballed.
- Automated abort on SLO burn; a human watching a graph is not a control.

## Decision 4 — Data is the hard part

- Schema changes are expand/contract: add compatible structure, dual-write,
  backfill, switch reads, remove old — across releases.
- Never drop or rename a column in the same release that stops using it.
- Backfills are batched, idempotent, resumable, and monitored.
- "Rollback" of a data migration is a forward migration, not a restore from
  backup — plan it.

## Decision 5 — Rollback vs roll-forward

- Decide the trigger in advance: error rate above X for Y minutes → revert.
- Rollback must not depend on a schema reversal; that is why data changes ship
  separately.
- Roll-forward is acceptable when the fix is small and known; document which
  path you chose and why.
- Post-release verification: smoke journey plus the metric that justified the
  release.

## Decision 6 — Communication

- Version numbers or changelogs for anything external; internal services use
  commit-based deployment records.
- Release notes name user-visible changes, not commits.
- Announce risky releases in the team channel with the rollback command in the
  message.

## Failure modes at scale

- One deploy containing 40 changes, one of which breaks the site — bisecting in
  production.
- 300 permanently-on flags; nobody knows which code is live.
- A migration dropped a column, and rollback means restoring a backup.
- Canary deployed to 1% but the metric chosen cannot detect the bug.
- Friday deploy with the one person who knows the rollback on holiday.

## Verification receipts

1. Deployment frequency and change failure rate over the last quarter.
2. Flag inventory with owner and expiry; count of flags older than 90 days.
3. Canary run with an automated abort demonstrated.
4. Migration plan for a live table (expand/contract, separately deployable).
5. Rollback drill executed and timed.
