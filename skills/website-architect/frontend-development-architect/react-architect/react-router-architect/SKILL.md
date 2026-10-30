---
name: react-router-architect
description: Architect-level routing for non-Next React apps — choosing React Router data router vs TanStack Router vs TanStack Start, route tree design, loaders and actions, nested layouts, error/404 boundaries, and URL-as-state rules. Use when designing navigation or migrating a client-rendered SPA.
license: MIT
compatibility: React 18+; React Router 7, TanStack Router/Start
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/react-architect/react-router-architect
  crusor-origin: original
  crusor-sources: "reactrouter.com; tanstack.com/router"
  crusor-triggers: "react-router, routing, spa, loaders, tanstack-router, navigation, url-state, nested-routes"
  crusor-verified-on: "2026-10-30"
---

# React Router Architect

## When to use

- A client-rendered React app needs navigation, data loading, or guards.
- Migrating from a hand-rolled route switch or an older router.
- Route-level loading/error handling is missing or duplicated per component.

## When NOT to use

- Next.js App Router (see `nextjs-architect`).
- A single-screen embed with no navigation.

## Decision 1 — Router

| Need | Choice |
|---|---|
| Mature ecosystem, data APIs, framework mode | React Router 7 |
| Type-safe routes/params as a first-class feature | TanStack Router |
| Full-stack TanStack (SSR + server functions) | TanStack Start |
| Tiny SPA, no data loading | React Router in declarative mode |

Type-safety of params is the deciding axis for large route trees.

## Decision 2 — Route tree = UI tree

- Nested routes mirror nested layout; the outlet is the composition point.
- Layout routes hold chrome only; they never fetch feature data.
- Each route declares its own `loader`, `errorElement`, and pending UI.
- 404 is a route, not a `if (!found) return null`.

## Decision 3 — Data at the route, not in effects

- Loaders fetch, routes render, components receive. No `useEffect` fetching on
  mount.
- Actions own mutations; revalidate affected routes after they settle.
- Parallel-load independent route data; defer only what is genuinely slow.
- Params are parsed and validated at the route boundary (`unknown` in, typed
  out).

## Decision 4 — Guards and auth

- Client guards are UX; authorisation is enforced by the API.
- Redirect logic lives in one place (route loader/guard), not in components.
- Deep-link to a protected route must survive login and return to the target.

## Failure modes

- Route components that fetch, transform, and render business rules at once.
- Duplicated loading state per component instead of route-level pending UI.
- Query params read ad hoc inside components rather than through a typed hook.
- Router state (location) copied into a store and kept in sync by effects.

## Verification receipts

1. Route tree printed: path, loader, error boundary, guard.
2. Deep link to a nested route works on a cold load and after refresh.
3. Forced loader failure renders the route's error boundary, not a blank page.
4. Back/forward and param changes do not remount stable layouts.
