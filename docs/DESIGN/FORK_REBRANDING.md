# Fork Rebranding — Code OSS → PulseAI IDE

**Owner:** Interface agent · **Date:** 2026-08-23
**Scope:** everything a user *sees* that says "Code OSS" / "Visual Studio Code" / looks upstream.
**Status:** identity + icons complete (earlier sessions); **theme shipped this session**; gaps in §4.

---

## 0. Rules this work respects

From `desktop/README.md`:

- **Invariant 7:** exactly **five** upstream *source* files may be modified
  (`product.json`, `build/buildfile.ts`, `build/next/index.ts`,
  `workbench.common.main.ts`, `workbench.desktop.main.ts`).
- **Invariant 2:** Pulse *agent* code never under `/extensions/`.
- **Invariant 4:** no global workbench recolor from code; theming happens through
  the theme system.

**Founder call (2026-08-23): do not touch Copilot.** `contrib/chat/` and
`extensions/copilot/` are the reference implementation for our integrations.
See §5 — the founder is right, with one nuance.

---

## 1. Already done (verified in-repo)

| Area | State | Evidence |
|---|---|---|
| Product identity | ✅ Complete | `product.json`: `nameShort` PulseAI, `nameLong` PulseAI IDE, `applicationName` pulseai, `dataFolderName` .pulseai-ide, `urlProtocol` pulseai, `darwinBundleIdentifier` com.pulseai.ide, Win32 AppIds/mutexes all PulseAI |
| Platform icons | ✅ 8 files | `resources/{darwin/code.icns, linux/code.png, win32/code.ico, win32/code_150x150.png, win32/code_70x70.png, server/code-192.png, server/code-512.png, server/favicon.ico}`, all generated from `branding/pulseai-mark.svg`, tracked in `SELECTIVE_MANIFEST.json → brand_assets` |
| Window title | ✅ | Verified live: "PulseAI IDE Dev" (`Agent work.md`) |
| Pulse contribution | ✅ | `contrib/pulseai/` registered in the auxiliary bar |

**Identity-level rebranding is essentially finished.** What was missing is the
part users actually *feel*: the colors.

---

## 2. Shipped this session — the PulseAI Dark theme

The single highest-impact rebrand available: the IDE shipped **VS Code's
"Dark 2026"** (grey `#121314` chrome, teal `#3994BC` accents). Any screenshot
looked like VS Code.

### What was added

| File | Change |
|---|---|
| `scripts/generate_pulseai_theme.py` | **New.** Generates the theme from `2026-dark.json`. |
| `extensions/theme-defaults/themes/pulseai-dark.json` | **New.** 305 colors, 53 token rules. |
| `extensions/theme-defaults/package.json` | Registers `PulseAI Dark`; adds `configurationDefaults` → default theme. |
| `extensions/theme-defaults/package.nls.json` | Adds `pulseaiDarkThemeLabel`. |
| `branding/pulseai-dark-theme-preview.svg` | Static preview of the result. |

**Zero upstream source files touched.** All four changes are additive, inside an
existing built-in extension. Invariant 7 verified intact:

```bash
git diff --name-only b192a4c2 -- desktop/vscode/ \
  | grep -E "^desktop/vscode/(src/|build/|product.json)" | grep -v contrib/pulseai
# (no output)
```

### Why generated, not hand-written

Dark 2026 defines **298** workbench colors. Hand-authoring misses keys, and
stray upstream teal shows up in odd corners. The generator applies two
systematic remaps and inherits everything else:

1. **Surfaces → true black.** `#121314`/`#191A1B` → `#000000`;
   `#202122`→`#0A0A0A`; `#242526`→`#101010`; `#2A2B2C`→`#1A1A1A` (hairlines).
2. **Accents → Pulse blue.** The teal family (`#3994BC`, `#297AA0`, `#307E9F`,
   `#48A0C7`, `#276782`, …) → the blue ramp (`#3B82F6`, `#2563EB`, `#60A5FA`,
   `#1D4ED8`), **alpha suffixes preserved** (`#3994BCB3` → `#3B82F6B3`).
3. Syntax token colors and semantic red/green/amber inherited unchanged.

Then ~60 explicit overrides pin the brand-defining pixels (editor/activity/
side/status/title/panel = `#000000`, `button.background` = `#3B82F6`,
`focusBorder` = `#3B82F6`, `activityBarBadge` = `#3B82F6`, white/grey text ramp).

Verification: **0** leftover upstream teal or grey values.

### Re-syncing when the upstream pin moves

```bash
python3 scripts/generate_pulseai_theme.py
```

### Default-theme mechanism (and why this way)

Making it default *looked* like it required editing
`workbenchThemeService.ts` (`ThemeSettingDefaults.COLOR_THEME_DARK = 'Dark 2026'`)
— that would have been a **sixth** upstream source file, breaking invariant 7.

`product.json` `configurationDefaults` is **web-only** (read from
`environmentService.options`, not the desktop product file), so that was out too.

The working path: **extensions can contribute `configurationDefaults`**, and
several built-ins already do (`extensions/copilot/package.json`,
`extensions/css-language-features/package.json`, …). So `theme-defaults`
contributes:

```json
"configurationDefaults": { "workbench.colorTheme": "PulseAI Dark" }
```

Users can still switch themes; this only moves the default.

---

## 3. Not yet verified

The theme is **statically correct** (valid JSON, registered, 0 upstream leftovers)
but has **not been rendered in a running IDE** — the fork needs a multi-hour
build that cannot run in this sandbox.

**Founder action:** hand `DESKTOP_AGENT_THEME_VERIFICATION.md` (repo root) to the
desktop agent. It contains the sync commands, the launch paths, a 9-row pass/fail
checklist, a teal-hunt list, and the two open questions (doubled panel header;
two agent icons). Zero credits.

```bash
cd desktop/vscode
npm run compile
.build/electron/PulseAI.exe --user-data-dir .freebuff/pulseai-ud
```

Expect: black chrome, blue focus rings/badges/buttons, PulseAI Dark preselected
in the theme picker. Preview of the intent: `branding/pulseai-dark-theme-preview.svg`.

---

## 4. Remaining rebranding gaps, ranked by user visibility

| # | Gap | Where | Effort | Notes |
|---|---|---|---|---|
| 1 | **Welcome / Getting Started page** | `contrib/welcomeGettingStarted/` | M | First screen on launch. Still upstream copy/walkthroughs. Highest remaining visibility. |
| 2 | **Empty-editor watermark** | `contrib/watermark` (part of editor group) | S | Shows upstream keybinding list on an empty window. |
| 3 | **Product icon theme** | `extensions/theme-modern-icons` / `product.json` `PRODUCT_ICON_THEME` | M | The codicon set. Replacing key glyphs is a strong brand signal. |
| 4 | **About dialog** | driven by `product.json` + `LICENSE` | S | Verify it reads "PulseAI IDE" and our repo URL, not Microsoft's. |
| 5 | **`licenseUrl` / `serverLicenseUrl`** | `product.json` | S | Both still point at `github.com/microsoft/vscode/blob/main/LICENSE.txt`. |
| 6 | **`webviewContentExternalBaseUrlTemplate`** | `product.json` | S | Still a `vscode-cdn.net` URL pinned to an upstream commit hash. |
| 7 | **`voiceWsUrl`** | `product.json` | S | Points at `falcon-caas.mai.microsoft.com`. Should be removed or repointed. |
| 8 | **Light theme** | `theme-defaults` | M | No PulseAI Light yet — generator handles it when wanted. |
| 9 | **Splash / startup colors** | window background before workbench paints | S | Prevents a grey flash on cold start. |

Items 5–7 are one-line `product.json` edits (already an allowed file) and are
worth doing together — 6 and 7 are also mild privacy/telemetry surface.

---

## 5. On "don't touch Copilot" — the founder is right

**Correct, and for more reasons than stated.** Deleting or editing `contrib/chat/`
would:

1. **Destroy the reference.** It is the best-documented example of a first-party
   agent surface in the workbench — see `COPILOT_INTEGRATION_ANALYSIS.md`.
2. **Break invariant 7** and blow up the selective manifest.
3. **Create a permanent rebase wall.** 1014 files / 21 MB that would conflict on
   every upstream pin bump. This alone is disqualifying.
4. **Risk the build.** `contrib/chat/` is imported across the workbench; removing
   it is not a delete, it is a refactor.

**The one nuance:** *keeping the source* and *shipping the UI to end users* are
separate decisions. Today a built PulseAI IDE shows **two** agent icons in the
auxiliary bar — Copilot Chat and Pulse — which is confusing in a product demo.

When that matters, the fix is **runtime visibility, not deletion**: Copilot's view
is already gated on context keys (`ChatContextKeys.Setup.hidden`,
`panelParticipantRegistered` — `chatParticipant.contribution.ts:71`). With no
Copilot extension present and no auth, it should stay hidden on its own.
**Verify this in the built IDE before doing anything else.** If it still shows,
gate it via `product.json`/setting — never by editing `contrib/chat/`.

Related: Copilot claims `{ isDefault: true }` on the auxiliary bar. Pulse should
claim it in our fork (see `COPILOT_INTEGRATION_ANALYSIS.md` §6 A3).

---

## 6. Next

1. **Founder:** build + eyeball the theme (§3).
2. Then `product.json` cleanups (§4 items 5–7) — small, safe, batched.
3. Then the four integration flags (`COPILOT_INTEGRATION_ANALYSIS.md` §6 A) —
   including the doubled-header fix.
4. Then Agent UI (`PULSEAI_DESIGN_PLAN.md` Phases 2–4), rebuilt on the fork's
   design tokens per `COPILOT_INTEGRATION_ANALYSIS.md` §3.

---

## Changelog

| Date | Change |
|---|---|
| 2026-08-23 | Initial audit. Shipped PulseAI Dark theme + generator, set as default via extension `configurationDefaults`. Zero upstream source files touched. Copilot untouched per founder direction. |
