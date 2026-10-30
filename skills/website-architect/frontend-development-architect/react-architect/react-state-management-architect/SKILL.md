---
name: react-state-management-architect
description: Architect-level state strategy for React apps — deciding between local, lifted, URL, server-cache and global state, and choosing among TanStack Query, SWR, Zustand, Redux Toolkit, Jotai and Context. Use when state is being duplicated, synced by effects, or when adding a store is on the table.
license: MIT
compatibility: React 18+; framework-agnostic
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/react-architect/react-state-management-architect
  crusor-origin: original
  crusor-sources: "react.dev/learn/managing-state; tanstack.com/query; zustand docs; redux-toolkit docs; vercel-labs/agent-skills@063bee94 (react-best-practices)"
  crusor-verified-on: "2026-10-30"
  crusor-triggers: "react state, client state, state ownership, zustand, jotai, context vs store, url state, app state, server state ownership"
---

# React State Management (decision skill)

There is no "React state library" problem. There are **five kinds of state**, and
most architecture failures come from putting one kind in another kind's home.

## When to use

- Before adding any store, context or query client.
- When a value needs `useEffect` to stay in sync with another value.
- When two screens disagree about the same entity.
- When the team cannot answer "who owns this state?"

## When NOT to use

- A value used by one component: it is `useState`, decision over.
- A styling or rendering change with no new state.

## The five homes

| Kind | What it is | Home |
|---|---|---|
| Local UI | open/closed, hover, draft text | `useState` in the owning component |
| Lifted | shared by siblings | nearest common parent |
| URL | filters, tab, page, selected id, query | router search params |
| Server | anything the backend is the source of truth for | TanStack Query / SWR / RSC |
| Global client | cross-feature, session-lifetime UI or drafts | Zustand / Redux Toolkit / Jotai |

Decision rule: **server data is a cache, not state.** If the server owns it, a
client store must not also own it.

## Choosing the library

| Need | Use | Why not the others |
|---|---|---|
| Server data, caching, revalidation | **TanStack Query** (or SWR if minimal) | a global store gives you no invalidation, dedupe or staleness model |
| Small global client state, minimal ceremony | **Zustand** | Redux's ceremony buys nothing at this size |
| Large app, devtools/audit, event-sourced updates | **Redux Toolkit** | Zustand gives no action log or enforced reducer boundaries |
| Many independent atoms, fine-grained subscriptions | **Jotai** | one big store over-renders or needs manual selector discipline |
| Values that rarely change (theme, locale, auth user) | **Context** | context re-renders every consumer on change |

Two libraries maximum. A codebase with a query client, a store *and* a context
holding the same entity has three sources of truth and zero owners.

## Boundaries

- **Query owns the entity lifecycle** (fetch, cache, invalidate). Components read
  from the query cache; mutations invalidate tags/keys.
- **Store owns client-only facts**: selected rows, unsaved draft, panel layout,
  wizard step. It must be serialisable and must not contain server payloads.
- **URL owns anything shareable** — if refreshing should preserve it, it belongs
  in the URL, not the store.
- **Context owns dependency injection** (theme, i18n, client instances), not
  application data.

## Rules that prevent the usual rewrite

1. **Derive, don't sync.** If B is computed from A, compute it during render.
   `useEffect` mirroring is the signature of a missing derivation.
2. **One writer per fact.** A fact written by two layers will eventually
   disagree.
3. **No fetching in components when a query hook exists.** Otherwise you get
   duplicate requests and per-component loading states.
4. **Select narrowly.** Subscribe to the field, not the object; shallow-compare
   only when the shape is truly stable.
5. **Normalise only when there is a real need** (same entity in several views,
   or updates that must propagate). Otherwise keep server data in the query
   cache untouched.
6. **Store shape is part of the public contract.** Renaming a slice is a
   migration, not a refactor.

## Failure modes

- Query cache + Zustand + local state holding the same list — three copies, one
  refresh path, guaranteed drift.
- A global store created for a modal's open flag.
- Context provider at the root holding a rapidly changing value; every consumer
  re-renders on every keystroke.
- Optimistic update with no rollback path.
- Storing derived booleans (`isValid`, `hasChanges`) instead of the inputs.

## Anti-patterns

- `useEffect(() => setLocal(serverValue), [serverValue])`.
- `useState` + `useEffect` fetch in a codebase that already has a query client.
- Redux for a form; the form library already owns that state.
- Passing setters four levels down instead of lifting, or lifting when the
  value belongs in the URL.
- A store whose actions call `fetch` directly, bypassing the cache layer.

## Verification receipts

1. A refresh of the page preserves everything that lives in the URL.
2. A mutation invalidates and refetches exactly the affected query keys (log the
   keys, do not assume).
3. Render-count check: typing in an input does not re-render unrelated screens.
4. Devtools/state dump shows one copy of each entity.
5. Tests: the query hook's loading/error/empty paths, not just success.
