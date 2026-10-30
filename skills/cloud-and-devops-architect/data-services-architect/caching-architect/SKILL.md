---
name: caching-architect
description: Architect-level caching design — cache layers and what each may hold, key strategy and invalidation, consistency models (TTL, write-through, event-driven), stampede and hotspot protection, and the failure behaviour when the cache is cold or down. Use when read load or latency must come down without changing the source of truth.
license: MIT
compatibility: Redis/ElastiCache, Memcached, CDN, in-process caches
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/data-services-architect/caching-architect
  crusor-origin: original
  crusor-sources: "redis.io/docs/manual; docs.aws.amazon.com/AmazonElastiCache/latest/red-ug; developer.mozilla.org/en-US/docs/Web/HTTP/Caching"
  crusor-triggers: "caching, redis, memcached, cache invalidation, cache stampede, ttl, hot key, cache hit ratio, write through, cache aside"
  crusor-verified-on: "2026-10-30"
---

# Caching Architect

A cache is **a copy you must be able to be wrong about**. If you cannot tolerate
stale data, you cannot cache it — you can only replicate it.

## When to use

- Read-heavy workloads with a hot subset.
- Expensive computations or aggregations repeated per request.
- Latency targets beyond what the datastore can deliver.

## When NOT to use

- Correctness-critical reads with no staleness tolerance.
- The database is fast enough — measure before caching.

## Decision 1 — Where the cache lives

| Layer | Holds | TTL |
|---|---|---|
| browser/CDN | public assets, GET responses | long, versioned URLs |
| edge | per-region responses | route-specific |
| app in-process | hot config, small objects | seconds |
| distributed (Redis) | sessions, computed objects, counters | minutes–hours |
| database buffer | pages | managed by engine |

- Every layer multiplies invalidation complexity; add one only when the layer below
  is measurably insufficient.
- In-process caches make rolling deploys temporarily inconsistent — acceptable only
  with short TTLs.

## Decision 2 — Pattern

| Pattern | Behaviour | Risk |
|---|---|---|
| cache-aside | app reads cache, on miss loads and writes | stale on write |
| write-through | write cache and store together | write latency |
| write-behind | write cache, async flush | data loss on crash |
| read-through | cache library fetches | hidden latency |
| event-driven invalidation | publish changes, subscribers evict | missed events |

- Cache-aside with event-driven invalidation is the default for product data.
- Session/counter data uses write-through with persistence configured.
- Any write-behind design needs the loss window stated and accepted.

## Decision 3 — Keys and invalidation

- Keys include the entity id and a schema version: `user:42:v3`.
- Never key on user-supplied strings without normalisation; unbounded key space is
  a memory attack.
- Set TTLs on everything — a cache without expiry leaks memory and hides bugs.
- Invalidation: on write, delete the key (do not update it) and let the next read
  fill; delete-then-set races are the classic stale-cache bug.
- Versioned namespaces for mass invalidation: bump the version, old keys expire.

## Decision 4 — Failure and load

- Cache down must degrade, not fail: fall back to the datastore with a circuit
  breaker, and rate-limit the fallback so the database does not die.
- Stampede: on miss storms, use a lock/single-flight per key plus jittered TTLs.
- Hot keys: local in-process cache in front, or shard the key.
- Cold start after an eviction or deploy is a load event — pre-warm critical keys.
- Eviction policy matters: LRU for general use, TTL-driven for sessions; a random
  policy with uniform keyspace destroys hit rate.

## Decision 5 — Measurement

- Hit ratio per key class; a 40% hit ratio may cost more than it saves.
- p50/p99 latency with and without the cache — prove the benefit.
- Memory, evictions, and connection counts from the cache itself.
- Cost per 1k requests vs the database query cost avoided.

## Failure modes at scale

- Cache poisoned by a null result written as `None` for 24 hours.
- TTL of zero meaning "forever" in the code path nobody reviewed.
- Cache key missing the tenant, so one tenant sees another's data — the worst
  possible cache bug.
- Redis down, every request hits Postgres and takes it down with it.
- Session data in a cache with eviction enabled; users logged out at random.

## Verification receipts

1. Cache inventory: layer, data class, TTL, invalidation trigger.
2. Hit-ratio and latency report per key class.
3. Tenant-isolation test: keys cannot collide across tenants.
4. Cache-outage drill with the fallback path and its rate limit.
5. Stampede test: mass eviction, database load stays within budget.
