---
name: secrets-and-keys-architect
description: Architect-level secrets management — secret stores and their hierarchy, rotation without downtime, envelope encryption with KMS/HSM, key custody and destruction, environment and CI secret injection, and the leak-detection path that catches what escapes. Use when credentials, tokens, or encryption keys must be handled by systems.
license: MIT
compatibility: AWS Secrets Manager/KMS, GCP Secret Manager, Azure Key Vault, Vault, SOPS
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/identity-architect/secrets-and-keys-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/secretsmanager; cloud.google.com/secret-manager/docs; developer.hashicorp.com/vault/docs"
  crusor-triggers: "secrets management, vault, kms, key rotation, envelope encryption, secret manager, api keys, key custody, hsm, leaked secret"
  crusor-verified-on: "2026-10-30"
---

# Secrets & Keys Architect

Secrets fail in two ways: **they leak, or they cannot be rotated**. Every design
decision here is about making both cheap.

## When to use

- Application credentials, API keys, signing keys, database passwords.
- Encryption at rest with customer-managed keys.
- A leak has happened or is suspected.

## When NOT to use

- Human identity and permissions → `iam-architect`.
- Mobile/web client token storage → mobile or web security books.

## Decision 1 — Store

| Store | Fit |
|---|---|
| cloud secret manager | default; IAM-scoped, audited, versioned |
| Vault | multi-cloud, dynamic credentials, PKI |
| KMS/HSM | encryption keys, never raw app secrets |
| SOPS + repo | config encrypted at rest, bootstrapped by a key |
| env vars / files | delivery mechanism only, never the store |

- Secrets never live in git, images, Terraform state in plaintext, or CI logs.
- One secret per credential per environment; sharing a secret across services
  makes rotation a coordination project.

## Decision 2 — Access

- Workload identity reads its own secrets; no human reads production secrets
  routinely.
- Path/namespace per service, policy scoped to the identity.
- Every read is audited; alert on access from an unexpected identity or region.
- Prefer short-lived dynamic credentials (Vault database engine, IAM auth) over
  static passwords where the system supports it.

## Decision 3 — Rotation

- Rotation is designed in, with two valid credentials during cutover.
- Automated rotation where the provider supports it (database, cloud keys);
  scheduled and monitored where it does not.
- Consumers re-read the secret or watch for change; a restart requirement is an
  outage waiting for a schedule.
- Test rotation in staging on every change of the rotation job — a broken rotator
  is discovered at 3 a.m. otherwise.

## Decision 4 — Encryption keys

- Envelope encryption: data key per object/tenant, wrapped by a KMS key.
- Key hierarchy: root/HSM → KMS key → data keys; permissions narrow at each level.
- Separate keys per environment and, where required, per tenant (crypto-shredding
  becomes deleting one key).
- Key destruction is irreversible: require a waiting period, dual approval, and a
  backup decision recorded.

## Decision 5 — Delivery to workloads

- Injected at runtime via the platform's identity (IRSA, workload identity,
  managed identity), not baked into images.
- CI/CD gets short-lived credentials by OIDC; no long-lived deploy keys.
- Local development uses a dev-only store; never a copy of production secrets.
- Secret changes do not require an image rebuild.

## Decision 6 — Detection

- Scan repos and images for secret patterns; block the merge, not just alert.
- Alert on a secret appearing in logs or error trackers.
- Leak response runbook: revoke → rotate → audit access → notify. Revoke first.
- Assume a leaked secret was used; check the audit trail.

## Failure modes at scale

- Database password in a Helm values file, committed and rotated never.
- KMS key deleted to "clean up"; encrypted backups unrecoverable.
- Rotation job fails silently for a year, then the password expires.
- One shared secret across 30 services; rotation requires a coordinated freeze.
- Secret in a CI log line, discovered months later by a third party.

## Verification receipts

1. Secret inventory: name, owner, consumers, rotation cadence.
2. Rotation executed live with zero downtime observed.
3. KMS key hierarchy diagram with policies per level.
4. Leak scan wired into CI, proven by a deliberate test secret.
5. Leak drill: revoke and rotate completed within the target time.
