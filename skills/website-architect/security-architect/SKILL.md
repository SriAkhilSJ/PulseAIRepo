---
name: security-architect
description: Architect-level security direction for web products — threat modelling before code, trust boundaries and the layers that enforce them, authentication versus authorization separation, secret and key custody, dependency risk, and the review gates that keep a system defensible as it grows. Use before any specific security skill.
license: MIT
compatibility: Web applications and APIs; any stack
metadata:
  crusor-domain: website-architect
  crusor-path: security-architect
  crusor-origin: original
  crusor-sources: "owasp.org/www-project-top-ten; owasp.org/www-project-asvs; threatmodelingmanifesto.org"
  crusor-triggers: "security, threat model, trust boundary, owasp, secure design, penetration test, vulnerability, hardening"
  crusor-verified-on: "2026-10-30"
---

# Security Architect

Security is **what the system does when someone is hostile**, not a scanner you
run at the end. Decide the boundaries first; everything else follows.

## Leaf map

| Need | Skill |
|---|---|
| the recurring classes of web vulnerability | `owasp-top10-architect` |
| who may do what, and how it is enforced | `authz-models-architect` |
| keys, tokens, credentials, rotation | `secrets-management-architect` |
| dependencies, CI, build and release integrity | `supply-chain-architect` |
| headers, CSP, cookies, client-side boundaries | `browser-security-architect` |

## Decision 1 — Threat model first

For every new surface, answer four lines:

1. What are we building, and what data does it touch?
2. What can go wrong (spoofing, tampering, disclosure, DoS, elevation)?
3. What are we going to do about each?
4. How will we know it still holds after the next release?

- If the model is empty, the design is undocumented, not secure.
- Data classification (public / internal / personal / secret) decides encryption,
  logging and retention rules — before schema design.

## Decision 2 — Trust boundaries

| Boundary | Enforced by |
|---|---|
| browser → API | authentication, input validation, CORS, CSRF |
| API → database | parameterised queries, least-privilege DB role |
| service → service | mTLS or signed tokens, not network position |
| app → third party | outbound allow-list, no secret in the client |
| operator → production | audit log, break-glass accounts, no shared root |

- Everything crossing a boundary is **untrusted** until validated at the
  receiving side.
- "Internal network" is not a control: assume an attacker inside.

## Decision 3 — Authentication ≠ Authorization

- Authentication proves identity; authorization decides access, server-side, on
  every request, using facts the server owns.
- Deny by default. A new endpoint is protected unless explicitly public.
- Least privilege for users, services and database roles alike.
- Every privileged action is auditable: who, what, when, from where.

## Decision 4 — Data handling

- Encrypt in transit (TLS everywhere, HSTS) and at rest (disk/column level for
  secrets and personal data).
- Minimise: do not collect, log or retain what the product does not use.
- Secrets never in code, logs, error messages, or client bundles.
- Backups inherit the classification of what they contain.

## Decision 5 — Failure behaviour

- Fail closed: an unavailable authorization service denies, it does not allow.
- Errors to clients are generic; details go to logs with a correlation id.
- Security events are logged separately from application logs; alerts on
  patterns, not on single failures.
- Rate limiting and account lockout with exponential delay, not permanent
  lockout (that is a DoS on your own users).

## Decision 6 — Verification

- Static analysis + dependency audit in CI on every PR.
- Authorization matrix tests per resource — these are the ones that catch real
  breaches.
- A pentest before major launches and after any auth rewrite.
- Findings have an owner and a date, or they are not findings.

## Failure modes at scale

- Authorization implemented in the UI and in a middleware, nowhere else.
- One admin database role used by every service.
- Secrets rotated never, shared in a chat, present in a build log.
- A threat model written once at kickoff and never revisited.
- Security work blocked behind feature work until an incident reprioritises it.

## Verification receipts

1. Threat model per surface, with mitigations and owners.
2. Authorization matrix test results per resource.
3. Secret inventory with rotation dates.
4. Dependency audit + SAST clean in CI.
5. Incident runbook exercised once (tabletop or real).
