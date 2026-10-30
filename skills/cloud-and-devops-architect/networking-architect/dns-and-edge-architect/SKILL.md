---
name: dns-and-edge-architect
description: Architect-level DNS and edge routing — zone structure and delegation, record hygiene, TTL and failover strategy, geo and latency routing, certificate lifecycle, and the change discipline that keeps the highest-blast-radius system in your estate safe. Use when domains, routing, or TLS certificates are part of the design.
license: MIT
compatibility: Route 53, Cloud DNS, Azure DNS, Cloudflare DNS, any CDN
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/networking-architect/dns-and-edge-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/Route53; developers.cloudflare.com/dns; cloud.google.com/dns/docs"
  crusor-triggers: "dns, route 53, zone, ttl, failover routing, geo routing, certificate, acme, domain migration, cname, cdn routing"
  crusor-verified-on: "2026-10-30"
---

# DNS & Edge Architect

DNS is **the last thing that breaks everything**. A wrong record takes down a
product globally in seconds, and the TTL you set last year decides how long it
lasts.

## When to use

- Registering domains, structuring zones, or migrating providers.
- Designing multi-region failover or geo routing.
- Certificate automation and renewal.

## When NOT to use

- Internal service discovery inside Kubernetes → `kubernetes-architect`.
- CDN/edge logic → `cloudflare-architect`.

## Decision 1 — Zone structure

```
example.com              apex: apex records, MX, TXT (SPF/DKIM/DMARC)
  www.example.com        apex alias to CDN/LB
  api.example.com        public API entry
  *.example.com          wildcard only where a real use case exists
  internal.example.com   private zone, never public
```

- Delegate subdomains to teams/accounts rather than editing one shared zone.
- Registrant email on an org alias with monitoring; expiry is a self-inflicted
  outage (enable auto-renew and registrar lock).
- DNSSEC where the provider supports it end to end; verify with a validating
  resolver.

## Decision 2 — Records

- ALIAS/ANAME to load balancers and CDNs, never CNAME at the apex.
- CNAME chains add latency and failure modes; flatten or point directly.
- TXT records carry SPF/DKIM/DMARC and verification tokens — treat them as config,
  version them.
- CAA restricts which CAs may issue; it is cheap insurance.
- No wildcards for anything authenticated.

## Decision 3 — TTL and failover

| Situation | TTL |
|---|---|
| steady state | 300–3600 s |
| before a migration | 60 s, lowered ≥ 2× the current TTL in advance |
| failover records | 60 s, with health checks |
| static marketing | 3600 s+ |

- Failover routing needs health checks that test a real endpoint, not ICMP.
- DNS failover is not instant: clients and resolvers cache. Design the application
  for it (retries, multi-endpoint clients) rather than trusting TTL.
- Geo/latency routing requires a fallback record, or unmatched regions get NXDOMAIN.

## Decision 4 — Certificates

- Automated issuance and renewal (ACME), with expiry alerting at 30/14/7 days.
- Wildcard versus per-host: wildcards simplify, at the cost of blast radius if the
  key leaks.
- Certificates and private keys live in a secret manager, not a repo or a laptop.
- Rotation must be rehearsed — a certificate you cannot rotate is an outage
  scheduled by the CA.

## Decision 5 — Change discipline

- DNS changes via IaC with review; portal edits are drift.
- Before any change: current records exported, TTL state known, rollback record
  ready.
- Change windows for apex records; the apex affects email and verification too.
- Registrar-level protections: transfer lock, MFA on the registrar account, and a
  second admin with access documented.

## Failure modes at scale

- TTL still 3600 during a migration; rollback takes an hour to take effect.
- CAA record added without the CDN's CA, breaking renewals silently.
- Wildcard record exposing a staging host with production data.
- Registrar account with no MFA; domain hijacked.
- Health check pointed at `/` returning 200 while the API is down.

## Verification receipts

1. Zone inventory and delegation ownership map.
2. TTL policy table with the migration procedure.
3. Failover test: primary endpoint failed, traffic moved, time to recovery measured.
4. Certificate inventory with automation and expiry alerts proven.
5. Registrar security checklist: lock, MFA, auto-renew, billing contact.
