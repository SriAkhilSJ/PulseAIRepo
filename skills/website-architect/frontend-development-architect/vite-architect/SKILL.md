---
name: vite-architect
description: Architect-level Vite guidance — dev-server vs build pipeline boundaries, chunking and dependency pre-bundling, environment and proxy configuration, library vs app mode, and the build-output budgets that keep a frontend fast. Use when setting up or debugging a Vite build.
license: MIT
compatibility: Vite 5/6+; Node 20+
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/frontend-development-architect/vite-architect
  crusor-origin: original
  crusor-sources: "vite.dev/config; rollupjs.org"
  crusor-triggers: "vite, vite config, bundler, rollup, esbuild, code splitting, hmr"
  crusor-verified-on: "2026-10-30"
---

# Vite Architect

Vite is two tools with different rules: a **native ESM dev server** and a
**Rollup production build**. Most "works in dev, breaks in prod" bugs are that
difference.

## When to use

- A new frontend app or library build.
- Build output is too large, or chunks are mis-split.
- Dev server slow to start, or proxy/env behaviour is inconsistent with prod.

## When NOT to use

- Server-rendered frameworks that own their build (Next, Nuxt) — configure them,
  don't wrap Vite around them.
- Legacy browser targets that need a different pipeline — say so explicitly.

## Decision 1 — Dev ≠ prod

- Dev serves unbundled ESM; prod is Rollup. Anything relying on bundler-specific
  behaviour (CJS interop, `process.env`, `__dirname`) must be handled explicitly.
- `optimizeDeps.include` for deep CJS dependencies that pre-bundling misses.
- HMR boundaries: state that must survive a hot update lives in a module with an
  `import.meta.hot.accept` handler, not in component closure.

## Decision 2 — Environment and configuration

- `import.meta.env` only with the `VITE_` prefix; **never** put secrets there —
  everything shipped to the browser is public.
- `base` set for non-root deployments; asset URLs derived, never hard-coded.
- Dev proxy mirrors prod routes so relative URLs work in both.
- One config file with explicit modes; no env-specific code inside components.

## Decision 3 — Chunking

| Intent | Approach |
|---|---|
| framework/vendor stability | manual chunk for react/vue runtime |
| route-level code split | dynamic import per route |
| heavy, rarely-used UI | lazy boundary with a loading state |
| shared components | let Rollup hoist; don't over-split |

- Budgets: entry < 200 kB gzip, per-route chunk < 150 kB.
- `build.rollupOptions.output.manualChunks` is a decision, reviewed like code.
- No barrel file re-exporting an entire library — it defeats tree-shaking.

## Decision 4 — Library vs app

- Libraries: `build.lib`, externalise peer dependencies, emit types separately,
  preserve modules when the consumer needs deep imports.
- Apps: hash assets, set long cache headers, `build.sourcemap` hidden in prod.

## Failure modes at scale

- One 2 MB entry chunk because everything is imported from a barrel.
- `process.env.X` undefined in prod (works in some dev setups).
- Secrets in `VITE_*` variables, shipped to every browser.
- Proxy configured in dev only → broken URLs after deploy.
- Manual chunks tuned per-file, then never revisited.

## Verification receipts

1. `vite build` output reviewed: chunk count, sizes, no single monolith.
2. Bundle analyser screenshot in the PR for build-affecting changes.
3. Prod build run locally with the real env; deep link + refresh tested.
4. No `VITE_*` secret audit.
5. Cold dev-server start and HMR timing recorded.
