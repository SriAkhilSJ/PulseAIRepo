---
name: observability-architect
description: Architect-level observability — structured logs, metrics and traces that answer real questions, correlation ids across services, SLIs/SLOs and symptom-based alerting, and the cost and cardinality traps that make telemetry useless. Use when a system needs to be debuggable in production.
license: MIT
compatibility: OpenTelemetry; any backend (Prometheus, Loki, Tempo, vendor APM)
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/testing-and-deployment-architect/observability-architect
  crusor-origin: original
  crusor-sources: "opentelemetry.io/docs; sre.google/sre-book (SLOs); sre.google/workbook/alerting-on-slos"
  crusor-triggers: "observability, logging, metrics, tracing, opentelemetry, slo, sli, alerting, dashboards, cardinality"
  crusor-verified-on: "2026-10-30"
---

# Observability Architect

Observability is not "having logs". It is **being able to answer a question you
did not anticipate**, cheaply, during an incident.

## When to use

- Designing a new service, or one that cannot be debugged in production.
- Alerts fire constantly and nobody trusts them.
- Telemetry cost is growing faster than traffic.

## When NOT to use

- Local-only scripts. But any deployed service without traces is under-built.

## Decision 1 — The three signals, with a job each

| Signal | Answers | Cost driver |
|---|---|---|
| logs (structured) | what exactly happened in this request | volume |
| metrics | is the system healthy right now, at what rate | cardinality |
| traces | where the time went across services | sampling |

- All three must share a **correlation id** (trace id) so you can pivot.
- Every log line is JSON with a stable schema: timestamp, level, service,
  trace_id, message, plus contextual fields.
- Logs are events, not prose; no `print("here")` in production paths.

## Decision 2 — What to instrument first

1. Request rate, error rate, duration (RED) per endpoint.
2. Saturation: queue depth, pool usage, worker occupancy.
3. Dependencies: DB latency, cache hit ratio, third-party latency.
4. Business counters that indicate success (orders created, signups), not just
   system health.

- Instrument the boundary you own first; deep internals after.

## Decision 3 — Cardinality discipline

- Never use user id, email, request id or URL-with-params as a metric label —
  that is how you get a million time series and a five-figure bill.
- Put high-cardinality detail in logs and trace attributes, not metrics.
- Bound label sets explicitly (status class, endpoint template, region).
- Sample traces: 100% of errors, a percentage of successes.

## Decision 4 — SLOs and alerting

- Define SLIs as ratios: successful requests / total, fast requests / total.
- One SLO per user-facing journey with an error budget; alert on burn rate, not
  on raw thresholds.
- Every alert is: symptom-based, actionable, and has a runbook link.
- Delete alerts nobody acts on — alert fatigue is the failure mode.

## Decision 5 — Privacy and cost

- No PII, tokens or passwords in logs; redact at the logger, not per call site.
- Retention per signal: logs short, metrics longer, traces sampled.
- Cost review monthly: which signal grew, and did anyone use it?
- Debug endpoints and verbose logging are off by default in production.

## Failure modes at scale

- Logs exist, but no request id ties a frontend error to a backend query.
- Metrics with user ids → cardinality explosion and a surprise invoice.
- Alerts on CPU while users experience 500s.
- Traces sampled at 1% so every incident investigation is a guess.
- A dashboard nobody opens, kept alive because someone built it.

## Verification receipts

1. Trace of one request end to end, with DB and third-party spans.
2. RED dashboard per endpoint, plus queue/pool saturation.
3. SLI computation documented; error budget visible.
4. Alert inventory: symptom, threshold, runbook, owner, last fired.
5. PII scan across log output for a sample of real requests.
