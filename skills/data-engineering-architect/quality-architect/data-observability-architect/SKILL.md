---
name: data-observability-architect
description: Architect-level data observability — freshness, volume, schema and distribution monitoring per table, anomaly baselines that do not cry wolf, and the alert routing and triage that turns a signal into a fix. Use when pipelines run daily and nobody notices when one silently stops.
license: MIT
compatibility: Monte Carlo, Elementary, Soda, Great Expectations, custom monitors
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/quality-architect/data-observability-architect
  crusor-origin: original
  crusor-sources: "docs.elementary-data.com; docs.soda.io; montecarlodata.com/blog-data-observability"
  crusor-triggers: "data observability, freshness monitoring, volume anomaly, pipeline monitoring, data downtime, table monitor, row count alert, schema change alert, stale data, stale dashboard, data is stale, pipeline stopped"
  crusor-verified-on: "2026-10-30"
---

# Data Observability Architect

Data observability is **the answer to "is the data in this table trustworthy right
now"** without running a query. Pipelines report success while producing stale or
empty tables — that is the gap this closes.

## When to use

- Daily/hourly pipelines feed dashboards or decisions.
- Data downtime has been noticed by users rather than by monitoring.
- Too many tables and too few people to eyeball them.

## When NOT to use

- A single pipeline with one consumer and a human reviewing output daily.
- As a substitute for tests at the transformation layer — they are complementary.

## Decision 1 — Per-table signals

| Signal | Question |
|---|---|
| freshness | when did data last land? |
| volume | did row count change beyond expectation? |
| schema | did columns change? |
| distribution | did null rate / category mix shift? |
| lineage | did an upstream asset stop? |
| quality checks | did business rules pass? |

- Coverage first: monitor the **top 20 tables** by consumer count, not all 4,000.
- Freshness and volume catch most incidents cheaply; distribution catches the subtler
  ones.

## Decision 2 — Baselines

- Seasonal baselines (day-of-week, hour-of-day) — a flat threshold over a weekly
  business creates false alarms every weekend.
- Learn from the last N comparable periods, excluding known anomalies.
- Absolute floors as a backstop (a table should never have 0 rows).
- Review and retune monthly: a noisy monitor is removed by the team within weeks.

## Decision 3 — Severity and routing

| Severity | Example | Route |
|---|---|---|
| critical | revenue table empty at 08:00 | page the pipeline owner |
| high | freshness breach on a key mart | alert channel + ticket |
| medium | schema change, additive | notify consumers |
| low | distribution drift | weekly digest |

- Route by table ownership, not by team-wide channels; blast alerts to everyone and
  nobody reads them.
- Every alert carries: table, signal, expected vs actual, upstream asset, runbook
  link.
- Deduplicate: one broken upstream produces one incident, not forty tree alerts.

## Decision 4 — Culture and process

- On-call for data exists, or nothing is actionable outside business hours.
- Triage: check upstream freshness first, then the job, then the source system.
- Post-incident: add the monitor that would have caught it; record data downtime.
- Report data downtime as a metric alongside service uptime.

## Failure modes at scale

- Pipeline green, table stale for three days; a dashboard shows a flat line.
- 400 alerts a week; the channel is muted and the real one is missed.
- Freshness monitor set to 24 h for an hourly table; useless.
- Schema change alert fired 40 times for one migration.
- Monitoring tool deployed, connected to two tables, abandoned.

## Verification receipts

1. Monitored table list with the signal set per table and the consumer count.
2. Baseline configuration for one table including seasonality.
3. Alert routing map with owners and runbook links.
4. One incident reconstructed from monitors alone.
5. Alert volume trend for the last month, with stale monitors removed.
