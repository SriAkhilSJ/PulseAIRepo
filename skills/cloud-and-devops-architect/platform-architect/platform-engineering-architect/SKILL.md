---
name: platform-engineering-architect
description: Architect-level internal developer platform design — golden paths over mandates, what belongs on the platform versus in product teams, self-service provisioning, paved-road templates, and the adoption and support model that decides whether a platform reduces or adds friction. Use when building shared tooling, templates, or a platform team.
license: MIT
compatibility: Backstage, Crossplane, Terraform modules, Kubernetes, CI templates
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/platform-architect/platform-engineering-architect
  crusor-origin: original
  crusor-sources: "backstage.io/docs; crossplane.io/docs; teamtopologies.com"
  crusor-triggers: "internal developer platform, idp, platform team, golden path, self service, backstage, developer experience, paved road, template, scaffolding"
  crusor-verified-on: "2026-10-30"
---

# Platform Engineering Architect

A platform is **a product whose users are engineers**. It succeeds when teams
choose it, which means it must be faster than doing it themselves — not mandated.

## When to use

- Several teams repeat the same infrastructure and delivery work.
- Onboarding a service takes weeks of tribal knowledge.
- Standards exist on paper but are not in the default path.

## When NOT to use

- One or two teams — a shared repo of modules is enough.
- The real problem is a broken process; a portal will not fix an approval chain.

## Decision 1 — Scope

| On the platform | In product teams |
|---|---|
| cloud accounts, network, base IaC | service-specific resources |
| CI/CD templates and runners | pipeline logic for their service |
| registry, secret store, observability | dashboards and alerts they own |
| service catalogue, docs, scaffolding | domain documentation |
| policy and guardrails | compliance decisions inside the guardrail |

- The platform owns the **paved road**, not the destination: teams can leave it
  with a documented escape hatch and a cost.
- Anything the platform owns needs an SLO and an on-call rotation.

## Decision 2 — Golden paths

- Templates that produce a working deployable service end to end: repo, pipeline,
  IaC, dashboards, alerts, docs, runbook.
- One template per stack type (service, batch job, data pipeline), versioned.
- Generated code is owned by the team after creation — the platform does not
  update their service.
- Golden path must be the fastest route: if manual setup is quicker, nobody uses it.

## Decision 3 — Self-service

- Requests become API calls: a new environment, a database, a namespace — approved
  by policy, not by a human ticket.
- Provisioning via Crossplane/Terraform pipelines with quota and cost attached at
  request time.
- Every self-service action is auditable and reversible.
- Quotas are visible up front; discovering a limit at deploy time is a support
  ticket.

## Decision 4 — Adoption

- Measure: time to first deploy for a new service, change failure rate per team,
  support ticket volume, template adoption percentage.
- Opt-in first; mandate only for compliance-critical controls.
- Internal marketing is part of the job: docs, demos, office hours.
- Deprecation policy for platform components with migration support.

## Decision 5 — Support and evolution

- A platform team has its own backlog, SLOs, and severity levels.
- When a team needs something the platform does not offer, the default is to add
  it to the platform, not to fork.
- Backstage (or equivalent) is a UI over real APIs — a catalogue that lies is
  worse than none.
- Every onboarding friction fixed is a metric, not a favour.

## Failure modes at scale

- Platform built from mandates; teams route around it and shadow IT returns.
- Templates that generate a service nobody can debug — magic over clarity.
- Catalogue with 400 entries, half stale, owners unknown.
- Self-service provisioning with no quota; one team takes the whole cloud budget.
- Platform team becomes a ticket queue for routine changes.

## Verification receipts

1. Scope table: platform-owned versus team-owned, with owners named.
2. Template used to create a service and deploy it end to end, timed.
3. Self-service request executed with policy approval and audit record.
4. Adoption and time-to-first-deploy metrics for the last quarter.
5. Catalogue entries with current owners and validated freshness.
