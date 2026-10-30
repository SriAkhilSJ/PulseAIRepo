---
name: api-auth-architect
description: Architect-level API authentication and authorization — choosing sessions vs tokens vs OAuth2/OIDC, token lifetime and refresh strategy, scope and role models, server-side authorization boundaries, and the mistakes that leak other tenants' data. Use when designing who may call an API and how they prove it.
license: MIT
compatibility: OAuth 2.1 / OIDC; JWT; session cookies
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/api-development-architect/api-auth-architect
  crusor-origin: original
  crusor-sources: "oauth.net/2.1; openid.net/specs; draft-ietf-oauth-security-topics; owasp.org/ASVS"
  crusor-triggers: "authentication, authorization, oauth, oidc, jwt, session cookies, token refresh, rbac, authz"
  crusor-verified-on: "2026-10-30"
---

# API Auth Architect

Authentication says **who**; authorization says **what**. Conflating them is how
tenants leak into each other.

## When to use

- Designing login, sessions or tokens for an API.
- Adding roles, scopes, teams or multi-tenancy.
- Auditing an API for cross-tenant access.

## When NOT to use

- Internal-only service inside a trusted network with mTLS and no user concept —
  still document the assumption.

## Decision 1 — Mechanism by client type

| Client | Mechanism |
|---|---|
| first-party web app | httpOnly, Secure, SameSite session cookie |
| native/mobile app | OAuth2 + PKCE, short-lived access token + refresh |
| server-to-server | client credentials or mTLS |
| third-party integration | OAuth2 authorization code, scoped |
| public read-only data | API key (quota, not identity) |

- Never store tokens in `localStorage` for a browser app when cookies work.
- Implicit flow is dead; password grant is dead.

## Decision 2 — Token lifetimes

- Access token: minutes (5–15). Refresh token: days, rotating on use.
- Refresh rotation with reuse detection: a replayed old refresh token revokes
  the family.
- Logout revokes server-side; a JWT alone cannot be un-issued, so keep a
  revocation list or short lifetimes.
- Clock skew and `nbf`/`exp` validated; never trust the token's claims for
  authorization without checking the source of truth.

## Decision 3 — Authorization model

| Model | Use |
|---|---|
| RBAC | few roles, coarse permissions |
| ABAC / policy | rules over attributes (plan, region, ownership) |
| ReBAC | sharing and nested resources (documents, teams) |

- Authorization is enforced **server-side in the service layer**, on every read
  and write — not only in the controller.
- Ownership is checked against the database, never against a client-supplied id.
- Deny by default: new endpoints are protected unless explicitly public.
- Multi-tenancy: tenant id derived from the authenticated principal, never from
  the request body.

## Decision 4 — Session and cookie hygiene

- `httpOnly`, `Secure`, `SameSite=Lax` (or `Strict` for sensitive flows).
- CSRF protection for cookie-based writes (token or same-site + origin check).
- Session fixation prevented: rotate the session id on login.
- Idle and absolute timeouts; concurrent session policy decided.

## Decision 5 — Secrets and keys

- Signing keys rotated with a published JWKS; `kid` in the header.
- Client secrets never shipped to browsers; PKCE replaces them for public
  clients.
- Redirect URIs allow-listed exactly — no wildcards, no open redirects.
- Audit log for auth events: login, failure, revocation, permission change.

## Failure modes at scale

- Authorization only in the UI/middleware → API-level bypass.
- JWT with a long expiry and no revocation → compromised tokens valid for days.
- Tenant id taken from a header or body parameter.
- Refresh tokens without rotation → replayable indefinitely.
- Admin check by email string in code.

## Verification receipts

1. Auth flow diagram (client → IdP → API) reviewed.
2. Authorization matrix test per resource: anonymous, other user, member, admin.
3. Cross-tenant test: request another tenant's resource id → 404/403.
4. Token tests: expired, tampered, revoked, wrong audience.
5. Cookie/CSRF configuration verified in a real browser session.
