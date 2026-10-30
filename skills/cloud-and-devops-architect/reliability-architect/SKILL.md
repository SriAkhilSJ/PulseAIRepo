---
name: reliability-architect
description: Architect-level reliability engineering — SLIs and SLOs that mean something, redundancy and failure-domain design, degradation over failure, backup and disaster-recovery targets, and the drills that prove any of it is real. Use when a system must stay up under load and partial failure.
license: MIT
compatibility: Any stack and cloud
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/reliability-architect
  crusor-origin: original
  crusor-sources: "sre.google/sre-book; aws.amazon.com/architecture/well-architected/reliability"
  crusor-triggers: "reliability, slo, sli, availability, disaster recovery, failover, redundancy, error budget, capacity planning"
  crusor-verified-on: "2026-10-30"
---

# Reliability Architect

Reliability is **a number you promised and can measure**, plus the engineering that
keeps the number true. Everything else is aspiration.

## When to use

- Setting availability targets for a service or product.
- Designing for multi-AZ, multi-region, or graceful degradation.
- Deciding how much redundancy the business actually needs.

## When NOT to use

- The system has no users yet — measure first, promise later (but design the
  failure domains now).

## Decision 1 — Define the promise

| Availability | Downtime/month |
|---|---|
| 99% | ~7 h |
| 99.9% | ~43 min |
| 99.95% | ~22 min |
| 99.99% | ~4 min |

- SLIs are ratios measured at the user boundary: successful, fast, correct.
- One SLO per user journey; an error budget (1 − SLO) that product can spend
  deliberately.
- 100% is not a target: it removes the ability to change anything.

## Decision 2 — Failure domains

- Enumerate what fails together: process, host, AZ, region, dependency,
  credential, DNS.
- Each dependency needs a stated behaviour when it fails: retry, degrade, queue,
  or refuse.
- Stateless where possible; state with a single owner and tested recovery.
- No single instance of anything an SLO depends on.

## Decision 3 — Degrade, don't die

| Failure | Graceful response |
|---|---|
| recommendation service down | show a static bestseller list |
| cache down | serve slightly stale from DB, raise latency budget |
| payment provider down | queue the intent, confirm later |
| auth provider down | existing sessions continue, new logins wait |

- Circuit breakers with sensible thresholds; timeouts shorter than the caller's
  patience.
- Load shedding beats queue collapse: reject early with 429 and Retry-After.
- Health checks reflect *dependencies*, so the platform removes bad instances.

## Decision 4 — Backups and DR

- RPO/RTO written per dataset, agreed with the business, tested.
- Backups encrypted, in a different account/region, immutable where possible.
- Restore drill on a schedule — an untested backup is a rumour.
- Region failover, if claimed, has a runbook, a DNS strategy, and a rehearsal.

## Decision 5 — Capacity

- Know the units: requests/s per instance, DB connections, queue throughput.
- Load test at 2× projected peak; find the knee, not just the pass.
- Autoscaling needs headroom and correct metrics; scale-up latency is a design
  input.
- Pre-scale for known events; do not rely on the scaler to be fast enough.

## Decision 6 — Prove it

- Game days: kill an AZ, expire a credential, block a dependency.
- Chaos experiments in staging first, then production with a kill switch.
- Every incident feeds a design change, not just a runbook edit.

## Failure modes at scale

- "Highly available" with a single NAT gateway and one AZ for the database.
- Retries without backoff turning a blip into a metldown.
- SLO computed from server logs that ignore user-perceived failures.
- Backup restore never attempted; the first attempt is during an outage.
- Capacity planned from averages, not peaks.

## Verification receipts

1. SLO document with SLI definitions and current burn.
2. Failure-mode table per dependency with the designed response.
3. Load test at 2× peak with the knee identified.
4. Restore drill executed, RTO measured, notes attached.
5. Game day report with defects found and fixed.
