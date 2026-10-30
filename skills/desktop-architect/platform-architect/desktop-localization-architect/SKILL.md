---
name: desktop-localization-architect
description: Architect-level desktop localisation — string resources per platform, plural and RTL handling, locale-aware formatting and collation, translated installers and store listings, and the offline language packs enterprise deployments need. Use when a desktop app ships in more than one language.
license: MIT
compatibility: .NET resx, Xcode String Catalogs, gettext, i18next, ICU
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/platform-architect/desktop-localization-architect
  crusor-origin: original
  crusor-sources: "learn.microsoft.com/dotnet/core/extensions/localization; developer.apple.com/documentation/xcode/localization; gnu.org/software/gettext"
  crusor-triggers: "desktop localization, gettext, resx, string catalog, language pack, rtl desktop, installer language, locale formatting desktop, translate, translated installer, language selection"
  crusor-verified-on: "2026-10-30"
---

# Desktop Localisation Architect

Desktop localisation adds two problems web does not have: **installers** and
**offline machines**. Both need translated artefacts, not just translated strings.

## When to use

- Shipping to non-English markets, especially enterprise-managed fleets.
- Existing app with hardcoded strings in dialogs, menus, and error paths.
- RTL markets where layout mirroring is required.

## When NOT to use

- Single-language internal tools — but still externalise strings.

## Decision 1 — String resources

- One resource system per app: resx (.NET), String Catalogs (Apple), gettext
  (GTK/Qt), or i18next (Electron/webview).
- Keys are semantic; no concatenation; parameterised formats for dynamic content.
- Plurals through ICU rules, not `if count == 1`.
- Error messages, menu items, tooltips, and accessibility names are strings too —
  they are the ones teams forget.

## Decision 2 — Layout and script

- No fixed widths; German and Finnish expand text by 30%+.
- RTL: mirror layouts (leading/trailing), reverse navigation arrows, keep brand marks
  unmirrored.
- Fonts: ship a font or verify system coverage for CJK, Arabic, Hebrew, Devanagari.
- High-DPI and scaling combined with long strings is where clipping appears.

## Decision 3 — Formatting

- Dates, times, numbers, currency, and units via the platform's locale APIs.
- Time zones: display local, store UTC, never format manually.
- Sorting is locale-aware (collation); string comparison by bytes breaks names.
- Right-to-left text mixed with numbers/Latin requires bidi handling — test it.

## Decision 4 — Distribution

- Installers localised: NSIS/MSI/WiX support multiple languages; macOS package
  installers less so — document.
- Language selection at install and at runtime; per-user setting overrides system.
- Offline language packs for air-gapped fleets, versioned with the app.
- Store listings, screenshots, and documentation translated separately but shipped
  together.

## Decision 5 — Workflow

- TMS round-trip with screenshots; pseudo-locale builds in CI to catch truncation.
- Missing translations fall back and are reported, not left blank.
- Native-speaker review for top markets; machine translation labelled as such.
- String freeze before release; late string changes mean broken translations.

## Failure modes at scale

- English screenshots used for a German release; three clipped buttons.
- Installer in English only; enterprise deployment blocked by policy.
- Arabic UI with left-aligned text and unmirrored icons.
- Date shown MM/DD to a DD/MM market; contractual problem in finance.
- 12 languages claimed, 4 complete; missing strings show raw keys.

## Verification receipts

1. String coverage per locale with missing-key report.
2. Pseudo-locale screenshots of the top ten screens.
3. RTL walkthrough of a core flow.
4. Localised installer exercised on a clean VM.
5. Formatting tests for dates, currency, and collation.
