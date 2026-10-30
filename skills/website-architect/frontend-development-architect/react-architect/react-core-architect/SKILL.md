---
name: react-core-architect
description: Architect-level React application structure — server/client boundary, component taxonomy, composition over configuration, state locality, effects policy, Suspense and error boundaries, and the import rules that keep a React codebase navigable. Use when designing or reviewing how a React app is organised, not for syntax questions.
license: MIT
compatibility: React 18+ and React 19; framework-agnostic (Vite, Next, Remix, React Router)
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/react-architect/react-core-architect
  crusor-origin: original
  crusor-sources: "vercel-labs/agent-skills@063bee94 (react-best-practices, composition-patterns) — reference only: the repo grants no licence"
  crusor-verified-on: "2026-10-30"
  crusor-triggers: "react components, component composition, react hooks, state locality, error boundary, suspense, folder structure, rerender"
---

# React Core Architecture

React's failure mode is not syntax — it is a component graph with no ownership
model. Your job is to decide **where state lives, where data enters, what may
re-render, and what may import what**, before any component is written.

## When to use

- Designing a new React app or a new feature area.
- A codebase where every change touches five files, or one 900-line component.
- Deciding whether a piece of state belongs to a component, the URL, the server,
  or a store.
- Reviewing a PR that introduces a new context, a new store, or a new fetch.

## When NOT to use

- A single-props or styling change inside an already-governed structure.
- A pure server-side task with no React surface.

## Decision 1 — Rendering model, first

Pick the boundary before the components exist:

| Need | Model |
|---|---|
| Content-first, SEO, mostly static | server-rendered / static (Next App Router, Remix, Astro) |
| Highly interactive, authenticated, behind login | client-rendered SPA is defensible |
| Mixed | server shell + client islands; keep the client boundary at the leaves |

The rule that survives every framework: **push `"use client"` down, never up.**
A single client boundary at the root ships the entire tree to the browser and
removes the server model's benefits while keeping its complexity.

## Decision 2 — Component taxonomy

Every component belongs to exactly one layer:

```
app/          route composition, data wiring, error/loading boundaries
  features/   one product capability: owns its state, hooks and API calls
    ui/       shared, data-free presentational primitives
      lib/    framework-free utilities
```

Import rules (enforce with lint, not with review):

- `app` → `features` → `ui` → `lib`. Never upward.
- `ui` never imports a feature, a store, or a `fetch`.
- Two features never import each other's internals; they exchange props or a
  shared `lib` contract.
- A file that both fetches and renders is a screen, and screens live in `app`.

## Decision 3 — State locality

Default answers, in order:

1. **Component state** — anything only that component reads.
2. **Lifted parent state** — two siblings, one owner, no store.
3. **URL** — anything a user should be able to link, refresh, or back into:
   filters, tabs, pagination, selected entity.
4. **Server cache** — anything that came from the server (TanStack Query/SWR/
   RSC). Never copy it into a client store.
5. **Global store** — only cross-feature, long-lived client state (session UI,
   draft, preferences).

If you cannot name the owner of a piece of state, the design is not finished.

## Decision 4 — Effects are for synchronising with the outside world

`useEffect` is not a data-fetching tool, not a derived-state tool, and not an
event handler. Its only job is to synchronise React with something external
(browser API, subscription, analytics, focus).

- Derive during render; do not mirror props into state.
- Handle user actions in event handlers, not effects watching state.
- Data fetching belongs to the router loader, RSC, or the query library's cache.
- Every subscription returns a cleanup; every effect names what it synchronises.

## Decision 5 — Boundaries are part of the architecture

- **Error boundaries** per route segment and per independently-failing widget.
- **Suspense boundaries** at the same seams, so a slow subtree cannot blank the
  page.
- **Loading and empty states are designed at the seam**, not sprinkled inside
  components: the boundary owns the fallback, the leaf owns the content.
- A boundary that hides an error without a recovery path is a bug, not a
  feature.

## Decision 6 — Composition over configuration

Prefer explicit composition (`<Card><Card.Header/><Card.Body/></Card>`) over
boolean-prop soup (`<Card variant="compact" showHeader hasFooter dense/>`).

- Props describe *what* the component is; children describe *how it is used*.
- A component with more than ~4 boolean variants almost always wants a smaller
  set of composable pieces.
- Never define a component inside another component: identity changes every
  render and the subtree remounts.

## Failure modes at scale

- **Re-render storms** from a single context holding fast-changing values: split
  contexts by update frequency, or subscribe at the leaf.
- **Barrel imports** making every route pay for the whole library: import from
  the module, not the package index.
- **Redundant de-duplication**: query cache + store + local state all holding the
  same payload, each able to drift.
- **Client boundary creep**: one `"use client"` added for a dropdown pulls the
  page into the bundle and nobody notices until LCP regresses.

## Anti-patterns

- `useEffect(() => setX(prop), [prop])` — mirrored state.
- A context that exists to avoid prop-drilling a value used by three siblings.
- Fetch-on-render with no cache, retry, cancellation or loading contract.
- `any` at a component boundary: the contract disappears exactly where it is
  needed.
- Directory-by-filetype (`components/`, `hooks/`, `services/`) at scale — it
  destroys ownership; organise by capability.

## Verification receipts

1. `tsc --noEmit` (or the framework's typecheck) clean.
2. Lint rule proving the import direction (no feature → app, no ui → feature).
3. A render-count or profiler check on the hottest interaction.
4. Bundle report: no route pulls a library it does not use.
5. The route's error + loading states exercised (boundary test), not just the
   happy path.
