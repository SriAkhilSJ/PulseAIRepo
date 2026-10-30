---
name: cloudflare-architect
description: Architect-level edge platform design — DNS as code, Workers and Durable Objects for compute at the edge, R2 for zero-egress storage, WAF/bot/Turnstile at the perimeter, and the cache and origin rules that decide whether the edge helps or hides problems. Use when the perimeter, DNS, or CDN strategy matters.
license: MIT
compatibility: Cloudflare; comparable on Fastly/Akamai/CloudFront
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/providers-architect/cloudflare-architect
  crusor-origin: original
  crusor-sources: "developers.cloudflare.com/workers; developers.cloudflare.com/r2; developers.cloudflare.com/waf"
  crusor-triggers: "cloudflare, workers, durable objects, r2, waf, cdn, edge compute, dns, bot protection, turnstile"
  crusor-verified-on: "2026-10-30"
---

# Cloudflare / Edge Architect

The edge is **a second deployment target with its own runtime limits**. Used well
it absorbs abuse and latency; used casually it becomes a cache that hides bugs.

## When to use

- Global audience, static or per-request edge logic, DNS and perimeter in one place.
- Egress costs dominate (R2 instead of S3 for large media).
- Header-level routing, auth checks, and rewrites before origin.

## When NOT to use

- Single-region internal app — the edge adds hop and debugging complexity.
- Long-running compute, heavy CPU, or large binaries: Workers limits bite.

## Decision 1 — What runs at the edge

| Concern | Edge | Origin |
|---|---|---|
| TLS, DNS, WAF, bot rules | yes | — |
| static assets, cache | yes | — |
| auth token validation, header injection | yes | also verify |
| per-request personalisation (light) | yes | — |
| database queries, heavy processing | — | yes |
| anything over CPU/memory limits | — | yes |

- Edge code is a proxy: keep it small, deterministic, and independent of origin
  internals.
- Workers CPU time and memory are hard limits — design within them, not around.

## Decision 2 — Caching

- Cache keys decide everything: include the headers/vary dimensions you actually
  need; a bad key leaks one user's response to another.
- `Cache-Control` from origin is the contract; edge rules should not paper over a
  missing header.
- Purge strategy: tag-based purges, not "purge everything" as a habit.
- Never cache authenticated responses unless the key includes the identity and you
  understand the risk.

## Decision 3 — Perimeter

- WAF managed rules + a small set of custom rules for your actual attack surface.
- Rate limiting per IP and per API key, with a path-specific policy — a global
  limit will either not protect or block legitimate bursts.
- Bot management and Turnstile on public forms; do not rely on user-agent strings.
- Origin must accept traffic **only** from the edge (mTLS or IP allowlist with
  authenticated origin pulls) — otherwise the WAF is optional for attackers.
- DDoS is assumed; verify the plan's coverage for the protocols you serve.

## Decision 4 — DNS

- DNS as code (Terraform), with proxied vs DNS-only decided per record.
- CAA records, DNSSEC, and a documented change procedure: DNS is the highest
  blast-radius system you operate.
- Low TTLs before a migration, then restore; do not leave TTL=60 forever.
- Internal names never in public zones.

## Decision 5 — Storage and state

- R2 for media and large objects: zero egress, S3-compatible API; keep a copy
  strategy as for any object store.
- Durable Objects for coordination (counters, rooms, locks) — they are a single
  point of serialisation per object; keep state small.
- KV for read-heavy config with eventual consistency; never for correctness.
- Queue consumers for async work that must survive the request.

## Decision 6 — Observability

- Logpush to your own storage; sample request logs by status and path.
- Trace the edge hop: a 5xx at the edge and a 5xx at origin must be distinguishable
  in dashboards.
- Alert on origin error rate, cache hit ratio collapse, and WAF block spikes.

## Failure modes at scale

- Cache key ignoring `Accept-Language`; users see the wrong language.
- Origin reachable directly, bypassing every rule.
- Workers deployed without CPU headroom; large JSON payloads time out.
- Global purge on every deploy, collapsing the cache in front of a cold origin.
- DNS change during an incident with no rollback plan.

## Verification receipts

1. Edge inventory: which routes, handlers, and rules run where.
2. Cache key table per route with Vary dimensions and purge method.
3. Direct-to-origin request from outside the edge, rejected.
4. Rate-limit and bot rules exercised with a synthetic burst.
5. DNS change rehearsed with TTL plan and rollback.
