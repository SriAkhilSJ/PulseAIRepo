---
name: mobile-localization-architect
description: Architect-level localisation and internationalisation — string externalisation and pluralisation, RTL layout mirroring, date/number/currency formatting, translation workflow and pseudo-locales, and the store metadata and asset rules that decide whether a market can install the app. Use when the app ships in more than one language.
license: MIT
compatibility: String Catalogs, Android resources, ICU/CLDR, Crowdin/Lokalise
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/devices-architect/mobile-localization-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/xcode/localizing-and-varying-text-with-a-string-catalog; developer.android.com/guide/topics/resources/localization; unicode-org.github.io/icu"
  crusor-triggers: "localization, i18n, rtl, pluralization, string catalog, translation, locale, currency formatting, pseudo locale, l10n"
  crusor-verified-on: "2026-10-30"
---

# Localisation Architect

Localisation is **a data-model problem before it is a translation problem**. Strings
built by concatenation cannot be translated; layouts built for one script break in
another.

## When to use

- Shipping in more than one language or region.
- Right-to-left markets (Arabic, Hebrew) or long-text languages (German, Finnish).
- Dates, currencies, or units displayed to users.

## When NOT to use

- Single-language, single-market product with no near-term expansion — but still
  externalise strings; retrofitting is expensive.

## Decision 1 — Strings

- Externalise everything, including error messages and accessibility labels.
- No concatenation: use parameterised formats ("{count} items in {cart}"), never
  `"You have " + n + " items"`.
- Pluralisation through the platform's plural rules (ICU), not `if n > 1`.
- Gendered/formal variants: decide whether the target languages need them before
  writing keys.
- Keys are semantic (`checkout.button.pay`), not English text as the key.

## Decision 2 — Layout

- No fixed widths around text; localised strings are 30–40% longer.
- RTL: enable mirroring and use leading/trailing constraints, not left/right.
- Icons that imply direction (arrows, progress) must flip; brand logos must not.
- Test with a pseudo-locale (accented, expanded) on every screen; it finds truncation
  before translation does.

## Decision 3 — Formats

- Dates, times, numbers, currencies, and units via the locale-aware formatter — never
  manual formatting.
- Time zones: display in the user's zone unless the domain says otherwise.
- Address and name formats vary; do not assume first/last.
- Sorting and searching must be locale-aware (collation), not byte order.

## Decision 4 — Workflow

- Source language canonical; translation happens in a TMS with screenshots and context.
- Screenshots per string reduce bad translations more than glossaries alone.
- Translations are reviewed by a native speaker for the top markets, machine-only for
  the long tail — and labelled as such.
- Missing translations fall back gracefully and are reported, not silently blank.

## Decision 5 — Store and assets

- Store listing metadata, screenshots, and keywords are localised separately from the
  app.
- Text in images cannot be translated — design assets with minimal baked text.
- App name and icon may need per-market variants; the store allows localised names.
- Region-specific legal and pricing content follows store rules.

## Failure modes at scale

- Concatenated strings producing "1 items" in English and worse elsewhere.
- German text clipped in buttons designed for English.
- RTL layout with left-aligned text and mirrored brand logo.
- Dates formatted as MM/DD in a DD/MM market; a compliance issue in some industries.
- 14 languages declared, 9 with missing keys falling back to English.

## Verification receipts

1. String inventory: externalised percentage, keys, and plural coverage.
2. Pseudo-locale screenshots of the top ten screens.
3. RTL walkthrough of a core flow.
4. Locale-formatting test for dates, currency, and numbers.
5. Missing-translation report for each shipped locale.
