---
name: redux-toolkit-architect
description: Architect-level Redux Toolkit guidance — slice boundaries and normalization, thunk/RTK Query separation, selector discipline, middleware ownership, and the store-shape decisions that decide whether Redux helps or becomes a global mutable bag. Use when a React app needs a real global store.
license: MIT
compatibility: Redux Toolkit 2.x; React 18+
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/react-architect/redux-toolkit-architect
  crusor-origin: original
  crusor-sources: "redux-toolkit.js.org; redux.js.org/style-guide"
  crusor-triggers: "redux, rtk, redux toolkit, redux slice, createasyncthunk"
  crusor-verified-on: "2026-10-30"
---

# Redux Toolkit Architect

Redux is **not** a state cache; it is a shared, inspectable event log. Adopt it
when several unrelated parts of the app must agree on the same truth.

## When to use

- Cross-cutting state with many independent readers/writers (auth, cart,
  editor documents).
- Time-travel debugging or action auditing is a requirement.
- Server state needs a cache too — then RTK Query, not hand-written thunks.

## When NOT to use

- Server data only (TanStack Query / RTK Query alone).
- One or two components sharing a value (context or lift state).
- Modal flags and hover state — that is component state.

## Decision 1 — Slices are contexts, not entities

- One slice per **business context** (`cart`, `checkout`, `auth`), never per
  entity or per component.
- State is normalized (`entities: {byId, ids}`) when lists are long or shared.
- Slice reducers are pure and small; derived values are selectors, not state.
- Cross-slice updates happen in middleware/listeners, not by importing another
  slice's reducers.

## Decision 2 — Server state vs client state

| Concern | Tool |
|---|---|
| remote data, caching, refetch | RTK Query |
| local mutations of that data | optimistic updates on the cache, not a copy in a slice |

Never mirror server data into a slice — that is the classic divergence bug.

## Decision 3 — Selectors

- Selectors live with the slice, are typed, and take `RootState`.
- Components subscribe to the narrowest slice; `useSelector` returning new
  objects every call causes re-render storms — use memoised selectors.
- Derived/computed lists are memoised selectors, not `useEffect` + `useState`.

## Decision 4 — Side effects

- Thunks for command-like flows (submit → dispatch → invalidate).
- Listeners for reacting to actions (analytics, persistence, cross-slice rules).
- Side effects do not live in reducers, ever.
- Persistence is explicit (`redux-persist` allowlist), never "the whole store".

## Decision 5 — Store shape review

- Flat where possible; nesting only where it mirrors the domain.
- No functions, class instances, or Dates-as-objects in state (serialisability
  is what makes devtools and persistence work).
- Devtools in dev only; production middleware minimal.

## Failure modes at scale

- A `ui` slice holding every modal, tab and hover — the store becomes a dump.
- Server data copied into a slice → stale everywhere after a refetch.
- `useSelector(s => ({a: s.a, b: s.b}))` → re-render on every action.
- 40 slices with circular listener dependencies.
- Redux for everything, and now nothing can be tested without a store.

## Verification receipts

1. Store shape diagram reviewed; each slice names its owning context.
2. Render-count check on a hot component under unrelated actions.
3. Persistence allowlist reviewed (no tokens beyond what is needed).
4. Reducer purity audit: no side effects, no non-serialisable values.
5. A page can be tested with a minimal store (not the full app store).
