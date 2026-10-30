---
name: ec2-architect
description: Architect-level virtual machine design — instance family and sizing, AMI and golden-image lifecycle, placement and tenancy, storage selection (EBS types, instance store), autoscaling groups with health checks, and the patching and replacement model that keeps a VM fleet from rotting. Use when workloads run on VMs rather than containers or functions.
license: MIT
compatibility: AWS EC2; GCE/Azure VM analogues
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/compute-architect/ec2-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/AWSEC2/latest/UserGuide; docs.aws.amazon.com/ebs/latest/userguide; cloud.google.com/compute/docs"
  crusor-triggers: "ec2, virtual machine, ami, instance type, ebs, autoscaling group, spot instance, golden image, vm fleet, instance store"
  crusor-verified-on: "2026-10-30"
---

# EC2 / VM Architect

VMs are **pets you can replace**. The architecture question is whether the
replacement path is automated — because the instance will fail, and patching
decides how often.

## When to use

- Legacy or stateful workloads that cannot containerise yet.
- Licensed software, kernel-level agents, GPU training.
- Burstable or specialised hardware needs.

## When NOT to use

- Stateless HTTP services → `kubernetes-architect` or
  `compute-architect/serverless-architect`.
- Anything where the OS is not your concern.

## Decision 1 — Instance choice

| Need | Family |
|---|---|
| general web/app | general purpose (m/c) |
| CPU-bound | compute optimised (c) |
| memory-heavy caches, JVM | memory optimised (r/x) |
| GPU training/inference | accelerated (p/g) |
| rare, spiky, tolerant of interruption | spot |
| sustained baseline | reserved/savings plan |

- Size to measured p95, not to the vendor's "recommended".
- Graviton/ARM gives real price-performance wins where the stack supports it.
- Spot for batch and stateless workers with interruption handling; never for
  stateful single instances.

## Decision 2 — Images

- Golden images built by pipeline: base OS, patches, agents, no secrets, no
  application config baked where it varies.
- Immutable: deploy a new AMI, replace instances, never patch in place as the
  normal path.
- Image lifecycle: build weekly, scan for CVEs, deprecate old, keep N-1.
- Instance metadata service v2 enforced; no credentials on the image.

## Decision 3 — Storage

| Volume | Use |
|---|---|
| gp3 SSD | default; set IOPS/throughput explicitly |
| io2 | high, consistent IOPS (databases) |
| st1/sc1 | throughput workloads, logs |
| instance store | ephemeral scratch, caches — lost on stop |

- Snapshots scheduled and copied cross-region for anything that matters.
- Encryption at rest by default with a customer-managed key.
- Delete-on-termination set deliberately; orphaned volumes are a silent bill.

## Decision 4 — Scaling and availability

- Autoscaling group across ≥2 AZs, with ELB health checks (not just EC2 status).
- Scale on the metric that predicts load (queue depth, latency), not CPU alone.
- Warm pools or pre-baked images to cut boot time out of the scaling path.
- Lifecycle hooks for graceful drain before termination.
- Replacement-based patching: rolling replace with health gates, not SSH and
  `apt upgrade`.

## Decision 5 — Access and operations

- No SSH in the steady state: SSM Session Manager or equivalent, logged and
  IAM-gated.
- Host hardening baseline (CIS) applied by the image build and verified.
- Centralised logs and metrics from the agent, not from a login.
- Inventory: every instance tagged with owner, service, environment, and image
  version.

## Failure modes at scale

- Hand-patched snowflakes; nobody dares rebuild the oldest one.
- Single-AZ autoscaling group; an AZ event takes the service down.
- gp2 volumes silently throttling; latency blamed on the app.
- Orphaned volumes and snapshots costing more than the instances.
- SSH open to the world because the image build was broken.

## Verification receipts

1. Instance inventory with family, size, image version, owner.
2. Image build pipeline output, scanned and versioned.
3. AZ-failure test: instances replaced in the surviving AZs.
4. Graceful drain observed during a scaling event.
5. Cost report: instances vs volumes vs snapshots, orphaned resources removed.
