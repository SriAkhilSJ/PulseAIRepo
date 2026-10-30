---
name: cloud-and-devops-architect
description: Architect-level cloud direction — choosing provider services from operational reality, environment and account topology, infrastructure-as-code ownership, network and identity boundaries, reliability targets, and the cost model a system is designed against. Use before any provider, orchestration or IaC skill.
license: MIT
compatibility: AWS/GCP/Azure; Kubernetes; Terraform or Pulumi
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect
  crusor-origin: original
  crusor-sources: "12factor.net; aws.amazon.com/architecture/well-architected; kubernetes.io/docs; developer.hashicorp.com/terraform"
  crusor-triggers: "cloud architecture, infrastructure, devops, iac, kubernetes, terraform, environments, networking, cloud cost"
  crusor-verified-on: "2026-10-30"
---

# Cloud & DevOps Architect

Cloud architecture is **renting failure modes**. Every managed service you adopt
buys operational simplicity and sells you a new dependency, a new limit, and a
new bill.

## Leaf map

Seven shelves, 35 books.

| Shelf | Books |
|---|---|
| `providers-architect/` | `aws` · `gcp` · `azure` · `cloudflare` |
| `identity-architect/` | `iam` · `multi-account` · `secrets-and-keys` |
| `networking-architect/` | `vpc-networking` · `dns-and-edge` · `network-security` |
| `compute-architect/` | `kubernetes` · `serverless` · `ec2` · `ecs` · `lambda` · `autoscaling` |
| `data-services-architect/` | `object-storage` · `managed-databases` · `messaging` · `caching` |
| `iac-architect/` | `terraform` · `pulumi` · `cloudformation` · `ansible` |
| `platform-architect/` | `helm` · `gitops` · `service-mesh` · `kubernetes-security` · `platform-engineering` |
| `operations-architect/` | `reliability` · `cost-optimization` · `sre-observability` · `chaos-engineering` · `backup-and-dr` · `cloud-incident-response` |

Read this crown, then take the one or two books the decision needs. The shelf
tells you the axis; the book tells you the trade-off.

## Decision 1 — Topology before services

```
accounts/subscriptions per environment (dev, staging, prod, shared)
  network per environment (VPC/VNet), private by default
    workload per bounded context
      data per owner — never one shared database for everything
```

- Environments are **isolated by account**, not by naming convention.
- Blast radius is a design input: what fails together should be grouped
  together, and production must not share a control plane with staging.
- One region until a documented requirement forces multi-region; multi-region
  multiplies every consistency decision.

## Decision 2 — Managed vs self-run

| Situation | Choose |
|---|---|
| commodity (queues, object storage, DNS) | managed |
| undifferentiated but operationally risky (Kafka, Postgres at scale) | managed first |
| core differentiator, hard constraints | self-run, with an owner |

- Every self-run component needs an owner, a runbook, and an upgrade path.
- Managed services still need limits knowledge: quotas, throttles, regional
  availability, and the pricing cliff.

## Decision 3 — Infrastructure as code, always

- No console changes in production; drift is detected and reverted.
- State is remote, locked, and per environment; state contains secrets, so it is
  access-controlled.
- Modules are versioned and consumed by reference, not copy-paste.
- Plan output is reviewed like code; apply happens in the pipeline.

## Decision 4 — Identity and network boundaries

- Workloads authenticate with roles/workload identity, never static keys.
- Least privilege per service: each has its own identity and its own policy.
- Private subnets for data and internal services; public only where required
  (load balancer, CDN edge).
- Egress is controlled: an allow-list beats an open NAT for both security and
  cost.
- Secrets in a managed secret store with rotation (see
  `secrets-management-architect`).

## Decision 5 — Reliability targets

- Define SLIs/SLOs per user journey before choosing redundancy.
- Single-AZ by default, multi-AZ for anything with an SLO above 99.9%.
- Backups: automated, encrypted, restore-tested; RPO/RTO written down.
- Chaos is scheduled: kill an instance, drain a zone, expire a credential.

## Decision 6 — Cost is architecture

- Tag everything (service, environment, owner) from day one; untagged spend
  cannot be attributed.
- Budgets and alerts per environment; anomaly detection on.
- The expensive patterns are predictable: idle clusters, cross-AZ chatter,
  unbounded logs, over-provisioned instances, storage never deleted.

## Failure modes at scale

- Console changes that IaC later reverts or duplicates.
- One account for everything; a staging mistake reaches production credentials.
- Static access keys in CI.
- Multi-region "for safety" with no failover test.
- Costs discovered at the end of the quarter, untagged and unattributable.

## Verification receipts

1. Account/environment diagram with network and identity boundaries.
2. IaC plan/drift report clean; no manual production changes in the last period.
3. IAM review: per-workload roles, no long-lived keys.
4. Restore drill with measured RTO; failover drill if multi-AZ/region claimed.
5. Cost report by tag with budget alerts active.
