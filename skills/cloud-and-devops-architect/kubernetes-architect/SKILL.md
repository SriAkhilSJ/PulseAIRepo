---
name: kubernetes-architect
description: Architect-level Kubernetes guidance — cluster and namespace topology, workload resource contracts, networking and ingress, autoscaling and capacity, rollout and disruption budgets, and the operational ownership a cluster demands. Use when running or evaluating Kubernetes.
license: MIT
compatibility: Kubernetes 1.28+; managed clusters preferred
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/kubernetes-architect
  crusor-origin: original
  crusor-sources: "kubernetes.io/docs/concepts; kubernetes.io/docs/tasks/run-application; 12factor.net"
  crusor-triggers: "kubernetes, k8s, helm, ingress, hpa, statefulset, cluster, pod disruption budget, namespace"
  crusor-verified-on: "2026-10-30"
---

# Kubernetes Architect

Kubernetes is **a distributed scheduler you now operate**. If nobody owns the
cluster, you have adopted a second product without a team.

## When to use

- Many services, a platform team, and a need for uniform deployment/observability.
- Dynamic scaling and self-healing are genuine requirements.
- Already-standardised on containers and GitOps.

## When NOT to use

- Fewer than ~5 services: ECS/Fargate, Cloud Run or a PaaS is cheaper to run.
- A single stateful monolith — a VM with a deploy script is honest.

## Decision 1 — Cluster topology

| Shape | Use |
|---|---|
| one cluster, many namespaces | small/medium orgs; namespace per team |
| cluster per environment | strongest isolation, more overhead |
| cluster per tenant | compliance-driven cases |

- Namespaces are the unit of policy, quota and RBAC — one per team or bounded
  context, not per deployment.
- ResourceQuota and LimitRange per namespace; without them one team starves the
  cluster.
- Managed control planes by default (EKS/GKE/AKS); self-managed only with a
  platform team.

## Decision 2 — Workload contracts

- Every container declares **requests and limits**; requests drive scheduling, so
  wrong requests mean random performance.
- Memory limit without a matching request → OOMKilled pods with no headroom.
- Readiness gates traffic; liveness restarts; startup probes for slow boots. A
  liveness probe tied to a dependency causes outage cascades.
- Non-root, read-only root FS, dropped capabilities, no privilege escalation.
- One process per container; config via ConfigMap/Secret, not baked images.

## Decision 3 — Networking

- Ingress/Gateway for north-south; NetworkPolicy for east-west default-deny.
- Service discovery by DNS names, not IPs.
- MTLS via a service mesh only if you need it — it is a second control plane to
  operate.
- Avoid `hostNetwork` and `hostPath` in application workloads.

## Decision 4 — Scaling and capacity

- HPA on CPU/memory is a baseline; queue depth or RPS custom metrics match real
  load better.
- Cluster autoscaler/Karpenter needs correct requests or it provisions the wrong
  nodes.
- PodDisruptionBudget for anything with an SLO; without it, node drains take out
  all replicas.
- Topology spread across zones for multi-AZ resilience.

## Decision 5 — Delivery and rollouts

- Deployments with `maxSurge`/`maxUnavailable` chosen per criticality.
- Canary or blue/green via the ingress/FLagger or an equivalent; not by editing
  replica counts by hand.
- GitOps (Argo/Flux) so the cluster state is the repository state; no `kubectl
  apply` from laptops.
- Rollback is a revert in git, and it is tested.

## Decision 6 — Operate it

- Metrics, logs, traces shipped off-cluster; etcd backups verified.
- Upgrades: control plane and node versions on a schedule, not when forced.
- Admission policies (OPA/Kyverno) for the rules you keep re-reviewing.
- Cost: right-size requests, use spot for stateless work with disruption
  budgets.

## Failure modes at scale

- No resource requests → noisy-neighbour latency under load.
- Liveness probe hitting the database → a DB blip restarts every pod.
- `kubectl apply` from laptops, so the cluster drifts from git within a week.
- One namespace for everything, RBAC effectively admin for all.
- Cluster upgraded for the first time when a version goes EOL.

## Verification receipts

1. Namespace inventory with quotas, RBAC roles and owners.
2. Workload audit: requests/limits present, probes sane, security context set.
3. Drain test: PDB keeps the service available during node maintenance.
4. Rollout and rollback demonstrated from git.
5. Cost per namespace and right-sizing report.
