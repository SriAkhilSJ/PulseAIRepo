---
name: web-performance-architect
description: Architect-level web performance — Core Web Vitals as release budgets, critical-path and rendering strategy, image/font/JS cost, caching and delivery, and the measurement discipline (lab plus field) that keeps a site fast after launch. Use when a site is slow or when setting performance gates.
license: MIT
compatibility: Framework-agnostic; any CDN and browser
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/web-performance-architect
  crusor-origin: original
  crusor-sources: "web.dev/vitals; web.dev/learn/performance; developer.mozilla.org/Performance"
  crusor-triggers: "web performance, core web vitals, lcp, inp, cls, lighthouse, bundle size, page speed, slow site, slow page, site is slow, http caching, web fonts"
  crusor-verified-on: "2026-10-30"
---

# Web Performance Architect

Performance is a **budget you spend deliberately**, measured on the user's device
and network — not a score you chase after launch.

## When to use

- Setting performance gates for a new site or a redesign.
- LCP/INP/CLS failing in the field.
- Choosing rendering strategy, image pipeline, or font loading.

## When NOT to use

- Micro-optimising before architecture is set — fix the critical path first.

## Decision 1 — The budgets (75th percentile, mobile)

| Metric | Target | Owns |
|---|---|---|
| LCP | < 2.0 s | critical path, hero image, server time |
| INP | < 200 ms | main-thread work, hydration, event handlers |
| CLS | < 0.1 | layout stability, images/fonts/ads |
| TTFB | < 0.8 s | server/CDN/cache |
| JS shipped | < 170 kB gzip (initial route) | architecture |

Budgets are per route type (marketing vs app), declared in CI, and failing them
fails the build.

## Decision 2 — Critical path

- HTML → critical CSS → LCP resource → rest. Everything else is deferred.
- Server rendering or static generation for anything above the fold; client-only
  rendering is a measured decision, not a default.
- Preload exactly one LCP candidate; preloading many wastes bandwidth.
- Third-party scripts load after interaction/idle, never blocking.

## Decision 3 — Assets

| Asset | Rule |
|---|---|
| images | AVIF/WebP, `srcset`+`sizes`, explicit dimensions, lazy below fold |
| fonts | `font-display: swap`, self-hosted subset, max 2 families, preload the one used above the fold |
| video | poster + no autoplay with sound; never in the LCP path |
| icons | inline SVG sprite; no icon font |

## Decision 4 — Main thread and hydration

- Ship less JS: route-level code splitting, no barrel imports, tree-shaken
  libraries.
- Hydration is a cost: prefer islands/partial hydration where the framework
  allows.
- Long tasks (>50 ms) are the enemy of INP: break work, move it off the main
  thread (workers), or remove it.
- Lists over ~100 rows virtualise; animation uses transform/opacity only.

## Decision 5 — Delivery

- Immutable hashed assets, long `max-age`; HTML short-lived with revalidation.
- CDN in front of everything static; compression (br). HTTP/2+.
- Cache headers verified in production, not assumed.

## Decision 6 — Measurement

- **Field** (RUM) is the source of truth: p75 by device/route/country.
- Lab (Lighthouse/WebPageTest) for regressions and PR gates.
- Budget in CI on bundle size; a perf trace attached to perf-sensitive PRs.

## Failure modes at scale

- A green Lighthouse score on a fast laptop while p75 mobile LCP is 5 s.
- A 900 kB JS entry because one dependency was imported at the root.
- Hero image without dimensions → CLS on every load.
- Font loading blocking text render for a second.
- Performance regressions merged because nothing measured them.

## Verification receipts

1. Field p75 LCP/INP/CLS per route, before and after.
2. Bundle report: initial JS within budget per route.
3. Hero/LCP request waterfall: one candidate, preloaded, cached.
4. CLS trace with no layout shift from images or fonts.
5. Cache headers verified on the production CDN.
