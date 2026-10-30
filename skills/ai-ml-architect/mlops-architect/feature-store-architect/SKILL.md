---
name: feature-store-architect
description: Architect-level feature platform design — online versus offline stores, point-in-time correctness, feature ownership and SLAs, freshness tiers, backfills, and the parity testing that prevents training-serving skew. Use when more than one model or team consumes the same computed signals.
license: MIT
compatibility: Feast, Tecton, Databricks Feature Store, homegrown
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/mlops-architect/feature-store-architect
  crusor-origin: original
  crusor-sources: "docs.feast.dev; docs.tecton.ai; cloud.google.com/vertex-ai/docs/featurestore"
  crusor-triggers: "feature store, online features, offline features, point in time, training serving skew, feature pipeline, feature freshness, feast, online and offline, feature drift"
  crusor-verified-on: "2026-10-30"
---

# Feature Store Architect

A feature store exists to solve **one problem: the model must see at training time
what it will see at inference time**. If that is not a real problem for you, do not
buy the system.

## When to use

- Several models reuse the same features.
- Features must be served online with low latency and backfilled for training.
- Training-serving skew has caused a production incident.

## When NOT to use

- One model, one team, batch-only inference — a warehouse table is enough.
- Features are cheap to recompute in the serving path.

## Decision 1 — Do you need it

| Symptom | Feature store helps |
|---|---|
| two definitions of "active user" | yes |
| online serving from Redis built ad hoc | yes |
| offline training reads raw event tables | yes, for point-in-time |
| one batch model, nightly | no |

## Decision 2 — Architecture

```
source events → transformation → offline store (warehouse/lake)
                              → online store (KV/Redis)  ← same definition
                                       ↑
                              materialisation job
```

- One definition, two sinks. Duplicating the logic per sink is the skew.
- Online store holds only the latest value per entity key; offline holds history.
- Materialisation lag is a stated number per feature.

## Decision 3 — Point-in-time correctness

- Training rows join features as of the label timestamp, not "now".
- Event-time timestamps, not ingestion timestamps; they differ under delay.
- Late-arriving data must update history without rewriting the past incorrectly.
- Leakage test: a feature that uses future aggregates will produce impossible
  offline scores — check every aggregate's window.

## Decision 4 — Ownership and SLAs

- Each feature has an owner, a description, a freshness SLA, and a quality check.
- Group features into logical views per entity (`user_profile`, `user_activity_30d`).
- Deprecate features explicitly; unused features cost compute forever.
- Discoverable catalogue so teams do not rebuild the same signal.

## Decision 5 — Freshness tiers

| Tier | Freshness | Mechanism |
|---|---|---|
| batch daily | 24 h | warehouse job |
| micro-batch | 15 min | scheduled |
| streaming | seconds | stream processor |
| on-demand | request time | computed in serving |

- Streaming features are 5–10× the cost and complexity; justify with a decision that
  changes within minutes.

## Decision 6 — Parity testing

- Automated test: sample entity ids, compare online value vs offline value at the
  same timestamp; alert on divergence.
- Golden dataset for model training; rerun the training pipeline to confirm
  reproducibility.
- Monitor null rates and distribution drift per feature — a silent upstream change
  is the common outage.

## Failure modes at scale

- Training features computed with today's data; offline AUC 0.95, production 0.6.
- Online store populated by a different job than offline; values differ subtly.
- One team redefines a shared feature; every dependent model shifts.
- Materialisation fails silently; serving serves day-old features for a week.
- Hundreds of features, none with an owner, half unused.

## Verification receipts

1. Decision record: the skew problem this store solves.
2. Point-in-time join test against a known historical row.
3. Parity test results for a sample of entities across online/offline.
4. Freshness SLA per feature, with materialisation lag measured.
5. Catalogue entries with owners and last-used timestamps.
