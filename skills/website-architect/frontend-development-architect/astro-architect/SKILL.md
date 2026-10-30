---
name: astro-architect
description: Architect-level Astro guidance — islands architecture, choosing static vs SSR vs hybrid output, content collections and schemas, framework island boundaries, and the performance contract that makes Astro worth using. Use when building content sites, marketing pages or docs that need selective interactivity.
license: MIT
compatibility: Astro 4/5; optional React/Vue/Svelte islands
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect
  crusor-origin: original
  crusor-sources: "docs.astro.build (islands, content collections, rendering modes)"
  crusor-triggers: "astro, islands, content-collections, ssr, static-site, hydration, marketing-site, docs"
  crusor-verified-on: "2026-10-30"
---

# Astro Architect

## When to use

- Content-heavy sites: marketing, docs, blogs, catalogues.
- Mostly static pages with a few interactive regions.
- SEO and Core Web Vitals are the primary constraint.

## When NOT to use

- A highly interactive application (SPA/dashboard) — Astro's island model fights
  you there.
- Realtime, authenticated app shells.

## Decision 1 — Rendering mode

| Need | Output |
|---|---|
| Content, no per-request data | `static` (default) |
| Auth, personalisation, API routes | `server` |
| Mostly static + a few dynamic endpoints | `hybrid` |

Every page states its mode. A page silently promoted to SSR loses the caching
model that justified Astro.

## Decision 2 — Islands are the architecture

- Static HTML is the default; interactivity is an **explicit island** with a
  hydration directive (`client:load`, `client:idle`, `client:visible`,
  `client:only`).
- Choose the cheapest directive that satisfies the interaction; `client:load` on
  everything recreates an SPA with extra steps.
- Islands cannot share client state — if two regions must share state, that is
  one island, or a deliberate store.
- Framework components are leaves; pages and layouts stay Astro.

## Decision 3 — Content collections

- Schemas (`src/content/config.ts`) are the contract: typed frontmatter,
  validated at build.
- Content references use `reference()` for relations instead of free strings.
- Draft/publish state is schema-driven, not filename convention.
- Images go through `astro:assets` for optimisation; raw `<img>` is an exception.

## Decision 4 — Server boundary

- Server endpoints (`src/pages/api/*`) own secrets; `import.meta.env` values
  prefixed `PUBLIC_` are the only ones shipped.
- Data fetching in `.astro` frontmatter runs at build (static) or request (SSR);
  state that distinction in the component.
- Auth checks live in middleware, not in page components.

## Failure modes at scale

- Islands everywhere: hydration cost without the SPA benefits.
- Shared state attempted across islands through globals or events.
- Content schema drift (unvalidated frontmatter) breaking builds months later.
- SSR enabled to fix one page, disabling caching for all.
- Client components importing server-only modules.

## Verification receipts

1. Build output per route: static vs server, and why.
2. Island inventory: component, directive, and justification.
3. Lighthouse on the heaviest page (LCP/CLS/INP) with JS disabled sanity check.
4. Content collection validation passes; broken relations fail the build.
5. Secrets audit: no non-`PUBLIC_` env value in the client bundle.
