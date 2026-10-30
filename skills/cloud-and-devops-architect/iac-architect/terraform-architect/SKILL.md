---
name: terraform-architect
description: Architect-level infrastructure-as-code guidance — module and state topology, environment separation, plan review discipline, drift and import handling, and the provider and secret pitfalls that make IaC dangerous at scale. Use when infrastructure is declared in Terraform.
license: MIT
compatibility: Terraform 1.6+ / OpenTofu; any provider
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/iac-architect/terraform-architect
  crusor-origin: original
  crusor-sources: "developer.hashicorp.com/terraform; opentofu.org/docs"
  crusor-triggers: "terraform, opentofu, iac, state file, modules, plan apply, drift, hcl"
  crusor-verified-on: "2026-10-30"
---

# Terraform Architect

Terraform is **a state machine over real infrastructure**. Everything painful
about it traces back to state: where it lives, who can change it, and whether it
still describes reality.

## When to use

- Declaring cloud infrastructure, DNS, IAM, or platform resources.
- Environments drift between plan runs.
- Migrating from console-managed infrastructure.

## When NOT to use

- Application deployment (that is a pipeline, see `ci-cd-architect`).
- One-off experiments — but import them or delete them, don't leave orphans.

## Decision 1 — State topology

- Remote backend with locking (S3+DynamoDB, GCS, Terraform Cloud).
- **One state per environment and per blast-radius group**; a single giant state
  makes every change risky and slow.
- State is sensitive (it holds secrets) — restrict access, encrypt at rest.
- Never edit state by hand; use `import`, `moved` blocks, and `state rm`
  deliberately.

## Decision 2 — Module design

- Modules are inputs → resources → outputs, versioned and referenced by tag.
- No provider configuration inside modules; the root sets providers.
- A module should not assume naming conventions of its consumer — accept a
  prefix.
- Composition over giant modules: small modules wired at the root are easier to
  change than a 2,000-line "platform" module.

## Decision 3 — Environment separation

| Approach | Trade-off |
|---|---|
| separate directories per env | explicit, some duplication |
| workspaces | shared code, easy to apply to the wrong env |
| terragrunt/atmos layering | powerful, another tool to learn |

- Prefer explicit directories or generated layering; workspaces hide which
  environment you are in.
- Same modules everywhere; differences only in variables and tfvars.

## Decision 4 — Plan discipline

- `plan` in CI on every PR, output posted for review.
- `apply` only from the pipeline, only for the merged commit.
- `-target` is an incident tool, not a workflow; it leaves drift.
- Destructive changes (`replace`, `destroy`) require explicit human approval and
  a stated data impact.
- Drift detection scheduled daily; unexplained drift is an incident.

## Decision 5 — Secrets and providers

- No secrets in `.tf` or tfvars committed; use a secret manager data source.
- Provider credentials via OIDC federation to CI, not static keys.
- Pin provider versions; unpinned providers break plans months later.
- `sensitive = true` on outputs, and never echo them into logs.

## Failure modes at scale

- One state for everything: one bad plan touches network and DNS together.
- Workspaces applied to production by mistake.
- Manual console fixes that the next apply silently reverts.
- Secrets committed in tfvars, still in git history.
- Provider upgrade breaking the plan the week of a release.

## Verification receipts

1. State inventory: backend, locking, who can access, which resources.
2. Plan review in CI with approval recorded for destructive changes.
3. Drift report from a scheduled run.
4. Module inventory with versions and consumers.
5. Provider/credential audit: pinned versions, OIDC, no static keys.
