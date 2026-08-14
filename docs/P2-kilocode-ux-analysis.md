# 🎨 P2 UX Analysis — Kilo Code's agent UI, read end-to-end

**Source read:** `Kilo-Org/kilocode` @ `001fb21` — whole tree mapped (9,167 files, 41-package monorepo), then the actual source of the UX layer: 41 chat components, the permission model, the snapshot system, and the VS Code integration manifest. Every design claim below cites a real file. Nothing here is from memory.

---

## 1. Their architecture (and what it means for our fork)

```
VS Code window
└── ActivityBar icon "Kilo Code"
    └── ONE sidebar webview (React/SolidJS)   ← packages/kilo-vscode/webview-ui
        ├── ChatView.tsx .............. the whole agent UX lives here
        └── 68 commands, 30 settings  ← package.json contributes
                ↕ postMessage bridge (kilo-provider/)
        extension host → kilo-gateway / core → engines
```

**They are an EXTENSION with a webview UI — we are a FORK with a contrib.** The designs below transfer 1:1: our `contrib/pulse/browser/` layer can render these same surfaces *natively* (no webview sandbox), while their message-bridge pattern maps onto our engine-sidecar protocol. We keep the fork benefits (native diff editor, checkpoint timeline with real editor scroll) and steal their *component designs*, which are excellent.

**Do NOT copy their plumbing:** 41 packages, bun + turbo + effect-ts, 5 UI packages. That's a company-scale monorepo. Our fork = vscode + one contrib + Python sidecar. Different league, same lessons.

---

## 2. The chat view wireframe (their main screen, reconstructed)

Reconstructed from `ChatView.tsx`, `TaskHeader.tsx`, `TaskTimeline.tsx`, `ContextProgress.tsx`, `TaskUsage.tsx`, `MessageList.tsx`, `PromptInput.tsx`, `PromptRail.tsx` and the dock components:

```
┌ Kilo Code ─ Task ────────────────────────────────────────────●─ ┐
│ ▸ TaskHeader: title . cost .. [×]        [SessionTabStrip ≡]    │
│ TaskTimeline ▁▃█▅▂▇▃▅█▂▅  (SVG bars, color per part-type,      │
│                          click bar → scrolls to that message)   │
│ ┌ ContextProgress: 38.2k ▓▓▓▓▓▓▓▓░░░░ 200k ─────────────────┐  │
│ │ used ▓ (RED when ≥50%) + reserved-output ░ + available      │  │
│ └ TaskUsage: Tokens ↑12.4k  ↑ cache 8.1k  ↓1.9k   $0.0231 ──┘  │
│                                                               │
│ ╔══ MessageList (scrolls, one card per turn) ═══════════════╗ │
│ ║ 👤 VscodeUserMessage                                      ║ │
│ ║ 🤖 AssistantMessage → markdown, code blocks, mermaid      ║ │
│ ║   ├─ basic-tool cards (one per tool call: icon, status    ║ │
│ ║   │   title, expandable), tool-error-card when crashed    ║ │
│ ║   └─ tool-count-summary "± 14 tools used" rollup          ║ │
│ ╚═══════════════════════════════════════════════════════════╝ │
│                                                               │
│ ┌ DOCK ZONE (stacked above input — this is the KEY design) ─┐ │
│ │ ⚠ PermissionDock (when approval needed — §3)              │ │
│ │ ❓ QuestionDock  (agent's ask_user card)                  │ │
│ │ ↩ RevertBanner  (after a revert — §5)                     │ │
│ └───────────────────────────────────────────────────────────┘ │
│ ┌ PromptInput ───────────────────────────────────────────┐  │
│ │ type…  @ SessionMentionPicker   [model ▾] [auto⚡] [➤] │  │
│ └ PromptRail: SuggestBar suggestions ────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

**The big UX lesson:** approvals, questions, and revert-state do NOT scroll away in the message stream — they live in a **persistent dock pinned above the input**. Whatever needs the human's eyes is *always* at the bottom, one glance from the send box.

---

## 3. The permission card — their safety net's front door

From `PermissionDock.tsx` + `permission-dock-utils.ts` + `PermissionDiff.tsx` + core `permission.ts`:

```
┌ ⚠ Bash wants to run ────────────────────────────────────┐
│  $ git log --oneline -5        (homograph-punycode'd,   │
│                                  control-chars escaped) │
│  future requests like this:                             │
│   ☑ git *          ← hierarchical rule toggles          │
│   ☐ git push *        (persist to config!)              │
│ ┌ PermissionDiff (file tools): src/app.py ──────────┐   │
│ │  12 │ -old line                                   │   │
│ │  12 │ +new line                                   │   │
│ └───────────────────────────────────────────────────┘   │
│                              [ Deny ] [ Run ]           │
└───────────────────────────────────────────────────────────┘
```

The system underneath (core `permission.ts`):
- **Deny-by-default ruleset:** missing permission = `[{action:"*", resource:"*", effect:"deny"}]`
- **Wildcard patterns** (`git *`, `git log *`, file globs) with a `Wildcard` matcher
- **Reply model:** `"once" | "reject"` for THIS request + `approvedAlways[] / deniedAlways[]` **persisted** — the human teaches the agent pattern by pattern, never asked twice for `git log *`
- **Display-side armor:** punycode-normalized URLs (anti-homograph), control/bidi character escaping so a command can't repaint itself (anti Trojan-Source)
- Special flows: `external_directory` (outside workspace), skill batches (never persisted)

**Map onto PulseAI:** our SafetyGuard approves per-call and asks *every time* an overwrite appears. Their per-pattern permission memory is the upgrade — candidate **D36: permission memory** (approve `write_file` for `generated/**` once → never nagged again; deny `npm publish *` once → refused forever). ⏸️ Proposal only, not shipped — your call.

---

## 4. The 4-metrics surfaces (your doctrine, made visible)

| Your metric | Their component | What it shows |
|---|---|---|
| **Token budget** | `ContextProgress.tsx` | 3-segment bar: used (turns **red ≥50%**) / reserved-for-output / available, with tooltip breakdown |
| **Cost & calls** | `TaskUsage.tsx` | ↑input, **↑cache 8.1k shown separately**, ↓output, per-model USD to 6 decimals — *cache savings are a first-class number* |
| **Latency/activity** | `TaskTimeline.tsx` | SVG bars color-coded per part type, width ∝ duration, click-to-jump |
| **Context quality** | (their context engine is simpler than ours — our D26/D19 telemetry beats it; we show MORE) |

Plus: `ContextProgress` reads model limits live; `TaskUsage` collapses per-model groups.

---

## 5. The revert banner — their checkpoint UX vs our 👑

From `RevertBanner.tsx` + core `snapshot.ts` (git-backed; ops: `capture/files/diff/preview/restore` — same soul as our D31 shadow store):

```
┌ ↩ Reverted 3 messages ─────────────────────[ Redo ] [ Redo All ]┐
│   src/app.py        +45  −12                                      │
│   src/util.py        +2   −1        ← per-file diff stats         │
│   ⚠ workspace files were restored on disk                         │
└───────────────────────────────────────────────────────────────────┘
```

Their model: revert = move a **message boundary**, show per-file diff stats, and **Redo** (step forward) / **Redo All**. Our D31 has the stronger *store* (shared, cross-session, undo-the-undo guard, cross-project isolation — guards they lack); their **banner + per-file diff + redo** is the stronger *surface*. M4 design = our store + their banner. Best of both, no compromises.

---

## 6. Full card inventory (the 41 chat components, sorted by job)

| Job | Their cards | Adopt for PulseCode? |
|---|---|---|
| Permission | `PermissionDock`, `PermissionDiff`, `PermissionCommand` | ✅ M2 (native diff editor instead of webview diff) |
| Ask user | `QuestionDock` | ✅ M2 (our `ask_user` gets a dock card) |
| Revert/safety | `RevertBanner`, `snapshot.ts` backend | ✅ M4 (on top of D31 👑) |
| Budget/usage | `ContextProgress`, `TaskUsage` | ✅ M3 (exactly your metrics) |
| Activity | `TaskTimeline`, `TaskToolExpanded` | ✅ M4 |
| Message stream | `AssistantMessage`, `VscodeUserMessage`, `TranscriptRow/Search`, `MessageList` | ✅ M1 baseline |
| Tool cards | `basic-tool`, `tool-error-card`, `tool-status-title`, `tool-count-*` (in kilo-ui) | ✅ M1/M2 (D34 refusals + D32 stale-write refusals get `tool-error-card` styling) |
| Input | `PromptInput`, `PromptRail`, `SuggestBar`, `SessionMentionPicker` | ✅ M1 (@-mention files = cheap RAG UX) |
| Sessions | `SessionTabStrip/Tab/Menu/Switcher`, `TabDnd` (drag!) | ⏳ M5 (multi-agent sessions — pairs with D33 batches) |
| Niceties | `WelcomeEmptyState`, `ErrorDisplay`, `StartupErrorBanner`, `FeedbackDialog`, `KiloNotifications`, `AgentRequirements`, `ReviewComments`, `CloudImportDialog` | ⏳ as needed |
| Component dev method | **every card has a `.stories.tsx`** (storybook catalog) | ✅ adopt the *habit*: build each PulseCode card against mock data first |

---

## 7. Integrations inventory

- **Providers:** `packages/kilo-gateway` + `packages/llm` (multi-provider, model limits feed ContextProgress)
- **MCP:** `packages/core/src/config/mcp.ts` + a config UI route — external tool servers plug in via config
- **JetBrains port:** `packages/kilo-jetbrains` (726 files, Kotlin) — proves their core is UI-agnostic; our sidecar gives us the same portability for free
- **CLI/TUI:** `packages/tui`, `bin` — terminal client of the same core
- **Docs-as-product:** `packages/kilo-docs` (898 files), incl. 9 checkpoint screenshots — their features ship *with pictures*

---

## 8. The steal list, mapped to our milestones

| Milestone | Steal from Kilo |
|---|---|
| **M1 brain-in-body** | ChatView layout, message cards, PromptInput, basic-tool cards, tool-error-card for D32/D34 refusals |
| **M2 safety UX** | **PermissionDock design** (dock zone, per-rule toggles, deny-by-default mental model, display armor) + QuestionDock |
| **M3 telemetry** | ContextProgress (3-segment budget bar), TaskUsage (with **cache tokens as a first-class line**), timeline |
| **M4 time machine** | RevertBanner + per-file diff stats + Redo — on top of our stronger D31 store |
| **M5 packaging** | Session tabs, welcome/error states, docs-with-screenshots habit |

**And the anti-steal list:** their 41-package monorepo, bun/turbo/effect stack, per-feature config sprawl (30 settings), webview message-bridge gymnastics — we skip all of it by being a contrib with a Python sidecar.

---

*Next per your orders: this + the fork analysis (`P2-vscode-fork-analysis.md`) define the design space for M1. Say GO and M1 scaffolding begins.*
