---
name: rate-limiting-architect
description: Architect-level API protection — quota models and key selection, token bucket vs sliding window, where the limiter lives (edge vs app vs database), 429 contract and Retry-After, graceful degradation, and the abuse cases limits are actually for. Use when an API needs quotas or is being scraped/abused.
license: MIT
compatibility: Any HTTP stack; Redis or an edge provider typical
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/api-development-architect/rate-limiting-architect
  crusor-origin: original
  crusor-sources: "datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers; cloud.google.com/architecture/rate-limiting-strategies-techniques"
  crusor-triggers: "rate limit, rate limiting, throttling, throttle, quota, 429, abuse, scraping, backpressure, token bucket"
  crusor-verified-on: "2026-10-30"
---

# Rate Limiting Architect

Limits exist so that **one client cannot degrade the service for everyone** —
including your own retry storms.

## When to use

- Public or partner-facing APIs.
- A client (or a bot) is degrading the service.
- Expensive operations: exports, searches, AI calls, emails.

## When NOT to use

- Internal service-to-service traffic where backpressure and timeouts already
  bound the work — adding quotas there just hides capacity problems.

## Decision 1 — What you limit, and by whom

| Dimension | Key |
|---|---|
| per user | authenticated subject id |
| per IP | hashed address (behind a trusted proxy) |
| per API key / tenant | key id, with plan tiers |
| per endpoint cost | weighted budget (exports cost 10× reads) |

- Rate limit the **cost**, not just the request count: one export can equal 500
  reads.
- Anonymous traffic is keyed by IP **and** a coarse fingerprint; IP alone breaks
  for shared NATs and proxies.
- Never trust `X-Forwarded-For` without a configured trusted proxy chain.

## Decision 2 — Algorithm

| Algorithm | Behaviour | Use |
|---|---|---|
| fixed window | bursty at boundaries | simple, low value |
| sliding window (log/counter) | smooth | default for user quotas |
| token bucket | allows burst up to capacity | APIs with bursty clients |
| concurrency limit | caps in-flight | expensive endpoints |
| queue + shed | admits then rejects | ingestion |

- Default: token bucket per key per endpoint class, stored in Redis with atomic
  increments (`INCR` + `EXPIRE`, or a Lua script).
- Distributed limiter needs atomicity; local in-process counters multiply by the
  instance count.

## Decision 3 — Where it runs

- Edge/WAF for coarse abuse and DDoS (never the only limit).
- Application middleware for per-user/per-tenant quotas (knows identity).
- Per-operation guards for expensive work (exactly where cost is incurred).
- Limits must degrade gracefully: reject early, before allocating work.

## Decision 4 — The 429 contract

- `429 Too Many Requests` with `Retry-After` (seconds) and rate headers
  (`RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`).
- The error body uses the same envelope as every other error, with a stable
  code (`RATE_LIMITED`).
- Limits are documented publicly: per plan, per endpoint class.
- Clients must back off with jitter — publish that expectation.

## Decision 5 — Fairness and abuse

- Separate buckets for reads/writes/exports so one heavy endpoint cannot starve
  the rest.
- Shadow-ban style soft limits for scrapers: slow, don't block, when the traffic
  is plausibly human.
- Cost-based limits for AI/LLM calls with a hard daily budget per tenant.
- Alert on limiter rejections: a spike is either an attack or your own retry
  storm.

## Failure modes at scale

- Counter in process memory → effective limit = limit × instances.
- Fixed windows allowing 2× burst at the boundary.
- Limiter in front of an expensive job but after the queue → work already
  enqueued.
- 429 with no `Retry-After` → clients hammer immediately.
- Retries without jitter turning a blip into an outage.

## Verification receipts

1. Limit table published: dimension, algorithm, thresholds, plan tiers.
2. Load test proving rejection happens before expensive work.
3. Distributed-consistency test across two instances.
4. Client behaviour test: 429 honoured with backoff, no thundering herd.
5. Alert on rejection rate and on limiter backend failure.
