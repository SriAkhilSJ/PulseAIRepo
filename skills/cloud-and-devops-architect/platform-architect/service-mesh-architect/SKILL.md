---
name: service-mesh-architect
description: Architect-level service mesh design — what a mesh actually buys (mTLS, retries, traffic shifting, telemetry), sidecar versus ambient versus gateway-only, policy ownership across teams, and the latency and operational cost that decides whether it is worth it. Use when service-to-service traffic needs uniform control.
license: MIT
compatibility: Istio, Linkerd, Cilium, Consul, AWS App Mesh
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/platform-architect/service-mesh-architect
  crusor-origin: original
  crusor-sources: "istio.io/latest/docs; linkerd.io/2-edge/overview; docs.cilium.io"
  crusor-triggers: "service mesh, istio, linkerd, envoy sidecar, mtls, traffic shifting, canary traffic, ambient mesh, cilium mesh"
  crusor-verified-on: "2026-10-30"
---

# Service Mesh Architect

A mesh is **a proxy per hop plus a policy control plane**. It solves uniform
traffic behaviour; it also adds a moving part to every request path.

## When to use

- Many services, many teams, needing consistent mTLS, retries, and telemetry.
- Progressive delivery (canary, traffic mirroring) at the network layer.
- Multi-cluster or multi-runtime connectivity.

## When NOT to use

- A handful of services — library-level retries and an ingress cover most needs.
- A single team that cannot operate a control plane.

## Decision 1 — Is it justified

| Need | Mesh | Cheaper alternative |
|---|---|---|
| uniform mTLS between services | yes | platform-level auto-mTLS |
| per-route retries/timeouts | yes | client library + gateway |
| canary by percentage across many services | yes | ingress/rollout controller |
| consistent L7 telemetry | yes | OpenTelemetry SDK |
| authorisation policy between services | yes | network policy + app auth |

- Count the hops first: mesh adds ~1–3 ms per hop and a sidecar's memory per pod.
- If you cannot staff the control plane, do not deploy it.

## Decision 2 — Data plane model

| Model | Trade-off |
|---|---|
| sidecar per pod | mature, per-pod overhead |
| ambient / sidecar-less | lower overhead, newer, some features lag |
| node-level (eBPF) | fast, kernel-dependent, less L7 richness |
| gateway only | minimal, no per-pod policy |

- Sidecars if you need full L7 policy today; ambient if overhead is the binding
  constraint and the feature set covers you.
- Resource requests for sidecars are real cost — size them and account for them in
  capacity.

## Decision 3 — Identity and policy

- mTLS identity from the platform (SPIFFE), not certificates you manage by hand.
- Authorisation policy: default deny between namespaces, explicit allow per route.
- Policy ownership: platform defines the model, teams declare their own
  allow-rules — otherwise every change is a platform ticket.
- Do not let the mesh become the only authorisation layer; application-level
  authorisation still owns business rules.

## Decision 4 — Traffic management

- Canary/blue-green by weighted routing with automated rollback on error-rate
  alarms.
- Timeouts and retries: mesh retries multiply — cap total attempts across hops or
  a partial outage becomes a retry storm.
- Circuit breaking at the destination; outlier detection ejects failing instances.
- Fault injection for game days, scoped to a namespace.

## Decision 5 — Operations

- Control plane upgrades are rolling and versioned; data plane compatibility
  matters — check the support matrix.
- Mesh telemetry (requests, latency, error rate per route) is the observability
  backbone; wire it to dashboards, not just to a collector.
- Debugging: know how to bypass the mesh for a single pod during an incident.
- Config drift: mesh policy as code with review, like everything else.

## Failure modes at scale

- Mesh deployed for mTLS; nobody uses the traffic policies; cost doubled.
- Retries at mesh, client, and app layer: a 3× retry storm on a degraded service.
- Sidecar CPU limits too low; p99 latency rises under load.
- Default-allow authorisation because deny was "breaking things".
- Control plane upgrade leaves half the data plane incompatible.

## Verification receipts

1. Justification table: need → mesh feature → alternative considered.
2. mTLS verification with a captured handshake and a denied plaintext call.
3. Canary routing demonstrated with measured error-rate comparison.
4. Overhead measured: added latency and memory per pod.
5. Retry budget documented and verified under injected failure.
