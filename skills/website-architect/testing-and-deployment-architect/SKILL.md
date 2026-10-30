---
name: testing-and-deployment-architect
description: Architect-level quality-to-production direction — the test portfolio and what each layer is allowed to assert, the pipeline that gates merges, container and environment topology, observability as a design requirement, and the release and incident practices that make shipping reversible. Use before any specific CI, container or SRE skill.
license: MIT
compatibility: Any stack; any CI provider
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/testing-and-deployment-architect
  crusor-origin: original
  crusor-sources: "martinfowler.com/articles/practical-test-pyramid.html; 12factor.net; sre.google/sre-book"
  crusor-triggers: "deployment, release, ci cd, pipeline, testing strategy, environments, rollout, sre"
  crusor-verified-on: "2026-10-30"
---

# Testing & Deployment Architect

Shipping is a **system property**, not a button. The architecture decides how
fast a change can reach a user, and how fast it can be taken back.

## Leaf map

| Need | Skill |
|---|---|
| how much of which test, and where | `test-strategy-architect` |
| the pipeline that gates merges | `ci-cd-architect` |
| images, environments, runtime config | `containerization-architect` |
| logs, metrics, traces, alerting | `observability-architect` |
| rollout, flags, rollback | `release-strategy-architect` |
| when it breaks at 3 a.m. | `incident-response-architect` |

## Decision 1 — The test portfolio

| Layer | Count | Duration | Asserts |
|---|---|---|---|
| unit | many | ms | rules |
| integration | some | seconds | boundaries (DB, queue, HTTP) |
| e2e | few | minutes | critical journeys |
| contract | per consumer | seconds | API compatibility |
| non-functional | continuous | varies | performance, a11y, security gates |

- A bug caught by a cheaper layer must not get an expensive test.
- Coverage is a diagnostic, never a target.
- Flaky is a failure state: quarantine, fix or delete within a sprint.

## Decision 2 — One pipeline, same for everyone

- Local commands and CI run the same scripts; CI adds parallelism, not different
  behaviour.
- Fast gates first (lint, types, unit) → slow gates (integration, e2e) after.
- A red pipeline is the team's top priority; a permanently red gate is a deleted
  gate in practice.
- No secrets on fork PRs; artefacts retained with an expiry.

## Decision 3 — Environments

```
local → preview (per PR) → staging (prod-like) → production
```

- Preview environments prove a change before merge.
- Staging mirrors production topology and config shape; different data.
- Configuration comes from the environment, never from the build.
- One artefact promoted across environments — never rebuilt per stage.

## Decision 4 — Observability is a requirement

- Every service emits structured logs, metrics and traces from day one; adding
  it after an incident is too late.
- A request has a correlation id from edge to database.
- Alerts are on symptoms users feel (error rate, latency, saturation), not on
  every CPU graph.
- Dashboards exist before launch, not after the first outage.

## Decision 5 — Reversibility

- Deploys are small and frequent; a big-bang release is a design failure.
- Every change ships behind a flag or can be rolled back in one step.
- Rollback is tested — an untested rollback path is a hope.
- Database changes are expand/contract so old and new code run simultaneously.

## Decision 6 — The human loop

- Runbooks for the top five failure modes; on-call knows where they are.
- Incidents get a blameless review with actions and owners.
- Post-deploy verification: smoke test, error rate, and a check the feature
  actually works.

## Failure modes at scale

- A 40-minute pipeline everyone bypasses with admin merge.
- Staging that differs from production in exactly the ways that matter.
- Deploying on Friday with no rollback plan.
- Logs that exist but cannot answer "which request failed and why".
- Postmortems written and never read.

## Verification receipts

1. Pipeline duration and stage breakdown; merge blocked on red.
2. Test portfolio counts per layer and flake rate over 50 runs.
3. One artefact promoted to production, provenance visible.
4. Alert inventory mapped to user-visible symptoms.
5. Rollback executed in a drill within the target window.
