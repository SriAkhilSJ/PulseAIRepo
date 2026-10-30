---
name: nextjs-architect
description: Architect-level Next.js guidance — App Router topology, choosing static vs dynamic vs streaming rendering, the four cache layers and how to reason about them, server action and route-handler boundaries, auth and data access placement, deployment topology, and the version changes from 13 to 16. Use when designing, reviewing or restructuring a Next.js codebase.
license: MIT
compatibility: Next.js 14+ (App Router). Pages Router is covered only for migration decisions.
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/react-architect/nextjs-architect
  crusor-origin: original
  crusor-sources: "nextjs.org/docs (App Router, caching, server actions); vercel-labs/agent-skills@063bee94 (react-best-practices server rules)"
  crusor-verified-on: "2026-10-30"
  crusor-triggers: "nextjs, next.js, app-router, rsc, server-components, caching, revalidate, server-actions, ssr, streaming"
---

# Next.js Architecture

Next.js gives you four caching layers, two rendering modes and three places to
put server code. Most production problems are a **boundary** problem: something
is client-side that should not be, or something is cached that should not be.

## When to use

- Choosing App Router vs Pages Router (or planning the migration).
- Deciding where a fetch, a mutation, or an auth check lives.
- A page is stale, slow, or re-renders on every navigation and the cache is the
  suspect.
- Reviewing route structure before the app grows past a handful of screens.

## When NOT to use

- A component-level change with no data, cache or routing consequence.
- A pure SPA where Next.js is not the target.

## Decision 1 — Router

| Situation | Choice |
|---|---|
| New app | App Router |
| Existing Pages Router app, stable | stay; migrate per-route when that route needs layouts, streaming or RSC |
| Hybrid during migration | both routers can coexist; do not share layouts across the boundary |

Migration rule: move **leaf routes** first, never the shell. Two routers sharing
a root layout is where migrations stall.

## Decision 2 — Rendering strategy per route

Be explicit for every route; "it depends" is how stale pages ship.

| Route character | Strategy |
|---|---|
| Same for all users, changes rarely | static (default) with `revalidate` |
| Content that must be fresh per request | dynamic (`cookies()`, `headers()`, `noStore`) |
| Personalised shell, shared body | static shell + dynamic holes + Suspense streaming |
| Slow data, page usable early | stream with `loading.tsx`/Suspense at the seam |
| Write path | server action or route handler — never a client-side secret |

One `cookies()` call turns the whole route dynamic. Place dynamic reads as deep
as possible, and know which file introduces them.

## Decision 3 — The four caches

| Cache | What it holds | How it is invalidated |
|---|---|---|
| Request memoisation | one render pass, duplicate `fetch` | automatic |
| Data cache | `fetch` results across requests | `revalidateTag`, `revalidatePath`, time |
| Full route cache | rendered static route | redeploy, revalidation, dynamic APIs |
| Client router cache | prefetched route payloads | navigation, `router.refresh()`, time |

Rules:

- Tag every non-trivial `fetch` (`next: { tags: [...] }`) — revalidation without
  tags becomes guesswork.
- After a mutation, invalidate **by tag, in the action**, not by hoping the
  client refetches.
- `router.refresh()` is a client cache fix, not a data-freshness strategy.
- A stale UI report is answered by naming which of the four caches is stale —
  if you cannot name it, you have not diagnosed it.

## Decision 4 — Where server code lives

```
app/route/            composition + boundaries only
app/route/actions.ts  mutations ("use server"), validate, authorise, invalidate
app/api/route/        route handlers for external/webhook/streaming contracts
lib/server/           data access + auth helpers, imported only by server code
lib/client/           browser-only helpers
components/           shared UI; "use client" only at interactive leaves
```

- Server actions are **public endpoints**: validate input, check authorisation,
  and never trust a hidden field.
- The data layer returns plain serialisable data; do not pass ORM entities or
  class instances across the RSC boundary.
- Secrets, database clients and SDK keys stay in `lib/server` and never reach a
  `"use client"` module.

## Decision 5 — Client boundary discipline

- `"use client"` at the leaf that needs interactivity, not at the layout.
- Pass server data down as props; do not import server modules into client
  components.
- Keep the client bundle's dependency budget explicit: charts, editors and
  date libraries load via `next/dynamic` behind a real interaction.

## Failure modes at scale

- **Sequential awaits** in a route or layout: fetch independent data in
  parallel; waterfalls dominate TTFB long before the database does.
- **Dynamic creep**: an analytics call using `headers()` turns every route
  dynamic and silently disables static optimisation.
- **Over-fetching to the client**: sending a whole record so the client can
  render three fields inflates the RSC payload on every navigation.
- **Cache confusion**: `revalidate = 0` added to "fix" staleness, converting a
  static route into a per-request render.
- **Auth in the wrong layer**: UI-level gating without a server-side check.

## Anti-patterns

- A single `"use client"` layout wrapping the whole app.
- `useEffect` fetching on mount in a framework that already has a server.
- A route handler duplicating a server action (two contracts, one behaviour).
- Mutating data in a `GET` handler or in a server component render.
- Relying on the router cache for correctness ("it updates after a click").

## Version notes (13 → 16)

- App Router remains the default; Pages Router is maintenance-only for new work.
- Server Actions are stable; treat them as public API from the first commit.
- `fetch` caching defaults have changed across releases — state the policy
  explicitly per route instead of inheriting the default of the day.
- Partial Prerendering / streaming holes graduate over these versions; when
  enabled, verify per-route behaviour rather than assuming a global switch.
- Always pin the Next.js major and record it in `metadata.crusor-sources`.

## Verification receipts

1. `next build` output: which routes are static, dynamic, or streamed — read it,
   do not assume it.
2. A production-mode request per critical route (dev mode hides caching).
3. Mutation → tag invalidation → fresh render, demonstrated end to end.
4. Client bundle report for the heaviest route.
5. An unauthenticated request against a protected action/route, showing denial.
