---
name: vue-architect
description: Architect-level Vue guidance — Composition API boundaries, SFC and composable ownership, Pinia vs local vs server state, Nuxt routing/rendering decisions, and the reactivity pitfalls that scale badly. Use when structuring a Vue/Nuxt app or reviewing its state and component boundaries.
license: MIT
compatibility: Vue 3.4+; Nuxt 3/4
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect
  crusor-origin: original
  crusor-sources: "vuejs.org/guide; nuxt.com/docs; pinia.vuejs.org"
  crusor-triggers: "vue, nuxt, composition-api, pinia, composables, reactivity, sfc"
  crusor-verified-on: "2026-10-30"
---

# Vue Architect

## When to use

- Structuring a Vue or Nuxt application.
- Deciding composable ownership, state location, or rendering strategy.
- Reactivity is surprising (lost reactivity, over-rendering, watcher chains).

## When NOT to use

- A single component's template change.

## Decision 1 — App shape

| Need | Choice |
|---|---|
| SEO, SSR/SSG, file routing, server routes | Nuxt |
| SPA behind auth | Vite + Vue Router |
| Content-heavy marketing | Nuxt with prerendering |
| Embeddable widget | Vue + custom element build |

## Decision 2 — Composition API discipline

- Components render; **composables own behaviour** (`useX`) and return a small,
  typed surface.
- A composable that returns 12 refs is a component in disguise — split it.
- Props down, events up; `v-model` is the contract for two-way inputs only.
- No business logic in templates; computed properties are the derivation layer.
- Provide/inject for dependency injection (theme, clients), not for app data.

## Decision 3 — State

| State | Home |
|---|---|
| local UI | `ref`/`reactive` in the owning component |
| shared in a feature | composable with module-scoped refs |
| app-wide client | Pinia store |
| server data | Nuxt `useFetch`/`useAsyncData` or TanStack Query |

- Server data is a cache, not a store.
- Pinia stores are modular, one per domain; no store that knows every entity.
- Never copy a store value into local state and sync with a watcher.

## Decision 4 — Nuxt specifics

- `ssr: true` by default; disable per route deliberately, not globally.
- `useFetch` keyed by params so navigation refetches correctly.
- Server routes (`server/api`) are the only place secrets live; `useRuntimeConfig`
  for env, with `public` restricted to what the client may see.
- Auto-imports are convenient but hide dependencies: keep cross-feature imports
  explicit in reviews.

## Failure modes at scale

- Reactivity lost by destructuring a `reactive` object without `toRefs`.
- `watch` used to derive state that a `computed` should own.
- One mega-store imported everywhere; every change re-renders half the app.
- Composables that call the API directly, bypassing the data layer.
- Nuxt payload bloat: sending server data to the client that no component reads.

## Verification receipts

1. `vue-tsc --noEmit` clean.
2. Route-level data tested for SSR and client navigation.
3. Reactivity check: a mutation updates exactly the intended subtree (devtools).
4. Bundle/route report; no route pulls another feature's store.
5. Secrets audit: nothing sensitive under `runtimeConfig.public`.
