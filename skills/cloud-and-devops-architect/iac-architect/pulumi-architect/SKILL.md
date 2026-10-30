---
name: pulumi-architect
description: Architect-level Pulumi design — real-language infrastructure with types and tests, stack and project structure, state backends and secrets providers, component resources as reusable abstractions, and the policy and review practices that keep programmatic IaC safe. Use when infrastructure is written in TypeScript/Python/Go rather than HCL.
license: MIT
compatibility: Pulumi; analogous to CDK/CDKTF
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/iac-architect/pulumi-architect
  crusor-origin: original
  crusor-sources: "pulumi.com/docs; pulumi.com/docs/iac/concepts; pulumi.com/docs/using-pulumi/testing"
  crusor-triggers: "pulumi, infrastructure as code in typescript, stack config, component resource, cdk, cdk for terraform, programmatic iac"
  crusor-verified-on: "2026-10-30"
---

# Pulumi Architect

Pulumi trades **declarative configurability for real programming**. That buys tests,
abstractions, and loops — and buys you every way a program can go wrong.

## When to use

- The team is stronger in TS/Python/Go than in HCL.
- Infrastructure needs loops, conditionals, and shared libraries beyond what HCL
  modules allow.
- You want unit tests over infrastructure logic.

## When NOT to use

- The org already runs Terraform at scale; consistency beats preference.
- The team has no programming discipline — programs with side effects are riskier.

## Decision 1 — Project and stacks

```
infra/
  Pulumi.yaml            project
  Pulumi.prod.yaml       stack config
  index.ts               entry point
  components/            component resources
  tests/
```

- One project per bounded system; stacks per environment.
- Config via stack files and `pulumi config set --secret`; never hardcoded.
- State backend: Pulumi Cloud or a self-managed S3/GCS backend with encryption and
  locking. Never local state for shared systems.

## Decision 2 — Component resources

- Wrap multi-resource patterns (a service with its bucket, role, alarms) into a
  component with a typed input/output interface.
- Components hide provider detail from app teams, but must expose the handles
  teams need (URLs, names, ARNs).
- Version components; app teams pin the version like any dependency.
- Avoid deep inheritance; composition with clear inputs beats subclassing.

## Decision 3 — Correctness

- `preview` is mandatory in review; a diff must be read, not just approved.
- Protect stateful resources (`protect: true`) and use `retainOnDelete` for data
  stores.
- Explicit dependencies where implicit ones are not captured by output references
  (a policy attached after a bucket).
- Idempotent programs: no random names with side effects, no calls to live APIs
  that change per run unless required.
- Unit tests with mocked providers for logic; ephemeral stacks for integration.

## Decision 4 — Secrets

- Encrypted secrets in config or an external provider (Vault/AWS KMS); `--secret`
  for anything sensitive.
- Secrets never in outputs consumed by logs; mark outputs secret.
- CI uses OIDC-federated credentials, no long-lived keys.

## Decision 5 — Policy and guardrails

- CrossGuard (or equivalent) policies as code: required tags, denied instance
  types, no public buckets — enforced at preview.
- Policy packs versioned with the platform repo.
- Drift detection scheduled; a console change is a review item, not a state of
  nature.

## Failure modes at scale

- Ten projects each re-implementing the same VPC; no shared component.
- A program that queries the live environment, so preview does not match apply.
- Local state on a laptop, two engineers, one lost database.
- `retainOnDelete` missing; a stack destroy wipes a production bucket.
- Policy pack too strict, everyone uses the escape hatch, and it means nothing.

## Verification receipts

1. Project/stack inventory with backend and encryption.
2. Component library list with versions used per stack.
3. Preview output reviewed for a real change, including a destructive one.
4. Policy pack enforced at preview with a deliberate violation blocked.
5. Drift report from a scheduled check.
