---
name: azure-architect
description: Architect-level Azure design — management groups and subscriptions, Entra ID as the identity plane, hub-and-spoke networking, AKS versus App Service versus Container Apps, and the governance layers (policy, blueprints, cost management) that hold an Azure estate together. Use when building on Microsoft Azure.
license: MIT
compatibility: Microsoft Azure, Entra ID
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/providers-architect/azure-architect
  crusor-origin: original
  crusor-sources: "learn.microsoft.com/azure/cloud-adoption-framework; learn.microsoft.com/azure/architecture/guide"
  crusor-triggers: "azure, entra id, aks, azure app service, container apps, management group, azure architect, microsoft cloud"
  crusor-verified-on: "2026-10-30"
---

# Azure Architect

Azure is **an enterprise identity product with compute attached**. Most designs
succeed or fail on subscription structure and Entra ID, not on the service list.

## When to use

- Designing an Azure landing zone or subscription model.
- Choosing between AKS, App Service, Container Apps, and Functions.
- Enterprise integration: hybrid, ExpressRoute, Entra-based access.

## When NOT to use

- Greenfield with no Microsoft relationship and no Windows/.NET estate — compare
  providers honestly first.
- Multi-cloud abstraction → domain crown.

## Decision 1 — Structure

```
Tenant (Entra ID)
  Management groups     platform / landing zones / sandbox / decommissioned
    Subscriptions       per workload or per environment
      Resource groups   per lifecycle boundary
```

- Subscriptions are the quota and policy boundary; management groups are the
  inheritance path. Do not flatten them.
- Resource groups group by **lifecycle**, not by type — everything in one group
  shares a deploy/delete fate.
- Platform subscription holds connectivity (hub VNet), identity, and shared
  services; workloads live in their own.

## Decision 2 — Identity

- Entra ID is the control plane for everything: RBAC, managed identities,
  Conditional Access.
- **Managed identities** for service-to-service; client secrets and connection
  strings in app settings are a last resort and a leak waiting to happen.
- Role assignments at the highest sensible scope; PIM for privileged roles.
- Conditional Access and MFA are architecture, not IT policy: they decide what
  hybrid and remote access can look like.
- On-prem AD integration: Entra Connect with a stated sync model, not ad-hoc.

## Decision 3 — Network

- Hub-and-spoke: hub holds ExpressRoute/VPN, firewall, DNS, shared services;
  spokes peer in and never peer sideways without a firewall.
- Azure Firewall or a NVA for egress inspection; NSGs at subnet level.
- Private Endpoints for PaaS — a service with a public endpoint and a private one
  is public, whatever the docs say.
- Private DNS zones linked to every spoke VNet; without them, private endpoints
  resolve publicly and break.
- ExpressRoute for predictable hybrid bandwidth; VPN for smaller sites.

## Decision 4 — Compute choice

| Workload | Choice |
|---|---|
| container, full Kubernetes API | AKS |
| container, HTTP, scale-to-zero | Container Apps |
| web app, minimal ops, Windows/.NET | App Service |
| event/queue functions, short work | Functions (consumption or premium) |
| lift-and-shift VM estate | VMs + Azure Migrate |

- AKS needs a node pool strategy, CNI choice (Azure CNI vs kubenet/overlay), and
  an ingress plan before day one.
- App Service: deployment slots for staging swaps; plan tier decides features.
- Functions: consumption has cold starts and long-running limits; premium when
  latency matters.

## Decision 5 — Data and integration

- Azure SQL / PostgreSQL Flexible Server as the relational default; Cosmos DB only
  when its consistency and partition model fit the access pattern.
- Storage accounts: hierarchical namespace for data-lake workloads, private
  endpoints, and a lifecycle policy.
- Service Bus for enterprise messaging (sessions, dead-letter); Event Hubs for
  streaming; Event Grid for reactive events.
- API Management as the front door when policies (rate limits, auth, transforms)
  must be enforced centrally.

## Decision 6 — Governance and cost

- Azure Policy at management-group level: allowed regions, required tags, denied
  public IPs, enforced private endpoints.
- Blueprints/Bicep templates for every landing zone; portal-built infrastructure
  is drift by definition.
- Cost Management: budgets per subscription, tag inheritance, reservations for
  steady load, and auto-shutdown for non-prod.
- Defender for Cloud for posture; fix critical findings as part of delivery.

## Failure modes at scale

- One subscription for the whole company; quota exhaustion blocks a launch.
- Service principals with client secrets committed to a repo.
- Private endpoint created, DNS zone not linked; the app still uses the public IP.
- Sideways VNet peering bypassing the firewall.
- EA spend discovered at renewal because no one owned cost reporting.

## Verification receipts

1. Management-group/subscription diagram with policy assignments per scope.
2. Identity inventory: managed identities everywhere, zero client secrets in code.
3. Hub-and-spoke diagram with peering, firewall, and DNS zone links.
4. Policy compliance report with exceptions justified.
5. Cost report by subscription and tag, with budgets and alerts configured.
