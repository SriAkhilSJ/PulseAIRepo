---
name: secrets-management-architect
description: Architect-level secret handling — what counts as a secret, custody and injection at runtime, rotation and revocation, per-environment isolation, and the leak paths (logs, bundles, build caches, CI) that expose credentials. Use when a project stores API keys, tokens or credentials.
license: MIT
compatibility: Any stack; vault/KMS/cloud secret managers
metadata:
  crusor-domain: website-architect
  crusor-path: security-architect/secrets-management-architect
  crusor-origin: original
  crusor-sources: "owasp.org/www-project-secrets-management-cheat-sheet; 12factor.net/config; cloud provider KMS docs"
  crusor-triggers: "secrets, api keys, secret manager, vault, kms, rotation, credentials, leaking keys, dotenv, environment variables"
  crusor-verified-on: "2026-10-30"
---

# Secrets Management Architect

A secret is **anything whose disclosure grants access**. The architecture
question is: who can read it, how does it arrive, and how is it replaced?

## When to use

- Wiring credentials into an app, CI, or a deploy pipeline.
- A key leaked (logs, repo, browser bundle, screenshot).
- Designing rotation, environments, or third-party integrations.

## When NOT to use

- Public configuration (feature flags, API base URLs) — that is config, not a
  secret, and treating it as one adds friction for nothing.

## Decision 1 — Inventory first

- List every secret: what it grants, who reads it, where it lives, when it
  rotates, blast radius if leaked.
- Classify: application secret / user credential / signing key / infrastructure
  credential.
- A secret with no owner is a secret that never rotates.

## Decision 2 — Custody

| Need | Store |
|---|---|
| cloud-native app | provider secret manager (parameter store/KMS-backed) |
| multi-cloud / on-prem | Vault (or equivalent) |
| CI/CD | pipeline secret store, scoped per environment |
| local dev | git-ignored `.env` with **non-production** credentials |

- Never in git — not in history, not in a "temporary" commit, not in a fixture.
- Never in a client bundle: anything shipped to the browser is public (see
  `browser-security-architect`).
- Never in logs, stack traces, error responses, or analytics.

## Decision 3 — Injection at runtime

- Secrets arrive as environment variables or a mounted file, injected by the
  platform at start — not fetched from a hard-coded URL with a hard-coded key.
- Fail fast: missing secret → process refuses to start, no insecure default.
- Least privilege: each service gets its own credential, scoped to what it needs.
- Rotate by deploying a new credential alongside, then removing the old — never
  a big-bang swap at midnight.

## Decision 4 — Rotation and revocation

- Signing keys: JWKS with `kid`, overlap window, old key retired after TTL.
- Database credentials: rotate on a schedule; connection pools refreshed.
- Third-party keys: rotation documented with the vendor's process, tested once.
- Revocation path exists and is exercised: "if this leaks at 2am, what do we
  run?"

## Decision 5 — Leak detection

- Pre-commit secret scanning; CI scan on full history for new repos.
- Log redaction as a library-level default (fields named `password`, `token`,
  `authorization`, `cookie`).
- Alert on secret-like strings in PRs and in build output.
- When a leak happens: revoke first, then investigate, then rotate everything in
  the blast radius.

## Failure modes at scale

- `.env` committed "just for the demo", still in history three years later.
- One shared credential used by six services — cannot rotate without a full
  outage.
- `NEXT_PUBLIC_`-style variables carrying a private key into the browser.
- Secrets printed in a debug log line during an incident.
- No revocation runbook; the team discovers rotation is untested in the middle
  of an incident.

## Verification receipts

1. Secret inventory with owner, location, rotation date, blast radius.
2. Repo + history scan clean (gitleaks/trufflehog).
3. Startup test: missing secret → boot failure, no fallback.
4. Log-redaction test: a request with an auth header produces no token in logs.
5. Rotation drill executed once per secret class.
