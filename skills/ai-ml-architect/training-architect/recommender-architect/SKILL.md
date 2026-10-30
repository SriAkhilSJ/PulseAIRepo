---
name: recommender-architect
description: Architect-level recommendation systems — candidate generation and ranking architecture, collaborative versus content signals, cold start, evaluation with offline metrics versus online experiments, and the feedback loops that quietly narrow what users see. Use when a product must choose what to show.
license: MIT
compatibility: Two-tower retrieval, matrix factorisation, LightFM, vector search
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/training-architect/recommender-architect
  crusor-origin: original
  crusor-sources: "developers.google.com/machine-learning/recommendation; arxiv.org/abs/1906.00091; eugeneyan.com/writing/system-design-for-discovery"
  crusor-triggers: "recommendation system, recommender, collaborative filtering, cold start, candidate generation, ranking model, personalized feed, two tower, recommend, recommendations, what to show"
  crusor-verified-on: "2026-10-30"
---

# Recommender Architect

A recommender is **a retrieval problem plus a ranking problem plus a feedback
problem**. Treat the feedback problem last and you ship a filter bubble.

## When to use

- Feeds, search suggestions, "related items", personalised ranking.
- Catalogue too large to show everything.
- Engagement or conversion depends on ordering.

## When NOT to use

- The catalogue is small and a human-defined order already works.
- You have no interaction data and no content metadata — start with rules.

## Decision 1 — Pipeline

```
candidate generation (retrieve 100s)  → ranking (score 10s) → re-ranking/business rules → UI
```

- Never rank the full corpus; two-stage is mandatory at scale.
- Candidates from several sources: popularity, collaborative, content-similar,
  trending, recently viewed.
- Ranking model sees user, item, context features; business rules (diversity,
  dedupe, policy, freshness) apply after scoring.

## Decision 2 — Signals

| Signal | Note |
|---|---|
| implicit (clicks, dwell, purchases) | abundant, noisy, position-biased |
| explicit (ratings, saves) | sparse, biased to extremes |
| content metadata | works for cold start |
| context (device, time, query) | big lift, often ignored |

- Impression data is required to correct position bias — without it, the model
  learns to recommend what it already showed.
- Weight actions by intent (purchase ≫ click ≫ view).

## Decision 3 — Cold start

- New items: content similarity plus exploration slot.
- New users: popularity and contextual rules until enough signal.
- Deliberate exploration for both; a deterministic top-1 for everyone is not a
  recommender.

## Decision 4 — Evaluation

- Offline: recall@k for candidates, nDCG/MAP for ranking, against held-out future
  interactions (time-based split).
- Offline metrics are a filter; **online A/B is the decision**.
- Track business metrics alongside engagement: conversion, retention, diversity,
  long-term satisfaction.
- Guard against offline-online divergence caused by position bias in labels.

## Decision 5 — Feedback loops and health

- Popularity amplification: popular items get shown, get clicked, become more
  popular. Add diversity constraints and exploration.
- Monitor catalogue coverage — what fraction of items ever get impressions.
- Monitor for undesirable self-reinforcement (narrowing topical range).
- Freshness and decay: recency-weighted interactions prevent stale models.

## Decision 6 — Serving

- Precompute candidates for heavy users, compute on demand for the tail.
- Keep p95 latency budget for the whole pipeline; ranking models are usually the
  biggest cost.
- Fallback path: popularity-based list if the model service fails.
- Log features and scores for the served item — needed for debugging and retraining.

## Failure modes at scale

- Offline nDCG improved 5%, online revenue flat, shipped anyway.
- No impression logging; the model learns position, not preference.
- Cold-start items never recommended; new inventory invisible.
- Same five items for every user; "personalisation" that is a global top-5.
- Latency spikes to 900 ms and the UI silently falls back to recency.

## Verification receipts

1. Pipeline diagram with candidate sources and counts.
2. Offline metrics on a time-based split, plus position-bias correction.
3. A/B design with primary and guardrail metrics.
4. Coverage and diversity report for the catalogue.
5. Fallback path tested by failing the ranking service.
