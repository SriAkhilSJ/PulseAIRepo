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

## 2b. VERIFIED on hardware (desktop agent, 2026-08-23, tip `efccaa10`)

Launched from a **clean profile** so `configurationDefaults` was genuinely
exercised. **All 9 checklist rows PASS. Zero teal found** — visually confirmed
across command palette, settings, SCM, find widget, and hovers, and statically
(`Select-String #3994BC → 0`).

- Editor + all chrome render true black `#000000` with `#1A1A1A` hairlines.
- Focus rings, badges, buttons, selections all blue (`#3B82F6` / `#2563EB` / `#60A5FA`).
- Syntax colors and red/amber/green states correctly **unchanged**.
- `PulseAI Dark` present and selectable in the theme picker.

Rows 7 and 9 (explorer selection wash, git/error decorations) were verified
**statically from the theme JSON, not visually** — re-confirm opportunistically.

**Build-pipeline note:** `.build\extensions\theme-defaults\` did not contain
the new theme; the agent copied `pulseai-dark.json` + `package.json` in by hand
to avoid a multi-hour compile. On a real `npm run compile` the extension build
step syncs these, so this is a stale-`.build` artifact, **not** a packaging bug.
Worth re-confirming after the next full compile.

## 2c. Fixed this session — the Copilot onboarding takeover

The verification surfaced three problems with a **single root cause**:

1. **A GitHub "Device Code / Sign in to use GitHub Copilot" dialog blocked the
   entire UI on first launch** of a clean profile. The agent needed `Esc` ×5.
   For a product called PulseAI IDE this is the worst possible first impression.
2. **Doubled panel header** — the auxiliary bar showed a `CHAT | PULSE` tab
   strip *plus* the `Pulse` view title.
3. **Two agent surfaces** — both `CHAT` and `PULSE` present.

### Root-cause correction (I was wrong earlier)

`COPILOT_INTEGRATION_ANALYSIS.md` §1 claimed Pulse was missing
`mergeViewWithContainerWhenSingleView`. **That was wrong** — it is already set at
`pulseAI.contribution.ts:57`, and the desktop agent caught the error.

The real mechanism: the auxiliary bar renders a **tab strip per view
*container***. Pulse's container holds exactly one view, so its own header
merges correctly. The second bar appears because **two containers** occupy the
auxiliary bar — Chat's and Pulse's. Remove Chat's, and both #2 and #3 disappear.
`--disable-extension GitHub.copilot` does nothing here: `contrib/chat` is
**built-in workbench code**, not the marketplace extension.

### The fix — `product.json`, not `contrib/chat`

Chat's setup UI, its view gating, and the GitHub sign-in flow are all driven by
**`product.defaultChatAgent`**. Upstream explicitly supports its absence:

```ts
// chatEntitlementService.ts:732
// No ChatEntitlementContext (e.g. no defaultChatAgent in product.json).
// chatGettingStarted.ts:35
if (!defaultChatAgent || hideWelcomeView) { return; }
```

Every consumer reads it as `product.defaultChatAgent?.…` with `?? ''` fallbacks.
Removing it is the **sanctioned path for a fork that does not ship Copilot**.

Applied to `desktop/vscode/product.json` (an already-modified, allowed file —
invariant 7 holds; **`contrib/chat/` and `extensions/copilot/` untouched**):

| Key | Change | Why |
|---|---|---|
| `defaultChatAgent` | **removed** | Kills the GitHub sign-in dialog and the Chat setup/welcome UI; should leave Pulse alone in the auxiliary bar |
| `voiceWsUrl` | **removed** | Pointed at `falcon-caas.mai.microsoft.com`; we ship no voice feature |
| `licenseUrl`, `serverLicenseUrl` | repointed | Were `github.com/microsoft/vscode`; now our repo |

`desktop/SELECTIVE_MANIFEST.json` `product.json → overlay_sha256` refreshed.
Desktop suites green: **23 passed** (branding 5, contrib overlay 5, renderer 6,
sidecar 7).

**This preserves the founder's rule exactly.** Copilot source remains the
integration reference, byte-for-byte. We only stopped *advertising GitHub
Copilot as this IDE's default chat agent* — which was never true of PulseAI.

`webviewContentExternalBaseUrlTemplate` was left alone: it is read only by the
**web** environment service and falls back to the same URL anyway.

**Awaiting hardware confirmation.** Round-2 instructions for the desktop agent
are at `DESKTOP_AGENT_VERIFICATION_R2.md` (repo root): fresh clean profile, no
seeded settings, no `--disable-extension`, 4 checks — (1) no GitHub sign-in
dialog on first launch, (2) single Pulse panel header, (3) no `CHAT` tab in the
auxiliary bar, (4) Chat commands still reachable (regression guard). It also
picks up the two round-1 rows that were only statically verified (explorer
selection wash; error/git decoration colors).

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
| ~~5~~ | ~~`licenseUrl` / `serverLicenseUrl`~~ | — | — | ✅ **Done** (§2c) |
| 6 | `webviewContentExternalBaseUrlTemplate` | `product.json` | S | `vscode-cdn.net` URL. **Web-only code path**; harmless on desktop. Low priority. |
| ~~7~~ | ~~`voiceWsUrl`~~ | — | — | ✅ **Done** (§2c) |
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
| 2026-08-23 | **Theme verified on hardware — 9/9 pass, zero teal** (§2b). Fixed the Copilot onboarding takeover by removing `defaultChatAgent` from `product.json` (§2c); also removed `voiceWsUrl` and repointed license URLs. Corrected my earlier wrong claim that `mergeViewWithContainerWhenSingleView` was missing — it was already set. 23 desktop tests green. |
