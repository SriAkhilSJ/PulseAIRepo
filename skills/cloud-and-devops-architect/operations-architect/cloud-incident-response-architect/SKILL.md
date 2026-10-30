---
name: cloud-incident-response-architect
description: Architect-level incident response for cloud estates — severity and declaration, roles and communication, blast-radius containment (revoke, isolate, roll back), evidence preservation, and the post-incident design changes that prevent the next one. Use when systems break in production and the response itself must be engineered.
license: MIT
compatibility: Any cloud; paging, status pages, IAM revocation
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/operations-architect/cloud-incident-response-architect
  crusor-origin: original
  crusor-sources: "sre.google/sre-book/managing-incidents; aws.amazon.com/blogs/mt/aws-security-incident-response-guide; incident.io/blog"
  crusor-triggers: "incident response, on call, severity, postmortem, outage, rollback, containment, status page, escalation, runbook"
  crusor-verified-on: "2026-10-30"
---

# Cloud Incident Response Architect

An incident is **a coordination problem under uncertainty**. The technical fix is
usually simple; the reason it takes four hours is unclear roles and missing
information.

## When to use

- Designing on-call, alerting, and escalation.
- A security incident needs containment without destroying evidence.
- Post-incident review after a major outage.

## When NOT to use

- A known failure with an existing runbook — just execute it.
- Pre-launch risk planning → `reliability-architect`.

## Decision 1 — Roles

| Role | Owns |
|---|---|
| incident commander | decisions, priorities, declaring severity |
| communications lead | status page, stakeholders, updates at fixed cadence |
| operations lead | the actual mitigation work |
| scribe | timeline, decisions, hypotheses |
| subject experts | diagnosis in their area |

- One person can hold several roles in small teams — but the commander must not be
  the person typing commands.
- Handover protocol for long incidents: written summary, not a verbal chat.
- Relieving an exhausted responder is a decision, not a failure.

## Decision 2 — Severity and declaration

- Severity by user impact, defined precisely: S1 total outage, S2 major
  degradation, S3 partial, S4 internal.
- Anyone can declare; declaring is never punished. Waiting for permission is the
  expensive mistake.
- Page on symptoms, not causes; the commander decides severity, not the alert.
- Status page updates on a fixed cadence even when there is nothing new.

## Decision 3 — Containment

- Stop the bleeding before root cause: roll back, shift traffic, disable the
  feature flag, scale out.
- Security incidents: revoke credentials first, then investigate. Preserve logs
  and snapshots before cleanup.
- Isolate without destroying evidence: snapshot the instance, capture the process
  list, keep the network flow logs.
- Know in advance what you can turn off, and test those switches
  (`chaos-engineering-architect` game days).

## Decision 4 — Information

- One channel per incident; a shared timeline document that everyone can write to.
- Timestamps in one timezone, one format.
- Dashboards annotated at declaration so the timeline survives after the fact.
- "What changed recently?" is the first question: deploys, config, traffic,
  certificates, provider status.

## Decision 5 — Resolution and review

- Resolution = SLO restored and verified, not "it stopped paging".
- Post-incident review within five days, blameless, focused on system conditions.
- Outputs: timeline, contributing factors, what worked, action items with owners
  and dates.
- Action items are design changes (timeouts, alerts, runbooks, tests); a doc-only
  outcome means the review failed.
- Track action completion; publish it — that is how trust is rebuilt.

## Decision 6 — Preparedness

- Runbooks for the top 10 failure modes, each tested in a game day.
- On-call rotation with escalation and a documented response-time expectation.
- Tooling tested: paging, status page credentials, break-glass access.
- Practice a provider-wide outage scenario — many systems share one dependency.

## Failure modes at scale

- Nobody declares for 40 minutes because everyone assumed someone else would.
- Commander debugging instead of coordinating; no updates for two hours.
- Rollback attempted without knowing what changed; two more changes layered on top.
- Security incident: instance terminated before snapshotting.
- Post-incident actions assigned to nobody, all still open a quarter later.

## Verification receipts

1. Severity matrix with examples and declaration authority.
2. One incident replayed through the timeline: detection, declaration, mitigation.
3. Containment switches tested within the last quarter.
4. Post-incident actions tracked to closure with owners.
5. On-call contacts and escalation verified by a test page.
