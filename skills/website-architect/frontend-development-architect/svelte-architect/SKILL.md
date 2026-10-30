---
name: svelte-architect
description: Architect-level Svelte and SvelteKit guidance — runes-era reactivity ownership, SvelteKit routing and load functions, server/client boundaries, form actions, and the state rules that keep a Svelte app predictable. Use when structuring a Svelte/SvelteKit app or migrating pre-runes code.
license: MIT
compatibility: Svelte 5 (runes); SvelteKit 2
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/svelte-architect
  crusor-origin: original
  crusor-sources: "svelte.dev/docs; kit.svelte.dev/docs"
  crusor-triggers: "svelte, sveltekit, runes, load-functions, form-actions, ssr, reactivity"
  crusor-verified-on: "2026-10-30"
---

# Svelte Architect

## When to use

- Structuring a SvelteKit app: routes, load functions, server boundary.
- Deciding where state lives with runes.
- Migrating stores/pre-runes reactivity to Svelte 5.

## When NOT to use

- A single component's markup change.

## Decision 1 — SvelteKit first

- SvelteKit for anything with routing, SSR, or server code.
- `+page.ts` (universal) vs `+page.server.ts` (server-only): anything touching
  secrets, a database or a private API lives in `.server`.
- `+layout` holds chrome and shared data; it must not fetch per-page data.
- Route-level `load` owns fetching; components receive data as props.

## Decision 2 — Reactivity with runes

- `$state` for mutable state, `$derived` for computed values, `$effect` only to
  synchronise with the outside world.
- Never derive state in an effect — that is what `$derived` is for.
- `$state.raw` for large immutable structures replaced wholesale.
- Props via `$props()` with explicit types; `$bindable` only for genuine two-way
  inputs.
- Class-based state is legitimate: a `.svelte.ts` module with runes is the
  composable equivalent.

## Decision 3 — State ownership

| State | Home |
|---|---|
| component-local | `$state` |
| shared within a feature | `.svelte.ts` module with runes |
| app-wide client | one store module, explicit exports |
| server data | `load` functions |
| URL | route params + `url.searchParams` |

Store server data in `load`, not in a client store that then re-fetches.

## Decision 4 — Forms and mutations

- Progressive enhancement is the default: `<form method="POST">` + `actions`
  works without JS, then enhance.
- Validate on the server; return typed `fail()` results and render them.
- Invalidate dependent data after a successful action; do not manually refetch.

## Failure modes at scale

- Effects used for derivation, producing loops and stale renders.
- Mixing legacy stores and runes in one feature with unclear ownership.
- Secrets or DB clients imported into universal load/component code.
- `load` duplicated at layout and page level, causing double fetches.
- Client-side guards treated as authorisation.

## Verification receipts

1. `svelte-check` clean with strict TS.
2. Form works with JavaScript disabled (progressive enhancement).
3. Server-only module audit: nothing from `$lib/server` reaches the client bundle.
4. Navigation test: layout state preserved, page data refreshed.
5. Effect audit: every `$effect` names the external system it synchronises.
