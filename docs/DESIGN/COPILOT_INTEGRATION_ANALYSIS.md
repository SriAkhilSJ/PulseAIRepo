# How Copilot Chat Is Integrated Into the Fork — and What Pulse Must Copy

**Author:** Interface agent · **Date:** 2026-08-23
**Method:** direct source analysis of `desktop/vscode/src/vs/workbench/contrib/chat/`
(21 MB, 1014 TS files) against `contrib/pulseai/`.
**Status:** Research complete. Actions listed in §6 are NOT yet implemented.

> **Read this before doing any Pulse UI or integration work.** It contains one
> finding (§3) that changes the design system plan and settles the "13px?"
> argument with evidence from inside our own fork.

---

## 1. Registration — Pulse is already architecturally correct

Copilot Chat registers exactly the way Pulse does. Side by side:

| | Copilot Chat | Pulse |
|---|---|---|
| Registration file | `chat/browser/chatParticipant.contribution.ts:40` | `pulseai/browser/pulseAI.contribution.ts:51` |
| API | `registerViewContainer(...)` then `registerViews(...)` | same |
| Location | `ViewContainerLocation.AuxiliaryBar` | `ViewContainerLocation.AuxiliaryBar` |
| Icon | `Codicon.chatSparkle` | `Codicon.pulse` |
| Order | `1` | `6` |
| View host | `ChatViewPane extends ViewPane` | `PulseAIViewPane extends ViewPane` |
| Lives under `/extensions/`? | **No** | **No** |

**Conclusion: the integration shape is right.** Both are first-party workbench
contributions in the secondary (auxiliary) sidebar. No change needed here.

> **⚠️ CORRECTION (2026-08-23, after hardware verification).** The claim below
> that Pulse lacks `mergeViewWithContainerWhenSingleView` is **WRONG** — it is
> already set at `pulseAI.contribution.ts:57`. The desktop agent caught this.
> The real cause of the doubled header is that the auxiliary bar renders a tab
> strip per view *container*, and two containers (Chat's and Pulse's) were
> present. Fixed by removing `defaultChatAgent` from `product.json`.
> See `FORK_REBRANDING.md` §2c. Action A1 below is void; A2/A3/A4 still stand.

### The one thing worth stealing

Copilot's container passes options Pulse does not:

```ts
ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [ChatViewContainerId,
    { mergeViewWithContainerWhenSingleView: true }]),
storageId: ChatViewContainerId,
hideIfEmpty: true,
order: 1,
}, ViewContainerLocation.AuxiliaryBar, { isDefault: true, doNotRegisterOpenCommand: true });
```

- `mergeViewWithContainerWhenSingleView: true` — removes the redundant inner
  view header when the container holds one view. **Pulse currently renders a
  doubled header.** This is a one-line visual win.
- `isDefault: true` — makes it *the* auxiliary bar default. Copilot claims this.
  Pulse cannot also be default; decide whether Pulse displaces Copilot in our
  fork (we ship no Copilot, so **we should claim it**).
- `openCommandActionDescriptor` with a keybinding — Copilot binds
  `Ctrl/Cmd+Alt+I`. **Pulse has no keybinding to open the panel.** It needs one.

### The extension boundary (important for our story)

Copilot's *UI* is 100% first-party (`contrib/chat/`). Only the **provider**
arrives via the `chatParticipants` extension point
(`chatParticipant.contribution.ts:86`). Microsoft owns the pixels; the extension
supplies the model.

Pulse uses the same split, with the extension host replaced by a Python sidecar:

```
Copilot:  contrib/chat/  →  chatParticipants extension point  →  Copilot ext
Pulse:    contrib/pulseai/ →  IPulseAIEngineService  →  utility process  →  python -m src.bridge
```

**This is a feature, not a shortcut.** We get Copilot's UI ownership model
without the extension host in the loop.

---

## 2. Scale reality check

| | Copilot Chat | Pulse |
|---|---|---|
| TS files | 1014 | 12 |
| Total size | 21 MB | ~0.1 MB |
| CSS files | 30 | 2 |
| Main stylesheet | `widget/media/chat.css` — **4933 lines** | `media/pulseAI.css` — 566 lines |

We are not going to out-build 1014 files. We win on **focus and proof**, not
surface area. (See the design plan's "receipts, not vibes" thesis.)

---

## 3. ⚠️ THE FINDING — the fork already ships a design system, and Pulse ignores it

`chat.css` almost never hardcodes a pixel value. It consumes **workbench design
tokens**:

```css
font-size: var(--vscode-chat-font-size-body-m);
border-radius: var(--vscode-cornerRadius-medium);
```

These are registered in **`src/vs/platform/theme/common/sizes/baseSizes.ts`**
and exposed as CSS variables by `sizeUtils.ts:45`
(`fontSize.body1` → `--vscode-fontSize-body1`).

### The actual, shipped scale in our fork

**Font sizes**

| Token | CSS variable | Value |
|---|---|---|
| `fontSize.heading1` | `--vscode-fontSize-heading1` | **26px** |
| `fontSize.heading2` | `--vscode-fontSize-heading2` | **18px** |
| `fontSize.heading3` | `--vscode-fontSize-heading3` | **13px** |
| `fontSize.body1` | `--vscode-fontSize-body1` | **13px** ← *"Primary body font size"* |
| `fontSize.body2` | `--vscode-fontSize-body2` | **11px** |
| `fontSize.label1` | `--vscode-fontSize-label1` | **12px** (section title, tabs) |
| `fontSize.label2` | `--vscode-fontSize-label2` | **11px** (metadata) |
| `fontSize.label3` | `--vscode-fontSize-label3` | **10px** (badge) |

`bodyFontSize` is likewise registered at **13px**, described verbatim as
*"Base font size. This size is used if not overridden by a component."*

**Font weights:** `regular` 400 · `semiBold` **600**.
Note the comment in the source: *"'Strong' variants are NOT separate size
tokens: reuse the matching size token paired with `fontWeight.semiBold` (600)."*
→ **Our polish layer uses `font-weight: 700`. The fork's system says 600.**

**Corner radii:** xSmall 2 · small 4 · **medium 6** · large 8 · xLarge 12 · circle 9999
**Stroke:** 1px · **Codicon:** 16px, compact 12px
**Spacing ramp:** 0, 2, 4, 6, 8, 10, 12, 16, 20, 24, 28, 32, 36, 40 …

### This settles the 13px question

The founder asked *"what 13px??"*. The answer is not my opinion — **13px is the
base body size defined inside our own fork**, the same token Copilot Chat
renders with. Shipping Pulse at 8px meant Pulse text was ~40% the size of the
editor it lives next to.

### How badly Pulse diverges today

Measured on `contrib/pulseai/browser/media/pulseAI.css`:

| Metric | Count |
|---|---|
| Hardcoded `font-size: Npx` | **34** |
| `--vscode-fontSize-*` / chat font tokens used | **0** |
| `--vscode-cornerRadius-*` used | **0** |
| `--vscode-spacing-*` used | **0** |
| Hardcoded `border-radius` | 3 |

Its most common size is **10px (15 occurrences)**, with one at 8px.

**Consequence:** Pulse ignores user font-size settings, editor zoom, and theme
size overrides. It will look wrong on every machine that isn't the founder's.

### Correction to the design plan

`docs/DESIGN/PULSEAI_DESIGN_PLAN.md` §4.2–4.4 invented a bespoke type/spacing/
radius scale. **That was wrong.** Pulse should *consume the workbench tokens*,
not parallel them. The plan's §4.2–4.4 are superseded by this section. The
custom **color** work (§4.5, true black / white / grey / blue) stands — colors
are genuinely ours; sizes are not.

---

## 4. UI patterns worth copying from `chat.css`

| Pattern | Where | Why Pulse wants it |
|---|---|---|
| Semantic color tokens (`--vscode-chat-linesAddedForeground`, `--vscode-chat-linesRemovedForeground`) | `chat.css` | Our `+12 −4` diff stats should use these, not custom green/red. |
| `--vscode-chat-requestBubbleBackground` / `requestBorder` | `chat.css` | A real registered treatment for the user turn; ours is a hand-rolled rail. |
| `--vscode-chat-thinkingShimmer` | `chat.css` | A *registered token* for reasoning-in-progress — directly serves our grey "thinking" text. |
| `--vscode-chat-avatarBackground/Foreground` | `chat.css` | Consistent agent avatar treatment. |
| CSS imported by the widget (`import './media/chat.css'` in `chatWidget.ts:6`) | | Same pattern Pulse uses — correct already. |
| Button tokens (`--vscode-button-background`, `-hoverBackground`, `-secondary*`) | `chat.css` | **Our blue buttons should map onto these** so they respect the user's theme. |

---

## 5. Feature surfaces Copilot has that Pulse has not designed

From the `contrib/chat/browser/` directory listing — each is a shipped surface:

`chatEditing` (edit review overlay) · `chatSessions` · `chatStatus` (status bar)
· `chatSetup` (onboarding) · `chatQuotaNotification` · `chatDebug` ·
`agentSessions` · `planReviewFeedback` · `promptTimeline` · `attachments` ·
`speechToText` / `voiceClient` · `aiCustomization` · `chatOutline` ·
`chatManagement` (model picker) · `chatSlashCommands` · `chatDragAndDrop`

**Highest-value gaps for Pulse, in order:**
1. **`chatSetup` — onboarding.** Pulse has no first-run experience at all.
2. **`chatStatus` — status bar integration.** Cheap, always-visible, and a
   natural home for the Pulse receipt (cost/context).
3. **`chatEditing` — the edit review overlay.** Our `29 Files → Review` equivalent.
4. **`attachments` / drag-and-drop context.** Table stakes in 2026.
5. **`promptTimeline` / checkpoints.** We already have checkpoint data in Manager.

---

## 6. Actions (proposed — not yet done)

**A. Integration (small, high value)**
- A1 Add `mergeViewWithContainerWhenSingleView: true` — removes the doubled header.
- A2 Add `openCommandActionDescriptor` + keybinding to open Pulse.
- A3 Claim `{ isDefault: true }` for the auxiliary bar (we ship no Copilot).
- A4 Add `hideIfEmpty` / `storageId` parity.

**B. Design system (the real work)**
- B1 Rewrite `pulseAI.css` to consume `--vscode-fontSize-*`,
  `--vscode-cornerRadius-*`, `--vscode-spacing-*` — remove all 34 hardcoded sizes.
- B2 Change emphasis weight 700 → `--vscode-fontWeight-semiBold` (600).
- B3 Map Pulse blue onto `--vscode-button-*` so buttons theme correctly.
- B4 Use `--vscode-chat-linesAdded/RemovedForeground` for diff stats.
- B5 Mirror the same token discipline back into `ui/src/styles.css` so the lab
  predicts production. (The lab can `@import` a shim defining the `--vscode-*`
  variables at their real values.)

**C. Gated**
- C1 Production palette port is still blocked by
  `src/tests/test_pulseai_branding.py:79` (pins `#22d3ee`). Needs a coordinated
  engine-agent change. See design plan §4.5b.

---

## 7. Bottom line for the founder

1. **Your integration is already built the right way.** Pulse registers exactly
   like Copilot Chat — first-party contribution, auxiliary bar, own ViewPane, no
   extension host. Four small option flags are missing; that's it.
2. **Your fork already contains a professional design system, and Pulse isn't
   using a single token of it.** 34 hardcoded font sizes, zero design tokens.
   Fixing that is the highest-leverage UI work available — it makes Pulse look
   native *and* respect every user's zoom/theme settings for free.
3. **13px is not my preference — it is `fontSize.body1` in your own repo,** the
   token Copilot Chat renders its messages with.
