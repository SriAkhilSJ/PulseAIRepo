---
name: iam-architect
description: Architect-level identity and access design in the cloud — human versus machine identities, role and permission boundaries, federation over keys, least privilege that can actually be maintained, break-glass access, and the audit trail that proves who did what. Use when designing accounts, roles, or service credentials.
license: MIT
compatibility: AWS IAM, Entra ID, GCP IAM, any OIDC federation
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/identity-architect/iam-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/IAM/latest/UserGuide; cloud.google.com/iam/docs/overview; learn.microsoft.com/entra/identity"
  crusor-triggers: "iam, roles, permissions, least privilege, service account, federation, oidc, break glass, access review, policy boundary"
  crusor-verified-on: "2026-10-30"
---

# IAM Architect

Identity is **the real perimeter**. Network controls are advisory once a credential
is stolen; the permission set is what actually limits the damage.

## When to use

- Designing roles for humans and workloads.
- Choosing between long-lived keys and federation.
- An audit or incident asks "who could have done this".

## When NOT to use

- Application-level authorization (tenant roles, feature access) → web
  `authz-models-architect`.
- Secrets storage mechanics → `secrets-management-architect`.

## Decision 1 — Identity classes

| Class | Credential | Lifetime |
|---|---|---|
| human, interactive | SSO federation | session, hours |
| human, privileged | SSO + step-up MFA | minutes |
| workload in cloud | instance/workload identity | automatic, rotated |
| workload outside cloud | OIDC federation | minutes |
| CI/CD | OIDC to provider | minutes |
| break-glass | hardware key, sealed | manual, audited |

- Static access keys are a legacy exception requiring an owner and an expiry date.
- One identity per workload — shared identities destroy attribution and blast-radius
  control.

## Decision 2 — Permission shape

- Start from deny; grant by role at the smallest scope that runs the workload.
- Use **roles with conditions** rather than wildcards: resource tags, source
  network, MFA presence, time.
- Permission boundaries / guardrails stop a role from escalating itself — the most
  important control in any delegated-admin model.
- Managed policies first, custom only with a documented reason and a review date.
- Separate planes: control-plane admin (create/delete) from data-plane access
  (read/write). Most humans need neither full-time.

## Decision 3 — Federation

- OIDC for CI: the provider issues short-lived credentials scoped to a repo/branch.
- Verify the token's audience and subject conditions — a permissive trust policy is
  an open door.
- Human access via the IdP; no local IAM users with console passwords.
- Cross-account access by role assumption with an external id, not shared keys.

## Decision 4 — Privileged access

- Break-glass role: no standing access, alert on use, credentials held outside the
  normal path, and a post-use review.
- Just-in-time elevation with approval; standing admin is the default failure.
- Session recording or command logging for production admin.
- Offboarding is automated from the IdP — a departed human's roles die with the
  account.

## Decision 5 — Audit

- Every identity action logged to an immutable store, retained per policy.
- Access reviews quarterly: unused roles, unused permissions, stale keys.
- Alert on: new admin role, policy attached to a principal, root/owner login,
  key creation.
- Attribution: the log must name the human behind the workload role when possible.

## Failure modes at scale

- One `deploy` role with `*` on `*`, used by every pipeline.
- Access keys from 2019 still active in a CI secret store.
- Trust policy accepting any repo in the org, so a fork can assume the role.
- Break-glass credentials in a shared password manager nobody audits.
- Hundreds of roles, none removable because "something might use it".

## Verification receipts

1. Identity inventory: class, credential type, rotation, owner.
2. Least-privilege check: unused-permission report with removals applied.
3. Federation trust policies reviewed for audience/subject conditions.
4. Break-glass use rehearsed and alert verified.
5. Audit log query demonstrating attribution for a sensitive action.
