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

### ⚠️ §2c REVERTED — removing `defaultChatAgent` bricks the workbench

**Status: the removal was WRONG and has been reverted. Do not retry it.**

Round-2 hardware verification (`e73e48b4`) found a **black screen**: the window
opens, the title stays `PulseAI IDE`, and the renderer never paints. No
`logs/window1` is created. All four checks were blocked.

The desktop agent's **control test is what cracked it**: restoring `product.json`
to `f2f1eb5e` (with `defaultChatAgent`) against the *same* `out/` made the
workbench paint; re-removing it went black again.

**Their conclusion — "the stale `out/` from 8/21 was built against the old
product shape" — is wrong, and their own control test disproves it.**
`product.json` is not compiled into `out/`. It is injected at runtime via
`globalThis._VSCODE_PRODUCT_JSON` (`platform/product/common/product.ts:37`).
Both control runs executed *identical JavaScript*; only the injected data
differed. That isolates the failure to a **runtime null-dereference**, and it
means rebuilding `out/` would not have helped.

**The actual crash site:**

```ts
// contrib/welcomeOnboarding/browser/onboardingVariationA.ts:80  (module top level)
assertDefined(product.defaultChatAgent, 'Onboarding requires a default chat agent product configuration.');
const defaultChat = product.defaultChatAgent;
```

`assertDefined` throws (`base/common/types.ts:156`). This runs at **module
evaluation**, not inside a function, and the module is pulled into the workbench
bundle by `workbench.common.main.ts:402`. A throw there aborts bundle
evaluation, so the renderer dies before it can paint anything — which is exactly
a black window with no renderer log.

**Why my earlier reasoning failed.** I quoted `chatEntitlementService.ts:732`
("No ChatEntitlementContext (e.g. no defaultChatAgent in product.json)") as
proof that absence is supported. That comment is real, but it describes *one
service's* tolerance — I generalised it to the whole workbench. The type
declaration stated the truth plainly and I did not check it:

```ts
// base/common/product.ts:272-276
readonly defaultChatAgent: IDefaultChatAgent;   // ← required, no `?`
readonly voiceWsUrl?: string;                   // ← optional, has `?`
```

**`defaultChatAgent` is a required field.** A survey of consumers found ~34
unguarded dereferences beyond the fatal one, including `defaultAccount.ts:151`
(constructor), `extensionGalleryService.ts:1980` (would break the Extensions
view) and `chatWidget.ts:1377`. Optional chaining is common but *not* universal.

**Lesson for future rebranding: grep the type declaration in
`base/common/product.ts` before removing any product key. A `?` means
removable; no `?` means a consumer will dereference it.**

#### What is retained

| Change | Status | Why |
|---|---|---|
| `defaultChatAgent` removed | **REVERTED** — restored byte-identical | Required field; module-level `assertDefined` bricks the renderer |
| `voiceWsUrl` removed | **KEPT** | Declared `voiceWsUrl?: string`; all three consumers use `\|\| ''` fallbacks |
| `licenseUrl` / `serverLicenseUrl` repointed | **KEPT** | Plain strings, no dereference risk |

`product.json` is now byte-identical to the last-known-booting revision
(`f2f1eb5e`) apart from those two safe edits.

#### The original three symptoms are still open

The GitHub Device Code dialog, the doubled panel header, and the `CHAT` tab in
the auxiliary bar are all **unfixed**. `product.defaultChatAgent` is not an
available lever. Candidate approaches, none yet validated:

1. **Drop `workbench.common.main.ts:402`** (`welcomeOnboarding.contribution.js`).
   That file is already one of the 5 permitted modified files, and Microsoft's
   "Sign in with GitHub Copilot / Google / Apple" wizard is wrong for PulseAI on
   its own merits. Removes the onboarding modal; does **not** address the CHAT
   container.
2. **Neuter rather than delete** — keep `defaultChatAgent`'s full shape so no
   consumer throws, but replace GitHub URLs/ids with PulseAI-neutral values.
   Needs care: empty provider ids may produce a broken dialog instead of none.
3. **Hide the Chat view container** via a contribution in the Pulse custom root,
   leaving `contrib/chat` untouched. Most surgical; needs research.

Option 1 is cheapest to test and independently desirable. It should be verified
**alone**, so a boot failure is unambiguous.


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

---

## §2d — The correct lever: `chat.disableAIFeatures` (settings, not surgery)

§2c reverted the `defaultChatAgent` deletion. This is the replacement, and it
changes **zero lines of TypeScript**. It is a settings default shipped through
the mechanism already proven on this hardware in round 1.

### The mechanism, traced end to end

`extensions/theme-defaults/package.json` → `contributes.configurationDefaults`:

```json
{
  "workbench.colorTheme": "PulseAI Dark",
  "chat.disableAIFeatures": true,
  "workbench.welcomePage.experimentalOnboarding": false,
  "workbench.startupEditor": "none"
}
```

`chat.disableAIFeatures` is a **first-class upstream setting**
(`platform/chat/common/chatSettings.ts:6`, declared in
`chat.shared.contribution.ts:2198`, default `false`, scope `WINDOW`). Its own
description is exactly our intent: *"Disable and hide built-in AI features
provided by GitHub Copilot, including chat and inline suggestions."*

**Symptom 1 — the GitHub sign-in modal.** It was never the marketplace
extension and never a device-code flow we triggered directly. It is upstream's
own onboarding wizard: `startupPage.ts:262` calls `onboardingService.show()`,
and `onboardingVariationA.ts` step 1 is a *"Sign In — GitHub Copilot, Google,
Apple"* hero. `startupPage.ts:249` guards it:

```ts
if (this.chatEntitlementService.sentiment.hidden) {
    return; // AI features are hidden, do not show AI-focused onboarding
}
```

`chatEntitlementService.ts:1397` sets `hidden: true` whenever
`chat.disableAIFeatures === true`. `workbench.welcomePage.experimentalOnboarding:
false` is a second, independent guard on the same modal
(`startupPage.ts:245`).

**Symptoms 2 and 3 — the doubled header and the `CHAT` tab.** The chat view's
registration is conditional (`chatParticipant.contribution.ts:71`):

```ts
when: ContextKeyExpr.and(
    ChatContextKeys.accountPolicyGateActive.negate(),
    ContextKeyExpr.or(
        ContextKeyExpr.and(
            ChatContextKeys.Setup.hidden.negate(),          // false when AI disabled
            ChatContextKeys.Setup.disabledInWorkspace.negate(),
        ),
        ChatContextKeys.panelParticipantRegistered,         // false, see below
        ChatContextKeys.extensionInvalid                    // false
    )
)
```

With AI disabled every branch is false, so the view is inactive. The container
declares `hideIfEmpty: true` (line 46), so a container with no active views
**leaves the auxiliary bar entirely**. One container remains — Pulse's — so the
per-container tab strip collapses and the "doubled header" resolves.

`panelParticipantRegistered` was the one real risk: `extensions/copilot`
(`GitHub.copilot-chat`) contributes a `chatParticipants` entry with
`isDefault: true`, `locations: ["panel"]`, `onStartupFinished`. It **cannot
activate**: its manifest declares `main: ./dist/extension` and the vendored copy
has **no `dist/` directory**. Independently,
`extensionEnablementService.ts:183` disables the built-in chat extension on any
profile where chat setup was never completed.

`maybeHideAuxiliaryBar()` (`chatSetupContributions.ts:858`) hides the whole
auxiliary bar only when chat is the *sole* container. Pulse is registered there
too, so the bar survives.

### Why this cannot repeat §2c

Every consumer reads the setting through `configurationService.getValue(...)`,
which returns the registered default when unset. There is no `assertDefined`, no
required-field dereference, and no module-level evaluation involved. It is also
**reversible by the user at runtime** — flipping the setting brings Chat back,
which is the round-3 check 4.

### Known wart

These settings live in the **theme** extension. That is semantically wrong and
is done only because `configurationDefaults` from `theme-defaults` is the exact
mechanism already verified to work on the target hardware. `product.json`
`configurationDefaults` is web-only and cannot be used here. **Follow-up: move
these into a dedicated `pulseai-defaults` built-in extension** once round 3
confirms the behaviour.

### Guard rails added

`src/tests/test_pulseai_branding.py` gains two tests: one asserting the
`configurationDefaults` contract, one asserting `defaultChatAgent` is still
present in `product.json` so §2c cannot be repeated. Suite: **32 passing**.

**Rule of thumb for this fork: prefer a setting over a source edit; prefer a
source edit over deleting a `product.json` key. Check
`src/vs/base/common/product.ts` for a `?` before touching any product key.**

---

## §2e — The build was broken by missing vendored files, not by code

Reported: `compile-client` failing with **205 TypeScript errors** — missing
Codex protocol modules, missing `logs.contribution.js`, plus implicit-`any`,
`unknown`-narrowing, generic-mismatch and missing-return errors.

**They were not 205 independent bugs.** Two directories were simply absent from
the vendored fork. Every other error cascaded from the missing types.

| Missing directory | Files | Broken imports |
|---|---:|---:|
| `src/vs/platform/agentHost/node/codex/protocol/` | 702 | 130 |
| `src/vs/workbench/contrib/logs/` | 6 | 7 |

### Method

Rather than fix errors one at a time, scan every relative import in the fork and
check whether its target exists:

```
7,793 .ts files scanned -> 138 unresolved relative imports across 3 directories
```

After restoring the two above: **1 remaining**, and that one
(`aiCustomizationManagement.css`) is absent from the pinned upstream commit too
— a pre-existing upstream bug, not our gap. Re-run that scan after any pin bump;
it is the cheapest possible check that vendoring is complete.

### Restoration

All files pulled byte-identically from
`microsoft/vscode@6c27443ce6fdf6ac798c64025d45175e2e23c4b4` (the existing pin).
Verified by recomputing each file's **git blob SHA-1** against the upstream tree:
**723/723 match, 0 mismatches.** Nothing hand-written.

*Sandbox note:* `raw.githubusercontent.com` is unreachable from the agent
sandbox (TLS EOF); `api.github.com` works. Fetch blobs via
`gh api repos/microsoft/vscode/git/blobs/<sha>` and base64-decode.

### A wrong theory, tested before it was acted on

The obvious explanation was that unanchored `.gitignore` rules (`logs/`,
`generated/`) matched at any depth inside `desktop/vscode/`, and that
`!desktop/vscode/**` could not rescue them because *git cannot re-include a file
whose parent directory is excluded*.

**That theory is false here.** `git check-ignore -v` resolves both paths to the
negation, and `git add -A .` stages all 708 files with `.gitignore` exactly as
it is. **`.gitignore` was left untouched.** The real cause is that the original
vendoring copy never brought these directories across.

Worth recording because it is the second diagnosis this week that looked
airtight and was wrong (§2c was the first). The difference is that this one was
falsified by a two-command experiment *before* anything was changed.

### Not fixed, deliberately

`build/vite` (15 files) is genuinely ignored, by the intentional
`desktop/vscode/build/*` rule at `.gitignore:81`. Its only consumer is
`componentFixtures/fixtureUtils.ts`, a test fixture outside `compile-client`.
Left alone; revisit if component-fixture tests are ever wired up.

### Scope

The Codex protocol is agent-engine territory, not interface work. This was
**vendoring repair** — restoring upstream files verbatim — undertaken because a
broken build blocks all UI verification. No agent logic was written or modified.

