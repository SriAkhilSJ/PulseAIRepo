---
name: sre-observability-architect
description: Architect-level observability design for infrastructure and services — the three signals and what each is for, SLI-driven dashboards, log strategy and cost, trace propagation across boundaries, alert design that pages a human only when it should, and the runbook link every alert needs. Use when operating systems need to be diagnosable.
license: MIT
compatibility: OpenTelemetry, Prometheus, Grafana, Datadog, CloudWatch, Loki
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/operations-architect/sre-observability-architect
  crusor-origin: original
  crusor-sources: "opentelemetry.io/docs; prometheus.io/docs; sre.google/workbook/alerting-on-slos"
  crusor-triggers: "observability, prometheus, grafana, opentelemetry, tracing, alerting, dashboards, sli, log aggregation, monitoring stack"
  crusor-verified-on: "2026-10-30"
---

# SRE Observability Architect

Observability is **the ability to answer a new question without deploying code**.
Dashboards answer known questions; instrumentation decides whether the unknown ones
are answerable.

## When to use

- Standing up monitoring for a new system.
- Alert fatigue, or an incident nobody could diagnose.
- Cost of logs/metrics growing faster than traffic.

## When NOT to use

- A local script or a one-off job.
- The problem is a single known bug — just fix it.

## Decision 1 — Signals

| Signal | Answers | Cost driver |
|---|---|---|
| metrics | is it healthy, at what rate | series cardinality |
| logs | what exactly happened | volume |
| traces | where the time went | sampling |
| profiles | which code is slow | collection overhead |

- Metrics for detection, traces for localisation, logs for detail. Do not use logs
  as a metrics store.
- Cardinality is the metric cost trap: user ids and request ids are labels you
  will regret.

## Decision 2 — Instrumentation

- OpenTelemetry SDKs, not vendor agents, so backends can change.
- Trace context propagated across HTTP, queues, and batch boundaries; a broken
  context = a useless trace.
- Span names stable and low-cardinality; attributes for specifics.
- Every service emits: request rate, error rate, duration, saturation, plus its
  own domain counters.
- Correlate: log lines carry trace id and span id, always.

## Decision 3 — Dashboards

- One dashboard per service: golden signals, dependencies, deploy markers.
- SLI-based panels first (availability, latency, error budget burn), then resource
  detail.
- Annotate deploys and incidents on every dashboard — correlation starts there.
- Dashboards are code (provisioned from git), reviewed like code.

## Decision 4 — Logs

- Structured JSON, consistent fields (`service`, `env`, `trace_id`, `level`).
- Levels used honestly: debug off in production, warnings that mean something.
- Volume control: sampling, retention tiers, and no PII.
- Store logs where they can be queried during an incident without a quota error.

## Decision 5 — Alerts

- Page only on **user-visible symptoms** or error-budget burn; everything else is a
  ticket.
- Every alert needs: owner, runbook link, and a clear action.
- Symptoms over causes: "checkout error rate > 2%" pages; "CPU > 80%" does not.
- Group and dedupe; a single incident should not produce 40 pages.
- Review alerts monthly: delete unused, retune noisy, verify the runbook still
  works.

## Decision 6 — Cost

- Metrics: drop high-cardinality labels, aggregate before ingest.
- Logs: retention by value — 7 days hot, 90 days cold, archive beyond.
- Traces: head sampling for volume, tail sampling for errors if the backend
  supports it.
- Review cost per service; observability spend should track the services it
  protects.

## Failure modes at scale

- 4,000 dashboards, none owned, all showing green while users complain.
- Logs sampled at ingest so the failing request is not present.
- Traces without context propagation to the queue consumer: half a transaction.
- Pager fires on a metric with no runbook; engineer improvises at 3 a.m.
- Observability bill exceeding compute, nobody owns it.

## Verification receipts

1. Signal coverage per service: metrics, traces, logs, with gaps listed.
2. One incident replayed from telemetry: found the cause without new code.
3. Alert inventory with owner and runbook for each paging alert.
4. Cardinality report showing the top label offenders.
5. Cost by signal type with retention policy applied.
