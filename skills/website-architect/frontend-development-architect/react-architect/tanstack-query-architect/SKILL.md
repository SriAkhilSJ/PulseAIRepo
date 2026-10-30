---
name: tanstack-query-architect
description: Architect-level TanStack Query (React Query) guidance — server-state ownership versus client state, query key design, cache lifetime and invalidation strategy, mutation and optimistic-update contracts, and the cache bugs that surface only in production. Use when a React app fetches remote data.
license: MIT
compatibility: TanStack Query v5; React 18+
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/react-architect/tanstack-query-architect
  crusor-origin: original
  crusor-sources: "tanstack.com/query/latest/docs/framework/react/overview"
  crusor-triggers: "tanstack query, react query, usequery, usemutation, server state, invalidation"
  crusor-verified-on: "2026-10-30"
---

# TanStack Query Architect

Server state is a **cache with an owner**, not application state. Everything
here answers one question: who is allowed to say a cached value is stale?

## When to use

- A React app fetches or mutates remote data.
- Data is duplicated across components, refetched on every mount, or goes stale
  silently after a write.
- Choosing between query cache, global store, and component state.

## When NOT to use

- Client-only state (modal open, form draft) — that is not server state.
- Single fetch with no reuse — a plain `fetch` in a loader is enough.

## Decision 1 — State ownership

| State | Home |
|---|---|
| remote records, lists, pagination | TanStack Query |
| UI state (open, selected tab) | component state |
| app-wide client state (theme, session flags) | small store or context |
| form drafts | local/form library |

Rule: if it came from the network, it does not belong in Redux/Zustand. Two
owners = two truths = the bug you cannot reproduce.

## Decision 2 — Query keys are an API

- Keys are arrays built by one factory: `['orders', {status, page}]`.
- Every variable that changes the response appears in the key. Miss one and you
  serve the wrong cache entry.
- Keys are shared with invalidation — inventing ad-hoc strings breaks the link.
- `enabled` gates dependent queries; `select` derives without re-fetching.

## Decision 3 — Freshness

| Data | staleTime |
|---|---|
| user profile, settings | minutes |
| lists that change on writes | 0–30 s + invalidation |
| reference data (countries, plans) | hours |
| live dashboards | short poll or push |

- Defaults are set once at the provider, not per hook.
- Pagination/infinite lists: keep previous data to avoid layout collapse.
- Retries: bounded, with backoff; never retry a 4xx.

## Decision 4 — Mutations

- Every mutation declares what it invalidates — the write path owns cache
  correctness, not the read path.
- Optimistic updates require a rollback path and an id strategy for new rows.
- `onSuccess` invalidates; do not hand-patch caches unless you can name why.
- Concurrency: last-write-wins is a decision, not an accident.

## Decision 5 — Server rendering

- Prefetch on the server/loader, dehydrate, hydrate on the client; keys must be
  identical on both sides.
- Never let the client refetch immediately after hydration (set `staleTime`).

## Failure modes at scale

- The same data fetched by three hooks with three keys → three truths.
- `staleTime: Infinity` set globally, then "data doesn't update".
- Optimistic update without rollback → phantom records after a failed write.
- Query in a component that mounts 50 times → request storm.
- Cache never garbage collected because the key holds a new object each render.

## Verification receipts

1. Key factory reviewed; every response variable present in the key.
2. Mutation → invalidation map documented per write.
3. Network tab: one request per logical read, no duplicates on mount.
4. Failed-write path: UI reverts, error surfaced.
5. SSR hydration: no double fetch, same data on both sides.
