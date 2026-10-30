---
name: gitops-architect
description: Architect-level GitOps design — repository structure for desired state, reconciliation loops and their ownership, promotion between environments by commit, drift and prune policies, secrets without committing them, and the rollback that is a revert. Use when cluster or infrastructure state must be driven from git.
license: MIT
compatibility: Argo CD, Flux, Terraform+CI; any reconciler
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/platform-architect/gitops-architect
  crusor-origin: original
  crusor-sources: "argo-cd.readthedocs.io; fluxcd.io/docs; opengitops.dev"
  crusor-triggers: "gitops, argocd, argo cd, flux, reconciliation, drift, promote environment, desired state, app of apps, sync policy"
  crusor-verified-on: "2026-10-30"
---

# GitOps Architect

GitOps means **git is the only way desired state changes**, and a controller
continuously reconciles reality to it. Everything else is CI with a different name.

## When to use

- Kubernetes fleets or cloud infrastructure needing auditable change history.
- Multiple clusters/environments with promotion.
- A team wants rollback to be `git revert`.

## When NOT to use

- Ad-hoc, single-environment scripts.
- You need imperative, one-off operations — those are break-glass, not GitOps.

## Decision 1 — Repository layout

| Layout | Structure | Trade-off |
|---|---|---|
| env-per-directory | `clusters/prod/…` | simple, easy promotion |
| app-of-apps | one root app spawning children | scalable, harder to reason about |
| separate config repo | app code repo + deploy repo | clean separation, two PRs |
| monorepo | everything | simple, big blast radius |

- Track **what runs where**, not just what exists: one directory per
  cluster/environment, with the app set and version pins.
- Application source (image build) and deployment config can be separate repos;
  the deployment repo is the source of truth for what is running.
- Promotion = PR that changes an image tag or a version; never a manual `kubectl
  set image`.

## Decision 2 — Reconciliation

- Controller runs in-cluster with read access to git and write access to the
  cluster; it is the only writer.
- Sync policy: automated with `prune` and `selfHeal` in non-prod; automated with
  prune but manual approval for production criticality tiers.
- Health assessment must mean something: a Deployment "healthy" with zero ready
  pods is not healthy.
- Reconcile interval short enough to matter (minutes), and webhooks for fast
  feedback.
- Drift is a first-class alert; a manual change is reverted, not tolerated.

## Decision 3 — Secrets

- Never plaintext in git. Options: Sealed Secrets, SOPS with cloud KMS, external
  secrets operator referencing a secret manager.
- The reconciliation loop must not need long-lived cluster credentials beyond its
  scoped role.
- Rotate the controller's git credentials; use deploy keys with read-only scope.
- Audit: the secret's source of truth is the manager, not the encrypted blob.

## Decision 4 — Rollback and promotion

- Rollback = revert the commit; the controller converges. Keep commits small and
  single-purpose so a revert is surgical.
- Prefer promotion gates: staging sync → smoke tests → PR to prod.
- Image tags immutable and digest-pinned; `latest` breaks the whole model.
- Keep the previous known-good state committed and identifiable (tags/releases).

## Decision 5 — Scale and ownership

- One controller per cluster group or a hub-per-tenant model; avoid one controller
  managing everything by hand.
- ApplicationSets/Flux generators for fleet-wide rollout, but keep per-cluster
  overrides explicit.
- Ownership boundaries: platform team owns controllers and base charts; app teams
  own their values and versions.
- Alert on out-of-sync beyond N minutes — silent drift is the failure mode GitOps
  is supposed to kill.

## Failure modes at scale

- `kubectl edit` in production, reverted within minutes, incident closed without
  learning why the change was needed.
- Secrets committed "encrypted" with the key in the same repo.
- One controller, 400 apps, no ownership; a broken base chart breaks everything.
- Self-heal enabled on a stateful workload and it keeps recreating a failing pod.
- Rollback attempted by redeploying an old image tag that was overwritten.

## Verification receipts

1. Repo layout diagram with environment promotion path.
2. Drift drill: manual change made, controller reverted it, alert fired.
3. Secret path documented and exercised (rotation).
4. Rollback by revert performed end to end.
5. Out-of-sync alert configured with the target threshold.
