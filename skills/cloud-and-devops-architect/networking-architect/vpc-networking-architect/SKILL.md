---
name: vpc-networking-architect
description: Architect-level cloud network design — VPC/VNet topology, subnet tiers, egress patterns, peering versus transit, private connectivity to managed services, load balancer placement, and the segmentation that keeps a compromised workload contained. Use when designing or auditing a cloud network.
license: MIT
compatibility: AWS VPC, GCP VPC, Azure VNet
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/networking-architect/vpc-networking-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/vpc/latest/userguide; cloud.google.com/vpc/docs; learn.microsoft.com/azure/virtual-network"
  crusor-triggers: "vpc, vnet, subnet, peering, nat gateway, transit gateway, private endpoint, network segmentation, egress, cidr"
  crusor-verified-on: "2026-10-30"
---

# VPC Networking Architect

A cloud network is **a routing table plus a policy surface**. Most incidents are
not routing failures — they are segmentation decisions nobody wrote down.

## When to use

- Designing a VPC from scratch or splitting one.
- Egress costs or NAT bottlenecks appear.
- A security review asks what can talk to what.

## When NOT to use

- Application-level authorisation → `iam-architect`.
- Edge/CDN routing → `cloudflare-architect` or `dns-and-edge-architect`.

## Decision 1 — Topology

| Model | Use |
|---|---|
| single VPC, tiered subnets | one product, one environment |
| VPC per environment | isolation and attribution |
| hub-and-spoke with transit | many accounts/teams, shared egress |
| shared VPC (host/service projects) | GCP estates |
| flat multi-VPC peering | up to ~5 VPCs, then unmanageable |

- Plan the CIDR allocation globally before the first VPC; overlap is unfixable
  without re-addressing.
- Reserve a /16 per environment, /20 per AZ, /24 per tier.
- Peering is non-transitive; once you need three hops, adopt a transit model.

## Decision 2 — Subnets

- Public: only load balancers and bastions. Private: everything else.
- One tier per subnet purpose (app, data, management) across AZs; same shape in
  each AZ.
- Data subnets have no route to the internet, even via NAT.
- IP exhaustion is the classic outage: /24 per tier is small for pods and Lambda
  ENIs. Size for pods, not for VMs.

## Decision 3 — Egress

- NAT gateways per AZ to avoid cross-AZ data charges and single-AZ failure.
- Most egress cost is cross-AZ chatter: colocate chatty services in one AZ, or in
  one service.
- VPC/service endpoints for cloud APIs — this removes NAT bills and dependence on
  internet paths.
- Egress allowlists at a proxy or firewall for compliance environments.

## Decision 4 — Ingress

- Public entry only through a load balancer with TLS termination and WAF.
- ALB/L7 for HTTP, NLB/L4 for performance or non-HTTP; global anycast LB for
  multi-region.
- Health checks reflect dependencies, or the balancer sends traffic to broken
  instances.
- Internal load balancers for service-to-service; no service reaching another by
  IP.

## Decision 5 — Segmentation

- Security groups / NSGs reference **identities (SG-to-SG, service accounts)**,
  never CIDR ranges you must maintain by hand.
- Default deny between tiers; open only the ports the flow needs.
- A separate management network for bastions, CI runners, and admin endpoints.
- DNS resolution across networks is part of segmentation: private zones linked to
  every network that needs them.

## Decision 6 — Diagnostics

- Flow logs on, to a searchable store, with a retention that matches incident
  needs.
- Reachability Analyzer / Network Intelligence / Connection Troubleshoot used
  before escalating — it answers "why can't A reach B" in minutes.
- Diagram the flows, not just the boxes: every arrow has a port and a reason.

## Failure modes at scale

- CIDR overlap between two environments discovered during an acquisition.
- Single NAT gateway: an AZ outage takes down all egress.
- Security groups with `0.0.0.0/0` on 22/3389 "temporarily".
- Cross-AZ chat between microservices costing more than compute.
- Pod IP exhaustion at 60% traffic growth.

## Verification receipts

1. CIDR allocation table with reserved ranges and owners.
2. Subnet/tier table per AZ, with public/private intent stated.
3. Egress diagram: NAT per AZ, endpoints, proxy, estimated monthly cost.
4. Reachability test matrix between tiers (allowed and denied).
5. Flow logs queryable, with one past incident reconstructed from them.
