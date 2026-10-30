---
name: helm-architect
description: Architect-level Helm design — chart structure and values schema, templating discipline that does not become a programming language, releases and rollback semantics, chart versioning and distribution, and the boundary between chart defaults and environment configuration. Use when Kubernetes manifests must be packaged and parameterised.
license: MIT
compatibility: Helm 3, OCI registries; analogous to Kustomize
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/platform-architect/helm-architect
  crusor-origin: original
  crusor-sources: "helm.sh/docs; helm.sh/docs/chart_best_practices; helm.sh/docs/topics/chart_repository"
  crusor-triggers: "helm, chart, values.yaml, helm template, kustomize, release rollback, chart versioning, helm hooks, oci chart"
  crusor-verified-on: "2026-10-30"
---

# Helm Architect

Helm is **a template engine plus a release ledger**. Both halves matter: a chart
nobody can read and a release history nobody can roll back are separate failures.

## When to use

- Shipping the same workload to many environments or customers.
- Third-party software distribution as charts.
- Versioned application packaging on Kubernetes.

## When NOT to use

- One environment, one app: plain manifests plus Kustomize are simpler.
- Complex conditional logic — that is a sign the values model is wrong.

## Decision 1 — Chart shape

```
chart/
  Chart.yaml           name, version, appVersion
  values.yaml          documented defaults only
  values.schema.json   typed validation
  templates/           no logic beyond substitution
  crds/                installed before templates
```

- One chart per deployable, not one mega-chart per platform (unless it is a true
  umbrella with independent subcharts).
- Library charts for shared helpers, imported with an alias.
- `values.schema.json` turns a typo into a validation error instead of a broken
  deploy.

## Decision 2 — Values

- Defaults must run the app locally-ish (small resources, no external deps
  required to template).
- Environment values live in the environment's repo/GitOps path, not in the chart.
- No `if` trees over `values.env == "prod"`. Pass explicit values instead.
- Names: `service.replicaCount`, `ingress.enabled`, `resources.limits.memory` —
  consistent across every chart in the org.
- Secrets referenced by name from an external secret store; never in values.

## Decision 3 — Templates

- `include`/`template` with `nindent`; no nested one-liners that nobody can debug.
- Fail fast: `required` on mandatory values, `fail` on impossible combinations.
- Helpers for labels/annotations so every resource carries the same metadata.
- Immutable-ish fields: `checksum/config` annotations to trigger restarts on config
  change.
- Never `helm install --set` in production; that is unversioned configuration.

## Decision 4 — Releases

- Release name = service name; namespace = environment. One release per workload.
- `helm upgrade --install --atomic --wait` in pipelines: failures roll back rather
  than leaving a half-applied release.
- Understand that rollback restores manifests, not data — migrations need their own
  strategy.
- Revision history kept for the retention window; a release with 200 revisions is
  usually a sign of a stuck pipeline.
- Hooks (`pre-install`, `post-upgrade`) for migrations and smoke tests, with
  timeouts and idempotent jobs.

## Decision 5 — Distribution

- Charts in an OCI registry, signed where supported; versioned semantically.
- `appVersion` and `version` are different things: chart changes vs app changes.
- Keep a `values` reference in the chart README; generated docs beat tribal memory.

## Failure modes at scale

- Chart with 60 `if` branches; nobody can predict the rendered output.
- `latest` chart version in a pipeline; two clusters run different code silently.
- Values containing production secrets in a git repo.
- Rollback attempted after a migration; the schema no longer matches the old chart.
- Hooks that run every upgrade without idempotency, duplicating data.

## Verification receipts

1. `helm lint` and `helm template` diffs reviewed in CI for each environment.
2. Values schema rejects an invalid input in a test.
3. Atomic upgrade demonstrated with an injected failure and automatic rollback.
4. Chart version and appVersion policy documented and followed.
5. Registry holds signed, versioned charts; a rollback to the previous version
   exercised.
