---
name: i18n-architect
description: Architect-level internationalisation — externalised message catalogues with ICU plurals, locale-aware routing and detection, date/number/currency formatting, RTL and text-expansion layout, and the extraction pipeline that keeps translations from rotting. Use when a site must serve more than one language.
license: MIT
compatibility: Framework-agnostic; ICU MessageFormat (FormatJS / i18next / framework built-ins)
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/i18n-architect
  crusor-origin: original
  crusor-sources: "unicode.org/reports/tr35; formatjs.io/docs; developer.mozilla.org/Intl"
  crusor-triggers: "i18n, internationalization, localization, translation, locale, rtl, plurals, intl"
  crusor-verified-on: "2026-10-30"
---

# Internationalisation Architect

Translation is a **content pipeline**, not a function call. Retrofitting i18n
means touching every string, every layout and every date — decide it at the
start or pay for it twice.

## When to use

- The product will ship in more than one language, ever.
- Strings are hard-coded and a second locale is now required.
- RTL, plurals, or locale-specific formatting is breaking layouts.

## When NOT to use

- Single-locale internal tools — but still externalise strings if a second
  locale is plausible.

## Decision 1 — Strings are data

- No user-visible string in code; all live in message catalogues keyed by
  meaning (`checkout.summary.itemCount`), not by English text.
- ICU MessageFormat for plurals, gender and selects — never string
  concatenation or `count === 1 ? "item" : "items"`.
- Placeholders are named and typed; translators see the full sentence.
- Keys are stable; changing a key is a migration, not a rename.

## Decision 2 — Locale in the URL

| Approach | Use when |
|---|---|
| `/en/…`, `/de/…` (subpath) | default for SEO and cacheability |
| subdomain | separate brands/markets |
| cookie-only | never for public pages — uncrawlable, uncacheable |

- The URL is the source of truth for locale; a redirect negotiates from
  `Accept-Language` once, then stays put.
- `<html lang>` and `hreflang` links follow the URL, not the cookie.
- Locale switching preserves the current route and its state.

## Decision 3 — Formatting

- Dates, numbers, currency, lists, relative time: `Intl.*`, never manual
  formatting or hard-coded separators.
- Time zones explicit; store UTC, render in the user's zone.
- Currency is an amount + code, not a float with a symbol baked in.
- Sorting and search use `Intl.Collator` where locale matters.

## Decision 4 — Layout for other languages

- Text expands 30–40% (German, Finnish): no fixed-width buttons or single-line
  labels that clip.
- RTL: use logical properties (`margin-inline-start`, `padding-inline`) — never
  `left`/`right` in shared styles.
- Mirrored icons and directional glyphs handled explicitly; numbers stay LTR.
- Fonts cover the target scripts; do not rely on fallback rendering for CJK or
  Arabic.

## Decision 5 — Pipeline

- Extraction runs in CI; a missing key fails the build, never falls back to a
  raw key in production.
- Pseudo-locale (`en-XA`) in dev to surface unexternalised strings and overflow.
- Lazy-load catalogues per locale per route; the initial bundle carries one.
- Translators get context (screenshot/description), not bare strings.

## Failure modes at scale

- „{count} items" hard-coded in a component that ships in 12 languages.
- Locale from a cookie → Google indexes one language; users share wrong URLs.
- Dates rendered with `toLocaleDateString()` and no locale argument.
- RTL shipped with `left`/`right` in 400 places.
- Translation keys drift; half the UI shows raw `checkout.title`.

## Verification receipts

1. CI: every key present in every shipped locale (no fallback in prod).
2. Pseudo-locale build reviewed for overflow and missed strings.
3. `Intl` audit: no manual date/number/currency formatting.
4. RTL pass on the primary journey; logical properties verified.
5. `hreflang` + `lang` correctness on a sample of routes.
