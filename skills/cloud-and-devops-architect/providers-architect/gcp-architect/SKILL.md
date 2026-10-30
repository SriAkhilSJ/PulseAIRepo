---
name: gcp-architect
description: Architect-level Google Cloud design — project and folder hierarchy, IAM and service accounts, VPC design and Shared VPC, GKE versus Cloud Run versus App Engine, BigQuery as the analytical anchor, and the quotas and org policies that actually govern a GCP estate. Use when building on Google Cloud.
license: MIT
compatibility: Google Cloud
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/providers-architect/gcp-architect
  crusor-origin: original
  crusor-sources: "cloud.google.com/architecture/framework; cloud.google.com/iam/docs; cloud.google.com/run/docs"
  crusor-triggers: "gcp, google cloud, gke, bigquery, cloud run, gcp architect, google kubernetes engine, folder hierarchy"
  crusor-verified-on: "2026-10-30"
---

# GCP Architect

GCP's shape is **projects as the unit of everything**: billing, quotas, IAM, and
network. Get the hierarchy right and most governance follows for free.

## When to use

- Designing a GCP landing zone or onboarding a new workload.
- Choosing between GKE, Cloud Run, and App Engine.
- BigQuery is the analytical destination.

## When NOT to use

- Multi-cloud abstraction → `cloud-and-devops-architect` crown first.
- The workload is already pinned to another provider.

## Decision 1 — Hierarchy

```
Organization
  Folders        environment or business unit
    Projects     one per workload/environment pair
      Resources
```

- Projects are cheap; use them. One project for everything destroys quota
  isolation, billing attribution, and IAM boundaries at once.
- Recommended split: `prod-<svc>`, `nonprod-<svc>`, `shared-network`, `shared-data`.
- Org policies at folder level are the real guardrails: disable SA key creation,
  restrict resource locations, enforce uniform bucket access.

## Decision 2 — IAM

- Use **service accounts as identities with least privilege**, one per workload
  component; never the default compute account.
- Prefer Workload Identity / Workload Identity Federation over exported SA keys.
  An exported key is a permanent credential in a text file.
- Custom roles only when predefined roles are too broad — they are unmaintainable
  at scale.
- `roles/viewer` at org level is an audit-friendly compromise; `roles/owner` at
  org level never is.
- Domain-restricted sharing for anything user-facing.

## Decision 3 — Network

- Shared VPC when several projects need one network; host project owns subnets,
  service projects attach.
- Private Google Access; no public IPs on data-plane VMs by default.
- Cloud NAT for egress; VPC Service Controls for exfiltration-sensitive data
  (BigQuery, storage, Secret Manager).
- Global external load balancer + Cloud Armor for public entry; regional for
  residency.

## Decision 4 — Compute choice

| Workload | Choice |
|---|---|
| container, occasional or bursty, HTTP | Cloud Run |
| container needing GPUs, sidecars, DaemonSets | GKE Autopilot |
| full cluster control, custom operators | GKE Standard |
| long batch, no HTTP | Batch or Cloud Run jobs |
| legacy runtime assumptions | App Engine — migrate if possible |

- Cloud Run for most request/response services: scale-to-zero, revisions, traffic
  splitting.
- GKE Autopilot removes node management; Standard only when you need node-level
  control (GPUs, privileged, custom networking).

## Decision 5 — Data

- BigQuery is the default analytical store: separation of storage and compute,
  slots or on-demand, partitioning and clustering are mandatory at scale.
- Cloud Storage: uniform bucket-level access, versioning, lifecycle rules,
  retention locks for compliance.
- Datastore/Firestore for document; Cloud SQL for relational parity; Spanner only
  when global consistency is a stated requirement (and budget exists).
- Pub/Sub as the default event bus; ordering keys when per-key order matters.

## Decision 6 — Operations

- Quotas are per project and per region; a quota increase is a launch dependency,
  not a post-launch fix.
- Cloud Logging/Monitoring costs scale with ingestion — set exclusions and
  retention on day one.
- Cost controls: budgets with alerts per project, committed use for steady
  baseline, and a label policy (`env`, `team`, `service`).

## Failure modes at scale

- One project, all workloads, one shared default SA with editor.
- Exported SA JSON keys pasted into CI secrets.
- No org policy; a developer creates a public bucket.
- BigQuery queried without partition filters; the bill arrives before the fix.
- Logging ingestion exceeding compute spend.

## Verification receipts

1. Hierarchy diagram with folders, projects, and billing accounts.
2. Service account inventory: no default SAs in use, no exported keys.
3. Org policy list with the resources each one protects.
4. Network diagram: Shared VPC host/service projects, private access, egress path.
5. Budget alerts per project plus a label coverage report.
