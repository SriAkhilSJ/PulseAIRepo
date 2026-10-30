---
name: react-architect
description: Framework-level React architecture — how the React branch fits together, when to pull react-core / nextjs / react-router / state-management / ui-libraries / testing, the app shell and routing model, and the rules that keep a React app from becoming a component soup. Use first for any React project, then the leaf skill it names.
license: MIT
compatibility: React 18+ / 19; framework: Next.js, React Router, TanStack Start, Vite SPA
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/react-architect
  crusor-origin: original
  crusor-sources: "react.dev; nextjs.org; tanstack.com/router; reactrouter.com"
  crusor-triggers: "react app structure, react app shell, react spa, nextjs, react-router, react framework choice"
  crusor-verified-on: "2026-10-30"
---

# React Architect (framework entry point)

This is the **navigation skill** for the React branch. It decides the app's shape
and names the leaf skill that owns each concern.

## When to use

- Starting a React app and choosing framework, shell and routing model.
- Reviewing a React codebase whose boundaries have blurred.
- Deciding where cross-cutting rules live before they multiply.

## When NOT to use

- Component-level API questions — take `react-core-architect`.
- Server-side structure — take the backend shelf.

## Leaf map

| Concern | Skill |
|---|---|
| component boundaries, composition, render model | `react-core-architect` |
| rendering strategy, caching, server actions | `nextjs-architect` |
| routes, loaders, nested layouts (non-Next) | `react-router-architect` |
| state ownership and libraries | `react-state-management-architect` |
| component libraries, headless primitives, theming | `react-ui-libraries-architect` |
| what to test at which layer | `react-testing-architect` |
| Node.js services, streams, workers, shutdown | `nodejs-architect` |
| remote data, caching, invalidation | `tanstack-query-architect` |
| genuine global client state | `redux-toolkit-architect` |
| 3D / WebGL scenes, render-loop budgets | `threejs-architect` |

## Decision 1 — Framework, before components

| Need | Choice |
|---|---|
| SEO, server rendering, file-based routing, server actions | Next.js App Router |
| SPA behind auth, rich client state, no SEO requirement | React Router (data router) or TanStack Start |
| Content site with islands | Astro (see `astro-architect`) |
| Library / embeddable widget | Vite + React, no router |

Pick one and record it. A codebase with two routers is a migration that stopped
halfway.

## Decision 2 — The app shell

```
app entry      providers, error boundary, router, suspense
  layout       persistent chrome (nav, sidebar) — no data fetching per child
    route      composition + loading/error boundaries
      feature  owns state, hooks, API calls
        ui     presentational, data-free
```

Rules:

- Providers are ordered and minimal: query client → theme → auth → router.
- The shell never fetches feature data; each route owns its data.
- One error boundary per route, one Suspense boundary per independently slow
  region.
- Layouts are stable across navigation; anything that remounts per route belongs
  inside the route.

## Decision 3 — Routing model

- URLs are state: filters, tabs, pagination, selected entity.
- Route-level data loading (loader/RSC) beats fetch-on-mount.
- Nested routes mirror nested UI; a route that renders one giant component has
  not been routed, only hidden.
- Protected routes are enforced on the server; the client guard is UX only.

## Decision 4 — Cross-cutting rules

- `"use client"` at leaves, never at the root (when the framework has RSC).
- No global store before the state skill has ruled out URL/server/local.
- Component libraries enter through a wrapper layer, never imported directly
  across features.
- One design token source feeds every styling approach.

## Failure modes at scale

- Router and framework chosen after components exist, forcing a rewrite.
- Every feature importing every provider: coupling with no owner.
- Route files that both fetch and render business logic.
- Two state systems (query client + store) owning the same entity.

## Verification receipts

1. Route tree printed and reviewed (depth, loaders, boundaries).
2. Fresh navigation to each critical route in production mode.
3. One deliberate error in a route → boundary renders, app survives.
4. Bundle report per route; no route ships another route's feature code.
