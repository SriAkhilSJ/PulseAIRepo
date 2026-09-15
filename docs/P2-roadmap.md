# 🗺️ P2 — CrusorCode: THE FIXED ROADMAP

**Status: LOCKED. This is a fixed roadmap, not a working one.** The engine era was "measure → fix → strengthen" — that era ended at 465+ green. This roadmap is additive and scope-frozen: **scope changes require the founder's explicit sign-off, written here as an amendment. Nobody — including me — may silently widen it.**

**The 2-LINE RULE (sacred):** across the whole fork we touch upstream VS Code code in exactly TWO places: ① `product.json` branding fields, ② ONE import line in `src/vs/workbench/workbench.common.main.ts`. Everything else is NEW files inside our own directory. No "improving" VS Code internals. No opportunistic refactors. New upstream bugs we find get *reported or patched*, never rewritten.

Sources audited for this plan: full VS Code OSS tree (`microsoft/vscode` main @ `a2aaf37`, v1.133.0, Node **24.18.0**), Kilo Code UX study (`docs/P2-kilocode-ux-analysis.md`), fork analysis (`docs/P2-vscode-fork-analysis.md`), and the finished CrusorAI engine (465+ green, PR #14 merged).

---

## The locked architecture (does not change)

```
┌─ CrusorCode (fork of microsoft/vscode, branch crusor/main) ───────────┐
│ src/vs/workbench/contrib/crusor/          ← our ONLY code territory  │
│   browser/           chat view, cards, docks, panels (UI in window) │
│   common/            bridge protocol types (shared message shapes)  │
│   electron-browser/  CrusorEngineService — spawns the engine ↓       │
└── product.json (CrusorCode branding) + 1 import line ────────────┼───┘
                                                                  │ stdio, JSON-RPC v1
┌─ CrusorAI engine — PulseAIRepo, UNCHANGED Python, 437 green ◄────┘   │
│   new: src/bridge/ — thin stdio adapter (pins, suite keeps green)   │
└──────────────────────────────────────────────────────────────────────┘
```

Engine rule: **the engine is completed work — the fork never edits its logic.** The bridge is the only door. All 32 hermes parity layers are now ported and merged to `main` (PR #14, commit `bf696a61`).

---

## PHASE 0 — Foundation (no user-visible features; everything later stands on this)

| # | Task | Where | Done when |
|---|---|---|---|
| 0.1 | Fork `microsoft/vscode` → `SriAkhilSJ/CrusorCode`, branch `crusor/main` | GitHub | repo exists |
| 0.2 | Dev env: Node 24.18.0 (repo `.nvmrc`), ~15GB disk, first build | founder's PC | `code-oss` window opens from source |
| 0.3 | **Rebrand:** `product.json` → nameShort/nameLong "CrusorCode", applicationName `crusorcode`, dataFolderName `.crusorcode` | fork | window title says **CrusorCode** |
| 0.4 | **Bridge v1** in PulseAIRepo: `src/bridge/` stdio JSON-RPC (see protocol below) + pins | engine repo | bridge pins green, suite ≥ 437 |
| 0.5 | Skeleton `contrib/crusor/` registers, shows an empty "Crusor" view in the sidebar | fork | sidebar shows our empty panel |

**Bridge protocol v1 (frozen):** `hello` (versions) • `prompt` (text, workspace, thread) → `token` / `tool_call_start` / `tool_call_end` / `safety_request` / `telemetry` / `turn_done` / `checkpoint_event` • `safety_reply` (approve/deny) • `shutdown`. Versioned: `protocol: 1`. Anything not in this list is out of scope until amended.

---

## M1 — 🧠 Brain inside the body (the chat round-trip)

**You SEE:** CrusorCode window → sidebar "Crusor" → you type → your real engine answers, tool calls appear as cards.

| New files (all inside `contrib/crusor/`) | Purpose |
|---|---|
| `browser/crusor.contribution.ts` | registers view + commands (1 upstream import line) |
| `browser/crusorChatView.ts` | the chat panel (message list + input) |
| `browser/cards/*.ts` | basic tool card + error card (Kilo's `basic-tool`/`tool-error-card` designs, native) |
| `common/protocol.ts` | bridge v1 message types |
| `electron-browser/crusorEngineService.ts` | spawns `python -m src.bridge` (uv-managed), stdio, restart-on-crash, health checks |

**Exit criteria (all):** ① fresh clone builds; ② chat round-trip through the REAL engine (plan, tools, finalize); ③ tool calls render as cards with status; ④ engine crash shows error card + auto-restart; ⑤ CrusorAI suite still 437+ green incl. bridge pins; ⑥ upstream touched only by the 2-line rule.
**NOT in M1:** diffs, approvals UI, telemetry panel, checkpoints UI, themes, packaging.

## M2 — 🛡️ Safety UX (the guard becomes visible)

**You SEE:** every guarded edit shown as a native diff with ✔ Approve / ✖ Refuse; agent questions as dock cards.
- Native **diff-editor approval** for `write_file`/`edit_file` (Kilo `PermissionDock` design, but our *native* diff editor — fork privilege) wired to `safety_request`/`safety_reply`
- **QuestionDock** for `ask_user`; D32 stale-file and D34 batch refusals as readable refusal cards
- Auto-approve toggle (global) • **Founder decision point:** candidate D36 *permission memory* (per-pattern always-allow/deny) — scope it here or defer; defaults to defer.
**Exit criteria:** a guarded edit cannot land unviewed; approval latency <200ms overhead; kill-switch `CRUSORAI_FORK_UI=off` leaves engine behavior unchanged.

## M3 — 📊 Telemetry (your 4 metrics, live)

**You SEE:** budget bar + usage card on every turn.
- Context-bar (3 segments: used/reserved/free, red ≥50%) fed by engine `telemetry` messages (token_tracker + cache_audit_stats)
- Usage card: ↑input, **↑cache (own line)**, ↓output, calls, $ • activity sparkline per turn
**Exit criteria:** numbers match the engine's own logs to the token (pinned bridge contract test).

## M4 — 👑 Time machine (D31 checkpoints surfaced)

**You SEE:** checkpoint timeline per session; one click restores (with undo-the-undo); revert banner lists per-file +/− diffs; Redo steps forward (Kilo `RevertBanner` design on our stronger store).
**Exit criteria:** restore + undo-the-undo round-trip from UI; cross-project guard blocks with a readable message.

## M5 — 📦 Shipping (installers + hygiene)

**You SEE:** `CrusorCode-Setup.exe` (Windows first), update channel, welcome screen, session tabs (D33 batches as parallel branches).
- electron-builder packaging; engine bundled (standalone build, no Python install needed)
- upstream-sync ritual doc: monthly merge, conflict surface = our 2 lines only
**Exit criteria:** clean VM install → chat works end-to-end; upstream merge drill < 30 min.

---

## Locked scope-freeze list (NOT in P2 at all)

Web/browser port · JetBrains port · MCP integrations · voice · cloud sync/accounts · marketplace publishing · VS Code internals refactoring · engine behavior changes (engine is frozen at 437 green; new engine ideas go through the old board as separate D-items, never inside fork milestones).

## Risk register (honest, ranked)

1. **First build pain** (Electron; tens of minutes first time) — Phase 0.2 absorbs it before features exist.
2. **Upstream drift** (99 contribs moving) — contained by the 2-line rule + monthly sync (M5 drills it).
3. **Engine packaging for end users** (Python inside an installer) — M5 uses a standalone engine build; M1–M4 use your dev `uv` flow.
4. **SolidJS/npm stack learning cost inside contrib** — cards are built mock-first (Kilo's `.stories` habit) in isolation before wiring.

## Estimate (founder-facing, in our usual rounds)

Phase 0 ≈ 2–3 rounds · M1 ≈ 6–8 · M2 ≈ 4–5 · M3 ≈ 2–3 · M4 ≈ 3–4 · M5 ≈ 3–4. Milestones are sequential and each ships a *visible* result. Estimates can slip; the SCOPE may not move.

---

## Amendment log

### 2026-08-15 — Founder-approved product/UI amendment

The founder explicitly approved the following changes before UI implementation. Paths below are fork-root-relative: the canonical Code OSS checkout is vendored in-repo at `desktop/vscode/`, so `product.json` is `desktop/vscode/product.json`, `build/buildfile.ts` is `desktop/vscode/build/buildfile.ts`, and the contribution lives at `desktop/vscode/src/vs/workbench/contrib/crusorai/`.

1. Public product name changes from **CrusorCode** to **CrusorAI IDE**; user-facing agent remains **Crusor**.
2. The first-party workbench territory is `src/vs/workbench/contrib/crusorai/` (never `/extensions/`).
3. Two product surfaces are in scope: compact **Agent UI** and wide **Crusor Manager**.
4. A browser **UI Lab** is allowed as development/visual-verification tooling. It is not a browser product and does not change final `/contrib/` registration.
5. The TaskTimeline/token/activity graph concept is rejected. Telemetry is numeric and evidence-based.
6. Shared portable renderer + host adapters replaces a throwaway website-then-rewrite flow.
7. The shipped Python bridge has outgrown the original v1 method list; a contract-tested Protocol v2 supersedes the stale hand-maintained TypeScript mirror before fork wiring.
8. Code OSS services and installed language/platform extensions may provide editor, diagnostics, SCM, terminal, test, and language capabilities through a narrow first-party workbench host. Crusor itself remains a contribution.
9. After the founder approved continuation with the desktop-sidecar constraint disclosed, the upstream-touch budget first expanded from two files to three: `product.json`, `workbench.common.main.ts`, and `workbench.desktop.main.ts`. The desktop import registers the utility-process Python sidecar without loading Electron APIs in web builds.
10. During optimized-packaging inspection, pinned Code OSS `build/buildfile.ts` showed that string-addressed utility workers are emitted only when listed as bundle entry points. The founder explicitly approved a fourth upstream edit: `build/buildfile.ts` registers `vs/workbench/contrib/crusorai/node/crusorAIWorkerMain` in `workbenchDesktop` only (legacy gulp packaging path). The current esbuild packaging path (`build/next/index.ts`) hardcodes its own `desktopEntryPoints` and does not consume `buildfile.ts`, so a fifth approved upstream edit vendors it and lists the Crusor worker in the desktop-only array as well. Deferring this would leave development working while packaged CrusorAI IDE omitted the worker. The active upstream **source** boundary is therefore exactly five files; this supersedes the earlier four-file count.
11. The founder explicitly requested the CrusorAI logo and custom fork colors. The canonical mark now generates eight expected Code OSS platform icon replacements plus browser assets. These binary branding overlays are manifest-pinned separately and do not expand the five-file source-code boundary. Global Crusor workbench recoloring was removed (`browser/crusorAIBranding.ts`); the IDE chrome stays VS Code Dark 2026 native-neutral, and Crusor semantic color tokens are scoped to Crusor surfaces only, preserving high-contrast and user settings.

Implementation began under `ui/`. Full host/API boundaries are recorded in `docs/CRUSORAI_IDE_CONTRIB_ARCHITECTURE.md`.
