# PulseAI IDE — Interface Design Plan

**Owner:** Frontend/Interface agent (design surface only)
**Status:** PLAN — approved scope pending founder sign-off
**Created:** 2026-08-23
**Scope:** `ui/` (UI Lab) + `desktop/vscode/src/vs/workbench/contrib/pulseai/browser/media/` (production CSS)
**Out of scope for this agent:** engine (`src/`), bridge protocol, benchmarks, build pipeline, Code OSS fork plumbing.

> **Read this before touching any UI file.** This document is the single source of
> truth for PulseAI's visual language. Other agents: do not re-derive design
> decisions by reading CSS — the CSS is currently *pre-system* and is being
> replaced. Read §4 (tokens) and §7 (file ownership) instead.

---

## 1. What this product actually is (derived from the code, not the pitch)

I read the engine, the bridge protocol, the workbench contribution, and both
UI Lab surfaces. The product's real identity is **not** "another Cursor."

| Evidence in the repo | What it implies |
|---|---|
| `UsageReceipt.tsx` — exact context/in/cache/out/calls/cost per turn | The product bills honesty. Usage is *evidence*, not a hidden meter. |
| Verify gate in the engine — a task cannot say "Finished" until a verification tool **ran and passed** | Verification is a first-class product state, not a log line. |
| `PermissionDock.tsx` + `safety_request`/`safety_reply` bridge frames with a `diff` payload | Approval is a designed moment with a real diff, not a toast. |
| `plan-ledger` (2/3 steps) + `SUB-AGENTS` rows + `Checkpoints` in Manager | Plan → execute → verify → checkpoint is the spine of the UI. |
| `README.md` "Honest status" block admitting embeddings are disabled | The founder's instinct is radical transparency. |

**Design thesis: _Receipts, not vibes._**
PulseAI IDE is the AI IDE that **shows its work** — every claim on screen is
backed by a number, a diff, or a passing check the user can click into.

This is a defensible position. See §2.

---

## 2. Competitor research (Aug 2026) — where the gap is

| Product | Interface posture (2026) | Documented weakness |
|---|---|---|
| **Cursor 3** (Apr 2026, $2B ARR) | Redesigned **Agents Window** — full-screen multi-agent workspace; added **Design Mode**; local↔cloud agent handoff | Criticised for "AI buttons and panels everywhere" / visual noise. Credit-pool billing is opaque to users. |
| **Windsurf** (Cognition/Devin) | Cascade + **Plan Mode**, parallel agents (Wave 13); deliberately minimal chrome | Reviewers report "minor UI issues all over"; generic design output. |
| **Zed** | Rust-native, 120fps, Agent Panel + ACP. Praised as *the* minimalist. | AI features are secondary; smaller ecosystem. |
| **Cline / Kilo / opencode** | Free, BYOK, extension-shaped | Constrained by the VS Code extension API — cannot own the chrome. |
| **Claude Code** | Terminal. Highest SWE-bench. | No GUI at all. |

**The three findings that matter for us:**

1. **Nobody owns "proof."** Every competitor shows *activity* (spinners, streaming
   text, tool logs). None make *verification + cost* the visual centerpiece.
   The 2026 UX literature is unanimous that this is the trust gap
   — Smashing Magazine's "Audit Trail" pattern, the Agentic UX "receipt"
   pattern, and NN/g's 2026 finding that users burned by premature AI features
   resist adopting new ones. PulseAI already *has* the data. It is under-designed.
2. **Cursor's own redesign validates our Manager surface.** Cursor 3 replaced
   Composer with a multi-agent window in April 2026. PulseAI's `ManagerSurface`
   is the same bet — and ours already has sub-agent trees, checkpoints, and a
   live evidence rail that Cursor does not.
3. **"Minimal" is the winning aesthetic, but minimal ≠ tiny.** Zed wins praise
   for calm density. Our current UI confuses *small* with *minimal* (see §3).

**Positioning statement to design against:**
> Cursor shows you an agent working. PulseAI shows you an agent's receipts.

---

## 3. Honest audit of the current interface

I measured `ui/src/styles.css` (562 lines) and read every component. The
information architecture is **genuinely good** — the layout, the action ledger,
the permission dock, the evidence rail are all correct product thinking. The
*visual execution* is what's holding it back. Hard numbers:

| Finding | Measurement | Impact |
|---|---|---|
| **Typography has collapsed** | 90 of 98 `font-size` declarations are ≤10px. 46 are `8px`. There is `7px` and `8.5px` text. | **Critical.** VS Code ships 13px UI text; Cursor 12–13px. 8px is below the legibility floor on a 1080p laptop. This alone makes the product read as a *wireframe*, not shippable software. |
| **No elevation hierarchy** | `--chrome` and `--surface` are both `#181818` — identical | Panels do not separate from chrome. Everything reads as one flat sheet. |
| **No radius language** | 5 `border-radius` rules in 562 lines; nearly everything is 0px | Reads as a Figma wireframe / dev tool, not a premium product. |
| **No spacing scale** | Arbitrary values: 13px, 9px, 7px, 11px, 37px, 43px | Nothing aligns to a grid; edges look "almost right", which is worse than wrong. |
| **No motion system** | 6 total `transition`/`@keyframes` in the whole file | Streaming, approval, and verification — the three emotional beats — have no choreography. |
| **Zero accessibility affordance** | `0` occurrences of `:focus-visible` | Fails the fork's own `accessibility.instructions.md`. Keyboard users are stranded. |
| **Unmaintainable selector block** | One rule lists **~40 selectors** to share `display:flex` | Any change risks unrelated surfaces. Blocks safe iteration. |
| **Token drift risk** | `ui/src/styles.css` (562 ln) and `.../media/pulseAI.css` (566 ln) duplicate the design vocabulary by hand | Lab and production will diverge silently. |
| **Brand is forgettable** | Cyan `#22d3ee` used only as a 1–2px hairline accent | No memorable identity. Screenshot does not survive a Twitter timeline. |

**Verdict:** we are not redesigning the product. We are giving a correct product
a real design system. Nothing in §1's information architecture changes.

---

## 4. The design system — "Pulse Native"

### 4.1 Guiding constraints (inherited, non-negotiable)

These come from `desktop/README.md` invariant #4 and `ui/README.md`. I am
keeping them:

- IDE chrome stays **VS Code Dark 2026 native-neutral**. No global recolor.
- Pulse semantic colors are scoped to **Pulse surfaces only**.
- **Cyan is the Pulse/working state, never the error state.**
- No token/activity graph, no node-canvas UI.
- Usage shown as **direct numeric evidence**.

### 4.2 Type scale (the single highest-impact fix)

Move to a real scale anchored at **13px base**, matching VS Code/Cursor.

| Token | Size / line-height | Use |
|---|---|---|
| `--pulse-text-display` | 20 / 26, -0.02em | Session title (Manager) |
| `--pulse-text-title` | 15 / 20, -0.01em | Panel titles, session name |
| `--pulse-text-body` | 13 / 20 | Transcript, the default for everything |
| `--pulse-text-ui` | 12 / 16 | Buttons, tabs, tree rows, composer |
| `--pulse-text-meta` | 11 / 14 | Timestamps, durations, counts |
| `--pulse-text-micro` | 10 / 12, +0.08em, 600 | Section eyebrows (`ACTIONS`, `PLAN`) **only** |
| `--pulse-code` | 12 / 20 | `ui-monospace, "Cascadia Code", Consolas` |

**Rule: nothing below 10px ships, and 10px is uppercase-eyebrow only.**

### 4.3 Spacing — strict 4pt grid

`--pulse-space-1..8` = 4, 8, 12, 16, 20, 24, 32, 40. No off-grid values.
Row heights: 28 (tree/tab), 32 (toolbar), 36 (tool row), 44 (rail button).

### 4.4 Radius & elevation

| Token | Value | Use |
|---|---|---|
| `--pulse-radius-sm` | 4px | Pills, badges, inputs |
| `--pulse-radius-md` | 8px | Tool rows, cards, dropdowns |
| `--pulse-radius-lg` | 12px | Permission dock, composer |

Three elevation planes (fixes the flat-sheet problem):
`--pulse-plane-0` chrome `#151515` · `--pulse-plane-1` surface `#1c1c1c` ·
`--pulse-plane-2` raised `#232323`, each with a `1px` top highlight at 4% white.

### 4.5 Color — TRUE BLACK (founder direction, 2026-08-23)

**Superseded the earlier native-neutral grey direction.** Founder call: full
black chrome, white for bold/primary text, grey for thinking/secondary text,
**blue** as the action accent. Cyan is retired as the Pulse accent.

**Surfaces (dark, default):**

| Token | Value | Use |
|---|---|---|
| `--bg` / `--chrome` / `--editor` | `#000000` | True black chrome and editor |
| `--surface` | `#050505` | Panels |
| `--surface-2` | `#0d0d0d` | Expanded tool bodies, raised blocks |
| `--surface-active` | `#1c1c1c` | Hover/selected |
| `--border` | `#232323` | Hairline seams (never grey slabs) |
| `--border-soft` | `#151515` | Internal dividers |

**Text — the white/grey contract:**

| Token | Value | Meaning |
|---|---|---|
| `--strong` | `#ffffff` | **Bold/emphasis** — titles, tool names, numbers, results |
| `--text` | `#e8e8e8` | Default body |
| `--muted` | `#9b9b9b` | **Thinking / reasoning / secondary prose** |
| `--faint` | `#6a6a6a` | Eyebrows, timestamps, counts |

**Blue — the single action accent:**

| Token | Value | Use |
|---|---|---|
| `--accent` | `#3b82f6` | Buttons, active state, working state, links |
| `--accent-hover` | `#5b9bff` | Button hover |
| `--accent-soft` | `#0c1a30` | Hover fills, selected rows |
| `--accent-border` | `#1d4ed8` | Accent hairlines |
| `--on-accent` | `#ffffff` | Text on blue (white, not dark) |

**States retained:** verified `#3fd68a` · approval `#f0b64f` · failed `#f2646f`
· sub-agent `#9b8cff`. **Blue = working/action, never error.** (This replaces the
old "cyan is the Pulse state" invariant — same rule, new hue.)

Light theme accent moves to `#1d4ed8`.

### 4.5b ⚠️ Production port is GATED — read before mirroring

`src/tests/test_pulseai_branding.py:79` asserts `#22d3ee` (and the other legacy
semantics) exist in
`desktop/vscode/.../media/pulseAI-tokens.css`. **The new palette is applied in
`ui/` only.** Mirroring it to production requires a coordinated change:

1. Interface agent updates `pulseAI-tokens.css`.
2. **Engine/CTO agent** updates the assertion in `test_pulseai_branding.py`.

Do not do (1) without (2) — it turns the branding suite red. This is Phase 7.

### 4.6 Motion — choreograph the three beats

| Beat | Motion |
|---|---|
| **Streaming** | Text fades in per-chunk (80ms); caret breathes 1.2s. |
| **Approval arrives** | Permission dock slides up 180ms `cubic-bezier(.2,.8,.2,1)` + one amber edge sweep. This is the only "loud" moment in the product. |
| **Verified** | Green check draws (stroke-dashoffset, 320ms); the tool row's left rail transitions cyan→green. |

Everything else: 120ms ease. Full `prefers-reduced-motion` fallback to opacity-only.

### 4.7 The signature: the Evidence Receipt

This is our screenshot moment — the thing that makes the design *attractive* and
is simultaneously our positioning.

Redesign `UsageReceipt` + the verification row into one **Receipt** component:
a monospace, ledger-styled block that closes every completed turn —

```
  VERIFIED                                    1.4s
  ─────────────────────────────────────────────────
  typecheck            passed      0 errors
  callback render      passed      destination kept
  ─────────────────────────────────────────────────
  ctx 38.4k/128k   in 12.8k   cache 9.42k   $0.031
```

Perforated top edge, tabular-nums, green state rail. It is *literally a receipt*.
No competitor has this. It is cheap to build (the data already flows through the
bridge) and it is the single most differentiating pixel in the product.

---

## 5. Execution phases

Each phase is independently shippable and independently screenshot-able.

### Phase 0 — Foundation (no visual change yet)
- Create `ui/src/styles/tokens.css` as the **single** token source.
- Generate `desktop/.../media/pulseAI-tokens.css` from it via a small script so
  lab and production **cannot drift** (fixes the §3 drift risk).
- Split the 562-line monolith into `base / chrome / agent / manager / tools`.
- Delete the ~40-selector `display:flex` block.
- **Exit:** `npm run build` clean, Playwright screenshots byte-comparable.

### Phase 1 — Typography, palette, radius, density — ✅ **DONE (2026-08-23, `ui/` only)**
Shipped in `ui/src/styles.css`:
- **Type scale applied.** Every size remapped off the 7–10px floor:
  7/7.5/8→11 · 8.5/9→12 · 9.5/10→13 · 13/14→15 · 16→18 · 17→20.
  Smallest shipped size is now **11px** (was 7px). Verified:
  `grep -o "font-size: [0-9.]*px" ui/src/styles.css | sort -u`.
- **True-black palette + blue accent** per §4.5.
- **Density pass** — row heights grown so the larger type breathes
  (tree 25→30, tab 34→38, tool row 36→42, code line 22→24, etc.).
- **Radius** — 6/8/10px applied to buttons, cards, docks, shells (was ~all 0px).
- **Blue buttons** — Approve/Send are filled blue with white text, hover +
  active-press states; ghost buttons get a blue-soft hover.
- **`:focus-visible` ring on every interactive element** (was 0 in the codebase).
- **Tabular numerals** on all usage/evidence numbers.
- **Text contract wired**: white+700 for bold/emphasis, grey for thinking prose.

**Exit evidence:** `npm run build` clean (38.9 kB CSS, 7.76 kB gzip).
**Known gap:** `ui/screenshots/*.png` are **stale** — the sandbox could not
download a Playwright browser, so they still show the old grey/cyan design.
Regenerate with `npm run test:ui` (or the shot script) on a machine with
browsers available before using them anywhere.

### Phase 2 — Agent Panel refinement
- Transcript rhythm, tool-row states with a colored state rail, streaming caret.
- Redesigned **Permission Dock**: filename + `+12 −4` + inline diff peek +
  Deny / Open native diff / **Approve** with a clear primary.
- Composer: real focus ring, mode/model/approval pills, `@` context affordance.

### Phase 3 — The Evidence Receipt (§4.7)
- New `Receipt.tsx`, retire the split `UsageReceipt` + verification row.

### Phase 4 — Manager surface
- Workspace tree density pass, sub-agent tree with connector lines,
- Live Evidence rail: Plan / Changed files / Verification / Checkpoints as one
  scannable column with the Receipt pinned at the bottom.

### Phase 5 — Motion + accessibility
- §4.6 choreography; `:focus-visible` on every interactive element;
- AA contrast audit both themes; `prefers-reduced-motion`; keyboard traversal.

### Phase 6 — States & polish
- Empty state (no workspace bound), first-run, error/offline engine, denied,
  long-running, reconnecting. These currently do not exist and are where
  startups look unfinished.

### Phase 7 — Port to production CSS
- Mirror into `contrib/pulseai/browser/media/pulseAI.css`.
- `npm run check:desktop-syntax` + refresh `ui/screenshots/`.

**Recommended order to demo:** Phase 1 → 3 → 2. Phases 1 and 3 together produce
the marketing screenshot.

---

## 6. How we will know it worked

| Metric | Now | Target |
|---|---|---|
| Smallest shipped font | 7px | **11px — done** |
| `:focus-visible` coverage | 0 | **100% of interactives — done** |
| Off-grid spacing values | ~30 | 0 |
| Token sources of truth | 2 (hand-synced) | 1 (generated) |
| Largest CSS file | 562 lines | < 200 lines per module |
| Contrast failures (AA) | unmeasured | 0, both themes |

---

## 7. File ownership — **other agents read this**

| Path | Owner | Rule |
|---|---|---|
| `ui/src/styles/**` | Interface agent | Do not hand-edit; tokens are generated. |
| `ui/src/components/**`, `ui/src/surfaces/**` | Interface agent | Presentation only. |
| `desktop/.../pulseai/browser/media/*.css` | Interface agent | Generated/mirrored from `ui/`. Never edit directly. |
| `ui/src/protocol.ts`, `ui/src/types.ts` | **Engine agent** | Interface agent consumes, never changes the contract. |
| `ui/src/runtime/**` | Shared | Interface agent may add *display* metadata only. |
| `src/**`, `benchmarks/**` | Engine/CTO agents | Interface agent never touches. |

**Invariants any agent must preserve** (from `desktop/README.md` + `ui/README.md`):
no global workbench recolor · cyan = working, never error · no activity graphs ·
usage as direct numerals · agent code never under `/extensions/`.

---

## 8. Open questions for the founder

1. **Brand temperature.** Current mark is cyan; the older `dashboard.html` used
   "red-neon EKG". Confirm cyan is final — I will not touch the mark until then.
2. **Light theme priority.** Ship at Phase 5, or defer post-launch? (Dark-first
   is normal for dev tools; Zed and Cursor both lead dark.)
3. **Receipt prominence.** Always visible after every turn, or collapsed to a
   one-line summary that expands? I recommend always-visible — it *is* the
   positioning.
4. Confirm 13px base is acceptable given you have been working at 8px.

---

## Changelog

| Date | Change |
|---|---|
| 2026-08-23 | Initial plan. Repo audit + Aug-2026 competitor research. No code changed yet. |
| 2026-08-23 | **Founder direction: true black + white/grey text + blue buttons.** §4.5 rewritten (cyan retired). Phase 1 implemented in `ui/` and marked DONE. Production port gated on a branding-test update (§4.5b). Screenshots stale — see Phase 1. |
