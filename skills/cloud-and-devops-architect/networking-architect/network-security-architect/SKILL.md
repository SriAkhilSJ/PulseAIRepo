---
name: network-security-architect
description: Architect-level cloud network security — segmentation models, ingress and egress inspection, private connectivity to SaaS, DDoS and WAF layering, east-west controls, and the detective controls (flow logs, DNS logs) that make a network defensible. Use when designing a perimeter or responding to a network-level requirement.
license: MIT
compatibility: Any cloud; firewalls, WAF, service mesh
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/networking-architect/network-security-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/whitepapers/latest/security-overview-aws; cloud.google.com/architecture/security-foundations; learn.microsoft.com/azure/security/fundamentals"
  crusor-triggers: "network security, firewall, waf, ddos, segmentation, egress inspection, private link, zero trust network, flow logs, east west traffic"
  crusor-verified-on: "2026-10-30"
---

# Network Security Architect

Segmentation is **the difference between one compromised service and a compromised
estate**. Identity controls the front door; the network controls lateral movement.

## When to use

- Designing or auditing a cloud perimeter.
- A compliance framework demands network controls.
- After an incident where lateral movement was possible.

## When NOT to use

- Pure IAM design → `iam-architect`.
- Application authorization → web `authz-models-architect`.

## Decision 1 — Zones

| Zone | Contains | Allowed |
|---|---|---|
| public | load balancers only | inbound 443 from internet |
| application | services | inbound from public LB only |
| data | databases, caches | inbound from application only |
| management | bastions, CI, admin APIs | inbound from corp/VPN, MFA |
| partner | third-party integrations | narrow, documented flows |

- Default deny between zones; allow per flow with a named owner.
- Reference security groups/service accounts, not CIDRs.
- One management zone with strong identity beats many openings.

## Decision 2 — Ingress

- WAF in front of every public HTTP endpoint; managed rules plus your own.
- DDoS protection at the provider edge; know what the plan covers (L3/4 vs L7).
- mTLS or origin authentication from edge to origin — otherwise the WAF is
  optional for anyone who finds the IP.
- No direct public IPs on application or data nodes.

## Decision 3 — Egress

- Default deny egress in regulated environments; allowlisted domains via a proxy
  or firewall.
- DNS-layer filtering catches callbacks and exfiltration cheaply.
- Block metadata access from workloads that do not need it; enforce IMDSv2.
- Private connectivity (PrivateLink/PSC/Private Endpoint) for SaaS and cloud APIs
  instead of egress to the internet.
- Log egress volume per workload; a sudden 10× is an incident signal.

## Decision 4 — East-west

- Service-to-service authentication (mTLS) where the mesh supports it; network
  policy alone is spoofable inside a cluster.
- Namespace/service segmentation in Kubernetes plus network policies default-deny.
- Database access only from the service's own identity, not from a shared bastion
  with a shared password.
- Regular sweeps: which services can reach the data tier that have no reason to?

## Decision 5 — Detection

- VPC flow logs and DNS logs to a central store with retention.
- Alerts on: new open security group, port scan patterns, traffic to unusual
  geographies, spikes in denied connections.
- Baseline normal flows; the anomaly is what matters, not raw volume.
- Correlate network identity with IAM identity in the same timeline.

## Decision 6 — Operations

- Changes to firewall rules via IaC with review; portal edits are drift and drift
  is an open port.
- Quarterly rule review: unused rules removed, exceptions expired.
- Document each allowed flow: source, destination, port, owner, why.

## Failure modes at scale

- `0.0.0.0/0` on the database security group "for the analytics team".
- WAF deployed, origin publicly reachable, rules bypassed.
- No egress controls; a compromised container exfiltrates over HTTPS.
- 4,000 firewall rules, none removable, all "critical".
- Flow logs enabled but never queried until after the incident.

## Verification receipts

1. Zone diagram with the allowed flows table and owners.
2. External port scan of public endpoints: only 443 exposed.
3. Direct-to-origin attempt blocked, demonstrated.
4. Egress test: unapproved destination denied and logged.
5. Flow-log query reconstructing a past connection path.
