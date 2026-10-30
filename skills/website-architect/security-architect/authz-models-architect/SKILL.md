---
name: authz-models-architect
description: Architect-level authorization modelling — choosing RBAC, ABAC or ReBAC for a domain, where policy is evaluated, relationship and tenant modelling, and the enforcement points that stop privilege escalation across a product. Use when permissions outgrow a boolean on the user row.
license: MIT
compatibility: Framework-agnostic; policy engines (OPA/Cedar) optional
metadata:
  crusor-domain: website-architect
  crusor-path: security-architect/authz-models-architect
  crusor-origin: original
  crusor-sources: "owasp.org/www-project-authorization-cheat-sheet; openpolicyagent.org/docs; docs.cerbos.dev"
  crusor-triggers: "rbac, abac, rebac, permissions, roles, policy, fine grained authorization, multi tenant, privilege escalation"
  crusor-verified-on: "2026-10-30"
---

# Authorization Models Architect

Authorization is **a model of the business**, not a table of booleans. Pick the
model the domain actually has, or every new feature becomes a permission patch.

## When to use

- Roles are multiplying, or "can this user do X" is answered in five places.
- Adding teams, sharing, orgs, or multi-tenancy.
- An authorization bug let someone see another tenant's data.

## When NOT to use

- A two-role internal tool — one enum and a guard is enough, and the model below
  is over-engineering.

## Decision 1 — Choose the model

| Domain shape | Model |
|---|---|
| few global roles (admin, staff, customer) | RBAC |
| rules over attributes (plan, region, clearance, time) | ABAC |
| sharing and nested resources (docs, folders, teams) | ReBAC (Zanzibar-style) |
| per-resource custom permissions | ACL with an owner |

- Mixed domains exist: RBAC for the admin surface, ReBAC for customer content is
  normal — document which applies where.
- Roles grant **capabilities**, never specific records. "editor of document 42"
  is a relationship, not a role.

## Decision 2 — Where policy is evaluated

```
edge/authn  → who is this? (session/token)
service     → may this subject do this action on this resource?
data        → tenant/row scoping as a second net (RLS, query filters)
```

- The service layer is where the business rule lives; the database scoping is a
  backstop, not the only control.
- Centralise the check in one function/policy module per domain; scattered
  `if (user.role === 'admin')` is how holes appear.
- Deny by default; unknown action or resource → deny.

## Decision 3 — Object-level checks

- Every access is `(subject, action, resource)` — all three, never just the
  subject.
- Fetch the resource with tenant/owner scoping in the query itself
  (`WHERE tenant_id = $1 AND id = $2`), so "not found" and "not yours" are the
  same answer.
- List endpoints filter by the same rule as detail endpoints — the classic leak
  is a detail check that the list forgets.
- Batch/bulk operations check each item, not just the request.

## Decision 4 — Modelling relationships

- Store edges explicitly (memberships, shares) with their own attributes
  (role on that resource, expiry).
- Denormalised permission caches must have a rebuild path and an invalidation
  event.
- Explicit deny beats allow; delegation has a scope and an expiry.
- Superadmin is a break-glass path: audited, time-boxed, never a normal role.

## Decision 5 — Policy as code

- Policy files (OPA/Cedar/your own DSL) live in the repo, are tested like code,
  and are reviewed by whoever owns the domain.
- A policy test suite covers: allowed cases, denied cases, cross-tenant cases.
- Policy changes ship with a decision log entry, not silently.

## Failure modes at scale

- Role explosion: 60 roles because teams needed slightly different access.
- Authorization in the UI plus a middleware that only checks "logged in".
- Detail endpoint scoped, list endpoint not.
- Tenant id read from the request body.
- Permission cache never invalidated after a role change.

## Verification receipts

1. Model documented: which domain uses RBAC/ABAC/ReBAC and why.
2. Authorization matrix test per resource × action × subject class.
3. Cross-tenant test on list **and** detail endpoints.
4. Policy test suite run in CI.
5. Audit trail for privileged and denied actions.
