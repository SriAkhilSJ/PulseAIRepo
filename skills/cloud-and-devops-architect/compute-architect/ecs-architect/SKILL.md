---
name: ecs-architect
description: Architect-level container platform design without Kubernetes — ECS/Fargate task definitions, service scheduling and placement, ALB integration, secrets and IAM task roles, blue-green deploys with CodeDeploy, and the operational surface a small team can actually run. Use when containers are needed but a full cluster is not.
license: MIT
compatibility: AWS ECS, Fargate; Cloud Run and Azure Container Apps analogues
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/compute-architect/ecs-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/AmazonECS/latest/developerguide; docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide; aws.github.io/copilot-cli"
  crusor-triggers: "ecs, fargate, task definition, container service, copilot, aws container, blue green deploy, service discovery, container platform"
  crusor-verified-on: "2026-10-30"
---

# ECS Architect

ECS is **a container scheduler with a small surface**. It wins when the team wants
containers, not a cluster to operate — so the design should stay boring.

## When to use

- AWS-native containers without Kubernetes expertise.
- Small platform team, few services, strong AWS alignment.
- Batch jobs and scheduled tasks alongside long-running services.

## When NOT to use

- Rich scheduling needs, CRDs, or multi-cloud portability → `kubernetes-architect`.
- A single container with mild traffic → Cloud Run / App Runner / Lambda container.

## Decision 1 — Fargate or EC2 capacity

| Factor | Fargate | EC2 capacity |
|---|---|---|
| ops burden | none | patching, scaling, AMIs |
| cost at high, steady utilisation | higher | lower |
| GPU / special hardware | no | yes |
| daemon-style agents | limited | yes |
| predictable burst | good | fine with capacity providers |

- Start on Fargate; move to capacity providers when sustained utilisation makes
  the price difference real.

## Decision 2 — Task definition

- One process per container; a sidecar only for a genuine cross-cutting concern
  (proxy, log router).
- CPU/memory at task level and container level, sized from measurement.
- Image by digest, not `latest`; immutable tags in every environment.
- Secrets from Secrets Manager/SSM via `secrets`, never in environment plaintext.
- Task role (application permissions) separate from execution role (pull/log).
- Health check defined in the task, matching the app's real readiness.
- Read-only root filesystem where the app allows; non-root user.

## Decision 3 — Services

- Service per deployable; ALB target group per service, path/host rules upstream.
- Deployment: rolling with circuit breaker, or blue-green via CodeDeploy with
  traffic shifting and automatic rollback on alarms.
- `desiredCount` across AZs with spread placement; no single-AZ pinning.
- Service discovery via Cloud Map for internal service-to-service calls.
- Autoscaling on ALB request count, queue depth, or latency — not CPU alone.

## Decision 4 — Networking

- `awsvpc` mode; private subnets only; egress via NAT or VPC endpoints.
- Security groups per service, referencing other services' groups.
- No public IPs on tasks; ingress only through the load balancer.

## Decision 5 — Operations

- Logs to CloudWatch with structured JSON and a retention policy; traces via
  X-Ray/OTel.
- Deploy pipeline: build → scan image → push → register task definition → deploy
  with rollback alarms.
- Runbook: how to roll back a service, drain a task, and read the last deployment
  event.
- Cost: Fargate task size drift is the usual leak — a 4 vCPU task for a 200 ms
  handler.

## Failure modes at scale

- Task definition with 4 GB memory for a service that needs 512 MB, ×40 services.
- Secrets in plaintext environment variables visible in the console.
- `latest` tag deployed; two environments run different code with the same name.
- No circuit breaker; a failing deploy replaces every task and stays broken.
- One cluster per service, doubling the operational surface for no isolation gain.

## Verification receipts

1. Task definition inventory: image digest, size, roles, secrets source.
2. Blue-green deploy demonstrated with automatic rollback on a bad image.
3. Networking check: no public IP, egress path documented.
4. Autoscaling policy tested under a synthetic load increase.
5. Cost per service at current task size, with right-sizing proposals.
