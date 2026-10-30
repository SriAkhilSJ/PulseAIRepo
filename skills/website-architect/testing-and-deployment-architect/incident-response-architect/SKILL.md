---
name: incident-response-architect
description: Architect-level incident practice — severity and role model, the first-15-minutes procedure, mitigation before diagnosis, communication cadence, blameless postmortems with owned actions, and the design changes that prevent the same class of outage repeating. Use when an outage happens, or when preparing for one.
license: MIT
compatibility: Any team and stack
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/testing-and-deployment-architect/incident-response-architect
  crusor-origin: original
  crusor-sources: "sre.google/sre-book/managing-incidents; sre.google/sre-book/postmortem-culture; incident.io/blog"
  crusor-triggers: "incident, outage, postmortem, on call, sev1, rollback during incident, runbook, blameless review"
  crusor-verified-on: "2026-10-30"
---

# Incident Response Architect

An incident is **a system telling you which assumption was wrong**. The response
is a procedure; the value is in what changes afterwards.

## When to use

- Something is broken in production right now.
- Preparing on-call, runbooks, or severity definitions.
- A postmortem needs to produce real changes rather than a document.

## When NOT to use

- Pre-incident hardening of the pipeline itself (see `ci-cd-architect`,
  `observability-architect`).

## Decision 1 — Severity is about users

| Sev | Definition | Response |
|---|---|---|
| 1 | core journey down or data at risk | all hands, exec informed, status page |
| 2 | major degradation, workaround exists | on-call + owner team |
| 3 | minor/limited impact | normal business hours |
| 4 | cosmetic/no user impact | backlog |

- Severity is assigned by impact, not by how interesting the bug is.
- Declaring a Sev 1 is cheap and reversible; hesitating costs minutes users
  notice.

## Decision 2 — Roles (even with three people)

- **Incident commander** — decides, does not debug.
- **Communicator** — status page and stakeholders.
- **Operators** — investigate and mitigate.

One person may hold two roles early; the commander role must exist or decisions
stall.

## Decision 3 — First fifteen minutes

1. Declare and open a channel; timestamp everything.
2. Stabilise: roll back the last deploy, flip the kill switch, shed load.
3. Check the obvious: recent deploys, config changes, dependency status.
4. Communicate: what is affected, what users see, next update time.
5. Only then investigate root cause — mitigation beats understanding.

- Never debug on the affected host without capturing state first.
- Write down every hypothesis and its result; memory lies under stress.

## Decision 4 — Communication

- Status page updates at a fixed cadence (every 15–30 min), even with no news.
- Say what users experience and what is being done — no internal jargon.
- One channel of truth; speculation stays out of public updates.
- Tell support and sales before they hear it from customers.

## Decision 5 — Postmortem

- Blameless: focus on the system that allowed the action, not the person.
- Timeline from telemetry, not recollection.
- Contributing factors, not a single "root cause" — complex systems rarely have
  one.
- Actions are specific, owned, dated, and tracked like any other work.
- Share widely; a postmortem nobody reads changes nothing.

## Decision 6 — Convert findings into design

| Finding | Typical durable fix |
|---|---|
| one bad deploy broke everything | canary + automated abort |
| migration could not be rolled back | expand/contract discipline |
| nobody noticed for 40 minutes | symptom-based alerting |
| same outage twice | test or gate for that failure mode |
| only one person could fix it | runbook + second on-call |

## Failure modes at scale

- Incident commander is also the deepest debugger → no one is coordinating.
- Status page updated once, at the end.
- "Human error" as a root cause; nothing changes in the system.
- Action items assigned to "the team" with no date.
- A runbook that describes a UI that was redesigned two quarters ago.

## Verification receipts

1. Severity definitions and paging policy documented and exercised.
2. Runbooks for the top five failure modes, last verified date on each.
3. A recent postmortem: timeline from telemetry, actions with owners and dates.
4. Action completion rate from the last three postmortems.
5. Game day or tabletop executed within the quarter.
