---
name: redis-architect
description: Architect-level Redis guidance — deciding what may live in a cache versus a source of truth, key naming and eviction policy, cache-aside and stampede protection, using the right data structure, and the durability limits that turn a cache into an outage. Use when adding Redis for caching, sessions, rate limits or queues.
license: MIT
compatibility: Redis 7+ (or Valkey)
metadata:
  crusor-domain: website-architect
  crusor-path: database-engineering-architect/redis-architect
  crusor-origin: original
  crusor-sources: "redis.io/docs/latest; redis.io/docs/latest/develop/reference/eviction"
  crusor-triggers: "redis, cache, caching, session store, rate limit, pub sub, eviction, key expiry, valkey"
  crusor-verified-on: "2026-10-30"
---

# Redis Architect

Redis is **fast because it is allowed to lose your data**. Everything here
follows from that sentence.

## When to use

- Read-heavy paths needing sub-millisecond responses.
- Sessions, rate limits, locks, counters, queues, presence.
- A cache in front of a database that remains authoritative.

## When NOT to use

- Anything that cannot be regenerated (orders, balances, audit logs).
- As the primary database because "it's faster".
- Large blobs and search — wrong tool.

## Decision 1 — What may live here

| Data | Allowed | Rule |
|---|---|---|
| derived caches | yes | always reconstructable from the source |
| sessions | yes | TTL, and re-login is an acceptable loss |
| rate-limit counters | yes | approximate by design |
| queues/dedup keys | yes | consumers must tolerate redelivery |
| business records | **no** | Postgres/document store |

Every key has an owner (who writes it), a TTL, and a rebuild path.

## Decision 2 — Keys and eviction

- Namespaced keys: `app:v1:user:{id}:profile`, version in the prefix so a shape
  change is a new keyspace.
- TTL on everything except deliberately durable structures; a key without TTL
  is a slow leak.
- `maxmemory-policy`: `allkeys-lru` for pure caches, `volatile-*` when some keys
  must survive, `noeviction` only when you handle write errors.
- Track hit ratio and evictions; evicting a lot means the cache is a database
  now.

## Decision 3 — Patterns

| Pattern | Use | Cost |
|---|---|---|
| cache-aside | default; app reads cache, falls back to DB, writes back | thundering herd on miss |
| write-through | strong freshness needed | write latency, cache as critical path |
| read-through | library-managed | hides latency from the app |
| stampede lock | hot key after expiry | complexity |

- Stampede: lock + serve stale, or jittered TTLs. Never let N requests
  recompute the same expensive value.
- Negative caching: cache "not found" briefly or you will hammer the DB.
- Invalidation is the hard part — prefer short TTL + explicit delete on write.

## Decision 4 — Data structures

- Strings for blobs/counters, hashes for objects (partial updates), sorted sets
  for leaderboards/rate windows, streams for queues, sets for membership.
- Avoid fetching a whole large hash to read one field.
- `SCAN` not `KEYS` in production; `UNLINK` not `DEL` for big values.

## Decision 5 — Durability and topology

- RDB/AOF are best-effort: acknowledge the loss window explicitly.
- Replication is async by default; a failover can lose recent writes — never
  put money in it.
- Sentinel/cluster for HA; cluster only when a single node's memory/throughput
  is genuinely insufficient (it constrains multi-key ops).

## Failure modes at scale

- Redis flushed during an incident → sessions gone, app unusable.
- One giant key (a list with a million entries) blocking the single thread.
- `KEYS *` in production freezing the server.
- Cache treated as truth: data "reappears" after eviction.
- TTL jitter absent → synchronized expiry → DB spike every hour.

## Verification receipts

1. Key inventory: owner, TTL, rebuild path.
2. Eviction policy and maxmemory reviewed against workload.
3. Hit ratio and eviction count from `INFO stats`.
4. Failure test: Redis down → app degrades (slower), not fails.
5. Hot-key and big-key audit (`--bigkeys`, slowlog).
