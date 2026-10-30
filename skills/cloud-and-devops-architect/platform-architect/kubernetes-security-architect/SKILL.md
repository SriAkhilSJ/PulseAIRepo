---
name: kubernetes-security-architect
description: Architect-level cluster hardening — RBAC and service accounts, admission control and policy engines, pod security standards, network policy, image provenance and runtime detection, and the multi-tenancy boundaries that decide whether a shared cluster is safe. Use when a cluster hosts more than one team or any sensitive workload.
license: MIT
compatibility: Kubernetes; EKS/GKE/AKS, OPA Gatekeeper/Kyverno
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/platform-architect/kubernetes-security-architect
  crusor-origin: original
  crusor-sources: "kubernetes.io/docs/concepts/security; kubernetes.io/docs/reference/access-authn-authz/rbac; kyverno.io/docs"
  crusor-triggers: "kubernetes security, rbac, pod security, admission controller, kyverno, gatekeeper, network policy, cluster hardening, image provenance, multi tenancy"
  crusor-verified-on: "2026-10-30"
---

# Kubernetes Security Architect

A cluster is **a shared kernel with an API that can schedule anything**. Isolation
is a configuration you enforce, not a property you assume.

## When to use

- Multi-team or multi-tenant clusters.
- A security review, compliance requirement, or post-incident hardening.
- Designing admission policy and RBAC.

## When NOT to use

- Single-tenant, short-lived dev clusters — apply the baseline and move on.
- Application authorization → web security books.

## Decision 1 — Tenancy

| Boundary | Strength |
|---|---|
| namespace + RBAC + network policy | soft, one cluster |
| namespace + policy engine + quotas | medium |
| separate node pools with taints | stronger |
| separate clusters per tenant | strongest, more cost |

- Namespaces are not a security boundary by themselves; RBAC, network policy, and
  admission control make them one.
- ResourceQuota and LimitRange per namespace prevent one team starving the cluster.
- For regulated tenants, separate clusters; shared clusters need a documented risk
  acceptance.

## Decision 2 — Identity

- No cluster-admin for humans; break-glass with audit and expiry.
- Workload identity from the cloud (IRSA/Workload Identity) instead of static
  secrets; one service account per workload.
- Disable automounting of service account tokens where unused.
- RBAC by role + binding per namespace; no wildcard verbs on cluster-scoped
  resources.

## Decision 3 — Workload hardening

- Pod Security Standards: restricted baseline enforced by admission.
- Non-root, read-only root filesystem, dropped capabilities, seccomp profile.
- No hostPath, hostNetwork, or privileged pods outside a labelled system namespace.
- Resource limits mandatory — limits are also a denial-of-service control.
- Image policy: only signed images from the approved registry; digest-pinned.

## Decision 4 — Network

- Default-deny ingress and egress per namespace; allow flows explicitly.
- DNS egress allowed narrowly; metadata endpoint blocked from pods that do not need
  cloud identity.
- Ingress only through the approved gateway; no ad-hoc NodePorts.
- Egress to the internet via a controlled proxy or NAT with logging.

## Decision 5 — Admission and detection

- Policy engine (Kyverno/Gatekeeper) enforcing: no `latest` tags, required labels,
  resource limits, allowed registries, no privileged.
- Policies versioned in git; violations audited before enforcement in a new
  cluster.
- Runtime detection (Falco/cloud-native equivalents) for shell-in-container,
  unexpected outbound connections, and crypto-mining patterns.
- Audit logs shipped off-cluster with retention.

## Decision 6 — Supply chain

- Images built by CI with provenance/SBOM; scanned for CVEs; signed.
- Admission verifies signature and registry; a policy that only alerts is theatre.
- Base images patched on a cadence; rebuild rather than mutate running pods.
- Secrets injected from a secret manager at runtime, not baked into images.

## Failure modes at scale

- Everyone has cluster-admin "temporarily" for a deployment.
- Default service account token mounted into every pod, usable by any SSRF.
- No network policy: a compromised front-end reaches the database directly.
- Policy engine in audit mode for a year; violations in the thousands.
- Images pulled from Docker Hub at deploy time, unpinned.

## Verification receipts

1. RBAC report: cluster-admin holders, wildcard rules, unused bindings.
2. Pod Security admission enforced with a rejected test pod.
3. Network policy matrix: denied flows verified between namespaces.
4. Policy engine in enforce mode with a blocked non-compliant manifest.
5. Runtime detection alert triggered by a safe simulated event.
