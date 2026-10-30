---
name: owasp-top10-architect
description: Architect-level treatment of the OWASP Top 10 — how each class of web vulnerability shows up as an architectural defect, the controls that prevent it at design time, and what to check before shipping. Use when designing or reviewing a web application's security posture.
license: MIT
compatibility: Web applications and APIs; any stack
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/security-architect/owasp-top10-architect
  crusor-origin: original
  crusor-sources: "owasp.org/www-project-top-ten; owasp.org/www-project-cheat-sheets; owasp.org/www-project-asvs"
  crusor-triggers: "owasp, top 10, sql injection, xss, csrf, ssrf, idor, insecure deserialization, broken access control"
  crusor-verified-on: "2026-10-30"
---

# OWASP Top 10 Architect

Each entry below is a **design defect**, not a bug to patch. If the architecture
is right, the class is structurally hard to introduce.

## A01 — Broken access control

- Enforce server-side, per object, using server-owned facts.
- Never take an object id from the client and trust that it implies permission
  (IDOR).
- Deny by default; explicit allow-lists for public routes.
- Test: request another tenant's resource → 404 (not 403 with existence leak).

## A02 — Cryptographic failures

- TLS everywhere, HSTS, no mixed content.
- Passwords: Argon2id/bcrypt with per-user salt and a sane work factor — never
  SHA-256, never MD5, never a custom scheme.
- Encrypt sensitive columns at rest; keys in a KMS, not in the repo.
- Do not invent crypto; use the platform library.

## A03 — Injection

- SQL: parameterised queries only; ORMs used correctly still need care with raw
  fragments.
- HTML: framework escaping by default; `dangerouslySetInnerHTML`/`v-html` need a
  sanitiser and a reason.
- Shell: no string-built commands; pass argv arrays.
- LDAP/XPath/template injection follow the same rule: data never becomes code.

## A04 — Insecure design

- Rate limits, quotas and lockouts are design elements, not add-ons.
- Business-logic abuse (negative quantities, replaying a coupon) is a design
  test case, not a pentest finding.
- Every privileged workflow has an approval/audit path.

## A05 — Security misconfiguration

- Debug off, stack traces never returned, directory listing off.
- Default credentials and sample endpoints removed.
- Least-privilege roles for DB, storage and cloud; no `*` in production IAM.
- Environment parity: staging must not be reachable anonymously if production is
  not.

## A06 — Vulnerable components

- Lockfiles committed; audit in CI; no unpinned ranges in production.
- Remove unused dependencies; every dependency is attack surface.
- Patch SLA by severity; know what runs in your build (see
  `supply-chain-architect`).

## A07 — Identification and authentication failures

- Sessions rotated on login; cookies httpOnly/Secure/SameSite.
- Credential stuffing defences: rate limit, breached-password checks, MFA.
- Password reset tokens single-use, short-lived, bound to the account.

## A08 — Software and data integrity failures

- Verify artefacts: signed images, pinned actions, checksums for downloads.
- Deserialisation of untrusted data is forbidden (pickles, YAML `load`,
  `eval`-like parsers).
- CI credentials scoped and short-lived.

## A09 — Logging and monitoring failures

- Log auth events, access-control denials and admin actions; never log secrets,
  tokens or full PII.
- Alerts on patterns (spike in 401/403), not on individual requests.
- Retain enough to investigate; expire on a documented schedule.

## A10 — Server-side request forgery

- Any server-side fetch of a user-supplied URL is SSRF until proven otherwise:
  allow-list hosts, block private ranges, no redirects to internal addresses.
- Metadata endpoints (169.254.169.254) blocked by the network, not just the code.
- Prefer a proxy that enforces the policy centrally.

## Review checklist

1. Every new route has an explicit access-control decision.
2. Every query is parameterised; every render is escaped or sanitised.
3. Every secret is fetched, never embedded.
4. Every dependency is pinned and audited.
5. Every outbound request from the server has an allow-list.

## Verification receipts

1. Authorization matrix test per resource (A01).
2. Injection tests: SQL, HTML, shell, template.
3. Dependency audit + SAST clean in CI (A06/A03).
4. Secret scan on the repo and on build logs (A05/A02).
5. SSRF test with an internal address and a redirect chain (A10).
