---
name: mlops-architect
description: Architect-level ML platform design — reproducible training pipelines, feature stores and point-in-time correctness, model and data versioning, registries and promotion, shadow and canary deployment, and drift monitoring that connects production behaviour back to data. Use when models are trained, retrained, and operated rather than just called.
license: MIT
compatibility: MLflow, Kubeflow, SageMaker Pipelines, Vertex AI, Feast, DVC
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/mlops-architect
  crusor-origin: original
  crusor-sources: "mlflow.org/docs; docs.feast.dev; cloud.google.com/vertex-ai/docs; martinfowler.com/articles/cd4ml.html"
  crusor-triggers: "mlops, model training, feature store, model registry, retraining, model versioning, experiment tracking, training pipeline, deployed model, churn prediction, train a model, tabular model, classic ml, feature engineering, churn, model degraded, model got worse, data drift, retrain"
  crusor-verified-on: "2026-10-30"
---

# MLOps Architect

A model in production is **a pipeline artefact with a shelf life**. The platform's
job is to make "which data, which code, which weights, which config" answerable
at any moment, for any deployed model.

## When to use

- Models are trained or fine-tuned in-house and retrained on a cadence.
- Multiple teams share features, models, or serving infrastructure.
- Auditing "why did the model change" is required.

## When NOT to use

- You only call a third-party API — that needs `llm-app-architect` and
  `evals-architect`, not a training platform.
- One notebook, one offline analysis, never deployed.

## Decision 1 — Reproducibility spine

Every training run records: code commit, data snapshot id, hyperparameters,
environment image, random seeds, and output artefact hash. Missing any one of
these makes the run unreproducible and the model unauditable.

- Data versioning by immutable snapshot (DVC / lake commit / table version).
- Environments as containers, pinned.
- Experiments tracked centrally; notebooks are not the record.

## Decision 2 — Pipelines

| Stage | Contract |
|---|---|
| ingest | validated schema, quarantined bad rows |
| transform | pure, versioned, testable on samples |
| train | deterministic given inputs+seed |
| evaluate | gates vs baseline on a held-out set |
| register | artefacts + metadata + lineage |
| deploy | promoted by a human or an automated gate |

- Orchestrate with retries, idempotent steps, and per-step artifact handoff.
- Schedule retraining on a trigger (drift, new data volume, calendar), not vibes.
- Backfill must be possible and idempotent — the pipeline will need to re-run.

## Decision 3 — Features

- A feature store earns its cost when the same feature is used by training and
  serving and must not diverge.
- **Point-in-time correctness**: training features must reflect what was knowable
  at prediction time. Leakage from the future is the most expensive silent bug in
  ML.
- Online/offline parity is tested, not assumed: same definition, same value.
- Feature ownership and SLAs are named, like any other service.

## Decision 4 — Registry and promotion

- Registry holds model versions with: metrics, eval report, training data lineage,
  signature, and approval state.
- Promotion is a state machine: staging → shadow → canary → production, with
  automatic rollback on metric breach.
- Serving reads a version, never `latest`.
- Keep the last N production versions servable for instant rollback.

## Decision 5 — Deployment patterns

- **Shadow**: run the candidate on live traffic without serving its output.
- **Canary**: small traffic slice with guardrail metrics.
- **A/B**: business metric comparison, requires statistical power.
- Batch scoring for non-real-time use cases; do not force everything online.

## Decision 6 — Monitoring

- Data drift on inputs (distribution shift), not just accuracy.
- Prediction drift and calibration; delayed labels arrive late, so use proxies.
- Performance, latency, error rate, and per-segment quality — a model can be good
  overall and broken for one cohort.
- Alerts route to the model owner with the run id attached.

## Failure modes at scale

- Feature computed differently online and offline; offline metrics are fiction.
- "Latest" tag in production serving an untested model.
- Retraining silently changes the label definition.
- No baseline stored, so "better" cannot be proven.
- Drift alarms nobody owns, muted within a month.

## Verification receipts

1. One run reproduced end to end from its recorded metadata.
2. Leakage test: point-in-time join verified against a known historical row.
3. Online/offline feature parity test in CI.
4. Rollback exercised from production to the previous registry version.
5. Drift monitor wired with an owner, threshold, and a past alert.
