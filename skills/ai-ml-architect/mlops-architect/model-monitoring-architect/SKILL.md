---
name: model-monitoring-architect
description: Architect-level production model monitoring — input drift, prediction drift, delayed-label evaluation, per-segment performance, shadow deployment and feedback capture, and the alerting that says "the model is wrong" rather than "latency rose". Use when a model is live and nobody knows if it still works.
license: MIT
compatibility: Evidently, WhyLabs, Arize, custom metrics
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/mlops-architect/model-monitoring-architect
  crusor-origin: original
  crusor-sources: "evidentlyai.com/docs; docs.arize.com; cloud.google.com/vertex-ai/docs/model-monitoring"
  crusor-triggers: "model monitoring, data drift, prediction drift, model decay, shadow deployment, feedback loop, model performance, drift alert"
  crusor-verified-on: "2026-10-30"
---

# Model Monitoring Architect

Model monitoring answers **"is the model still right?"** — not "is the service up".
Those are different systems, and only one of them shows model decay.

## When to use

- A model's predictions drive decisions in production.
- A retraining schedule exists and its trigger needs evidence.
- A model silently degraded and nobody noticed for weeks.

## When NOT to use

- The model is stateless, deterministic, and covered by normal tests.
- You have no ground truth and no proxies — establish a feedback path first.

## Decision 1 — What to monitor

| Layer | Signal |
|---|---|
| inputs | distribution drift vs training baseline |
| predictions | score distribution, class mix, confidence |
| outcomes | accuracy once labels arrive; proxies until then |
| segments | per-cohort performance, not just aggregate |
| business | conversion, rejection rate, manual overrides |

- Aggregate health hides a segment that is broken — always monitor by cohort.
- A drift alert without a performance link is noise; measure both.

## Decision 2 — Ground truth latency

- Labels arrive late (days, weeks) — define the expectation and track label lag.
- Proxies in the interim: user overrides, manual review outcomes, downstream
  conversion, escalation rate.
- Backfill evaluation windows when labels land; recompute historical performance.
- If no labels ever arrive, say so and design a sampling process.

## Decision 3 — Drift detection

- Baseline = training distribution, plus a rolling recent window for comparison.
- Metrics: PSI/KL for numeric, chi-square for categorical, plus simple mean/variance.
- Threshold per feature based on business tolerance, not a universal 0.1.
- Alert on **feature × segment** where it matters; global drift can be a harmless
  mix shift.

## Decision 4 — Deployment patterns that produce evidence

- **Shadow**: run the candidate in parallel, log predictions, compare to production
  before switching.
- **Canary**: small traffic share with guardrail metrics tied to the business.
- **Champion/challenger**: sustained comparison over a full cycle.
- Log features used at serving time; without them you cannot reproduce a prediction.

## Decision 5 — Retraining triggers

| Trigger | Action |
|---|---|
| drift beyond threshold | evaluate retrain |
| performance below floor | retrain, escalate if unchanged |
| scheduled cadence | routine retrain |
| new segment growth | collect data, then retrain |

- Retraining is a pipeline run with eval gates, not a manual notebook.
- Track model version in every prediction log; a "regression" is often an old
  version still serving.

## Decision 6 — Alerting quality

- Alert with the impact statement: which segment, what change, what threshold.
- Route to the model owner, with a runbook: check version, check input pipeline,
  check upstream schema, compare to shadow.
- Tune to few alerts; a channel with 200 weekly alerts is a dead channel.
- Review alert outcomes monthly; delete what never leads to action.

## Failure modes at scale

- Latency and error-rate dashboards only; accuracy decayed for three months.
- Drift alert on a feature that changed because of a marketing campaign; ignored.
- Segment regression invisible in the aggregate metric.
- Retraining pipeline breaks silently; the model ages out over a quarter.
- Predictions logged without features; cannot reproduce or explain a complaint.

## Verification receipts

1. Monitoring plan: signals, thresholds, owners, alert routes.
2. Drift report comparing a recent window to baseline.
3. Delayed-label evaluation run once labels landed.
4. Shadow deployment comparison for a candidate model.
5. One alert triaged through the runbook, with the outcome recorded.
