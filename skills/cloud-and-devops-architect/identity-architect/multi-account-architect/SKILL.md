---
name: multi-account-architect
description: Architect-level account and project structure — landing zones, environment and workload separation, centralized logging and billing, guardrails applied by policy, and the account vending workflow that keeps a growing estate consistent. Use when an estate spans more than a handful of accounts or projects.
license: MIT
compatibility: AWS Organizations, GCP folders, Azure management groups
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/identity-architect/multi-account-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/organizations; cloud.google.com/resource-manager/docs/creating-managing-folders; learn.microsoft.com/azure/governance/management-groups"
  crusor-triggers: "multi account, landing zone, account vending, organizations, control tower, environment separation, guardrails, scp, shared services, separate accounts, account per environment, account structure"
  crusor-verified-on: "2026-10-30"
---

# Multi-Account Architect

Accounts are **blast-radius and billing boundaries you get for free**. The design
question is which boundary each workload deserves, and how new ones are created.

## When to use

- More than a couple of teams or environments share a cloud.
- Compliance requires separation of production data.
- Billing attribution is contested.

## When NOT to use

- A single-product startup with one environment and a small team — one account is
  honest.

## Decision 1 — Structure

```
Organization/Tenant
  Root guardrails (policy, MFA, deny-leaving)
  ├── Security      log archive, audit, break-glass
  ├── Infrastructure network hub, DNS, CI runners, registry
  ├── Workloads
  │     prod-<product> / staging-<product> / dev-<product>
  └── Sandbox       capped spend, no production data
```

- Environments in separate accounts: prod credentials cannot touch staging data,
  and a quota problem stays contained.
- A shared **log archive** account is written to by everything, read by almost
  nobody.
- Sandbox accounts have hard budget caps and no network path to prod.

## Decision 2 — Guardrails

| Layer | Control |
|---|---|
| org/root | deny disabling audit, deny leaving org, region allowlist |
| OU/folder | required tags, denied public buckets, no root keys |
| account | baseline roles, logging, backup policy |
| workload | least privilege, private networking |

- Preventive controls (SCP/policy) beat detective ones; a detection after a public
  bucket exists is a post-mortem.
- Every guardrail has an owner and an exception process with an expiry.

## Decision 3 — Account vending

- One pipeline creates accounts: baseline IaC, logging wired, budgets, tags,
  identity federation, and a documented owner.
- No portal-created accounts; unvended accounts are invisible to governance.
- Naming convention encodes purpose: `<env>-<product>-<region>`.
- Decommissioning is also a workflow: data retained then destroyed, account
  closed, DNS handed back.

## Decision 4 — Shared services

- Centralised: DNS, transit network, container registry, artifact store, log
  archive, CI runners.
- Consumed across accounts by **role assumption**, never by copying credentials.
- A shared service needs an SLO and an owner; otherwise it becomes everyone's
  excuse.

## Decision 5 — Cost and audit

- Billing consolidated at the org with tags for product/env; budgets per account.
- Cost anomalies route to the account owner, not the platform team.
- Baseline: CloudTrail/audit logs to the archive account with object lock;
  config/history enabled centrally.
- Quarterly review: unused accounts, unowned resources, expiring exceptions.

## Failure modes at scale

- 200 accounts, 40 created by hand, half without logging.
- SCP blocking a legitimate action, silently — discovered during an incident.
- Sandbox account with a route into production networking.
- Cost spike untraceable because 60 accounts share one tag-less billing view.
- An account owner leaves; nobody knows what the account does.

## Verification receipts

1. OU/folder tree with the policy attached at each level.
2. Vending pipeline run: new account created fully compliant in one pass.
3. Guardrail test: each preventive control proven by an attempted violation.
4. Shared-service inventory with owner and SLO.
5. Billing report by account and tag, with budget alerts configured.
