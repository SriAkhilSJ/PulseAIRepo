---
name: cost-optimization-architect
description: Architect-level cloud cost engineering — attribution through tagging and accounts, the structural drivers of spend (idle, egress, storage and logs), unit-economics thinking, and the review rhythm that keeps cost from becoming a quarterly surprise. Use when cloud spend is growing faster than usage.
license: MIT
compatibility: Any cloud; any billing export
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/cost-optimization-architect
  crusor-origin: original
  crusor-sources: "aws.amazon.com/aws-cost-management; cloud.google.com/cost-management; azure.microsoft.com/pricing"
  crusor-triggers: "cloud cost, cloud bill, bill doubled, cost spike, billing, finops, cost optimization, reserved instances, savings plans, egress, budget alarm, spend"
  crusor-verified-on: "2026-10-30"
---

# Cost Optimization Architect

Cost is **an architectural output**, not a spreadsheet cleanup. You can optimize
invoices for a quarter; only design changes the curve.

## When to use

- Spend grows faster than traffic or revenue.
- Starting a new system: the cost model is part of the design.
- Nobody can answer "what does this feature cost to run?"

## When NOT to use

- Micro-optimising a $40/month environment while latency or reliability is
  failing.

## Decision 1 — Attribution first

- Tag/label every resource with service, environment, owner; enforce it in IaC,
  not in a wiki.
- Separate accounts per environment so cost boundaries cannot be fudged.
- Monthly report by tag and by environment; untagged spend is an incident, not a
  rounding error.
- Unit economics: cost per request, per tenant, per active user. Absolute spend
  says nothing without a denominator.

## Decision 2 — The structural drivers

| Driver | Typical fix |
|---|---|
| idle/oversized compute | right-size from metrics, autoscale, schedule non-prod off |
| egress and cross-AZ traffic | colocate chatty services, endpoints instead of NAT |
| storage never deleted | lifecycle rules, snapshots retention, log retention |
| logging/metrics ingestion | sampling, retention tiers, drop debug in prod |
| over-provisioned databases | size to peak, read replicas only with need |
| orphaned resources | unattached volumes, old IPs, forgotten load balancers |

- The cheapest instance is the one that is not running: schedule dev/staging.

## Decision 3 — Commitment strategy

- On-demand for unpredictable; savings plans/reserved for a stable baseline,
  measured over time.
- Commit to the *baseline*, never to peak; over-commitment is a lock-in cost.
- Spot/preemptible for fault-tolerant batch and stateless workers, with
  interruption handling.
- Review commitments quarterly against actual usage.

## Decision 4 — Design decisions that change the bill

- Architecture sets cost shape: chatty microservices multiply network spend;
  serverless multiplies per-request cost at steady load.
- Caching reduces compute but adds a service to operate — compute the crossover.
- Data residency and multi-region replication double storage and egress by
  design.
- Retention policy is a product decision with a price tag; make it explicit.

## Decision 5 — The rhythm

- Budgets and anomaly alerts per environment; alerts route to the owner.
- Weekly cost review in the platform team; monthly with product.
- Every new service ships with an estimated monthly cost in its design doc.
- Cost regressions are found by the trend, not by the invoice at month end.

## Failure modes at scale

- Untagged resources: 30% of the bill cannot be attributed.
- Reserved instances bought for peak traffic, then unused.
- Cross-AZ chatter between two services that could be one deployment.
- 18 months of debug logs retained "in case".
- Cost reviews that list savings but never change the architecture.

## Verification receipts

1. Tag coverage report (target: 100% of spend attributable).
2. Top five cost drivers with an owner and a decision each.
3. Unit cost per request/tenant trend over the last quarter.
4. Commitment coverage vs baseline usage.
5. Scheduled-off non-production environments verified.
