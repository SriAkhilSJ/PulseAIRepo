---
name: react-ui-libraries-architect
description: Architect-level component-library strategy for React — headless primitives vs styled kits (Radix, shadcn/ui, MUI, Chakra), the wrapper layer, theming and token integration, accessibility ownership, and how to avoid leaking a vendor API across every screen. Use when adopting, replacing or governing a UI library.
license: MIT
compatibility: React 18+; Radix, shadcn/ui, MUI, Chakra, Headless UI
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/react-architect
  crusor-origin: original
  crusor-sources: "radix-ui.com; ui.shadcn.com; mui.com; chakra-ui.com"
  crusor-triggers: "ui-library, component-library, shadcn, radix, mui, chakra, design-system, theming, accessibility"
  crusor-verified-on: "2026-10-30"
---

# React UI Libraries Architect

## When to use

- Choosing a component library, or governing one already in use.
- Vendor APIs have leaked into feature code and upgrades are impossible.
- Theming, tokens and accessibility are inconsistent across screens.

## When NOT to use

- A single component's styling inside an established wrapper.

## Decision 1 — Headless vs styled

| Need | Choose | Trade-off |
|---|---|---|
| Full design control, own tokens | headless + Tailwind/CSS (Radix, Headless UI, React Aria) | you own every visual state |
| Ship fast, consistent defaults | styled kit (MUI, Chakra, Mantine) | theming limits, bundle weight |
| Own design + accessible behaviour, minimal code | shadcn/ui (copied-in components) | you own the code and its upgrades |
| Complex data grids/trees | specialised library behind a wrapper | largest escape risk |

## Decision 2 — Always a wrapper layer

```
feature  →  ui/  (our wrapper API)  →  vendor library
```

- Features import our components, never the vendor's.
- The wrapper owns variants, sizes, tokens, and state coverage; the vendor owns
  behaviour.
- A vendor upgrade should touch one directory, not 400 imports.

## Decision 3 — Theming and tokens

- Vendor theme is generated **from** our tokens, never the source of truth.
- Dark mode is a semantic remap; no component-level colour overrides.
- Spacing/radius/type come from the token scale; vendor defaults are replaced,
  not mixed.

## Decision 4 — Accessibility ownership

- Behaviour (focus trap, ARIA, keyboard) is the vendor's contract — verify it,
  do not re-implement it.
- Labels, descriptions, error text and landmarks are ours.
- Every wrapper ships: default, hover, focus-visible, disabled, loading, error.

## Failure modes

- Vendor components imported directly across features (upgrade deadlock).
- Two libraries for the same job (two modal systems, two date pickers).
- Deep style overrides into vendor internals (`.MuiXxx-root-123`).
- Theming by CSS overrides instead of tokens; dark mode half-broken.
- Accessibility assumed because "the library says it's accessible" — never
  verified with a keyboard.

## Verification receipts

1. Import audit: vendor names appear only inside `ui/`.
2. Keyboard + screen-reader pass on dialog, menu, combobox, tabs.
3. Dark-mode screenshot of every wrapper's states.
4. Bundle cost per library, per route.
5. Upgrade dry-run: bump the vendor, count changed files (should be one folder).
