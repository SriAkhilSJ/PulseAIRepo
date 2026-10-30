---
name: seo-architect
description: Architect-level technical SEO for web frontends — crawlability and render strategy, per-route metadata, canonical/robots/sitemap contracts, structured data, and the SPA pitfalls that make content invisible. Use when a site must rank or when pages are not indexing.
license: MIT
compatibility: Framework-agnostic; SSR/SSG/SPA
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/seo-architect
  crusor-origin: original
  crusor-sources: "developers.google.com/search/docs; developers.google.com/search/docs/appearance/structured-data"
  crusor-triggers: "seo, metadata, canonical, robots, sitemap, structured data, json-ld, indexability, meta tags"
  crusor-verified-on: "2026-10-30"
---

# SEO Architect

SEO at the technical layer is **indexability plus clarity**: can the crawler get
the content, and does it know what the page is about?

## When to use

- Public marketing/content pages, product listings, docs, blogs.
- Pages not appearing in search results.
- SPA migrating to SSR/SSG, or adding structured data.

## When NOT to use

- Authenticated apps with no public content — invest in performance and
  accessibility instead.

## Decision 1 — Rendering and indexability

| Strategy | Indexability |
|---|---|
| SSG | best — full HTML, fast |
| SSR | good — full HTML per request |
| SPA (CSR) | risky — content arrives after JS; metadata is invisible to most crawlers |
| Hydrated islands | fine if content is in the HTML |

- Content that must rank is in the initial HTML, not fetched after mount.
- Do not block crawlers with auth walls, cookie gates, or `noindex` left from
  staging.

## Decision 2 — Per-route metadata

- Title (unique, 50–60 chars), description (unique, 120–160), canonical URL.
- Open Graph/Twitter cards for shareable pages; image with correct dimensions.
- One `h1` matching search intent; headings reflect structure.
- Metadata is derived from the route's data, not hard-coded per file.

## Decision 3 — Crawl contracts

- `robots.txt`: allow crawlable paths, point to the sitemap; never block CSS/JS
  the rendering depends on.
- `sitemap.xml`: generated from the content source, canonical URLs only, with
  `lastmod`; split at 50k URLs.
- Canonicals: self-referencing on every page; cross-canonical for
  paginated/filtered variants with `noindex` where appropriate.
- `hreflang` for locale variants, reciprocal and self-referencing.

## Decision 4 — Structured data

- JSON-LD in the page head; `Organization`/`WebSite` site-wide,
  `Product`/`Article`/`FAQPage`/`BreadcrumbList` per content type.
- Every property comes from real page data — invented ratings and prices are a
  penalty risk.
- Validate with the Rich Results test; keep schema and UI in sync.

## Decision 5 — URL and content hygiene

- Human-readable, stable URLs; redirect (301) rather than delete.
- Pagination crawlable with real links, not JS-only buttons.
- No duplicate content across query params; canonicalise.
- Status codes honest: 404 for missing, 410 for gone, never 200-with-error.

## Failure modes at scale

- SPA where every route shares one `<title>` and an empty `<div id="root">`.
- Staging `noindex` shipped to production (or absent from staging).
- Filter combinations generating infinite crawlable URLs.
- Structured data copied from a generator with placeholder ratings.
- Sitemap listing URLs that redirect or 404.

## Verification receipts

1. `curl` the URL and grep the content — is it in the HTML?
2. Unique titles/descriptions across sampled routes.
3. robots.txt + sitemap fetched and validated; no blocked assets.
4. Rich Results test on each structured-data type.
5. Search Console: index coverage, no soft-404 spikes.
