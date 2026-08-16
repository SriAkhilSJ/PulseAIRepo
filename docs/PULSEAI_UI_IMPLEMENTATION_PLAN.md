# PulseAI IDE UI — Execution Plan

**Date:** 2026-08-15
**Status:** Active
**Founder constraints:** `/contrib/pulseai/`, no Pulse extension, no activity/token graph, no card-heavy or over-spaced dashboard, canonical vendored fork only under `desktop/vscode/`.

## Capacity rules

1. Never clone full Kilo or VS Code working trees into the sandbox (the vendored `desktop/vscode/` checkout is the single committed Code OSS tree).
2. Kilo stays a blobless/no-checkout reference clone. Read individual blobs with `git show`.
3. `desktop/` tracks only fork metadata (`README.md`, `SELECTIVE_MANIFEST.json`, `UPSTREAM_PIN`, `.nvmrc`) plus the vendored `vscode/` tree; all Pulse overlay edits are committed in place inside `desktop/vscode/`.
4. Never create `desktop/vscode/node_modules`, build output, or a second Electron checkout during UI design; build artifacts inside the fork are protected by its nested `.gitignore`.
5. Check disk use after each major phase; the vendored fork must stay under control before the real build milestone.
6. Browser dependencies remain under ignored `ui/node_modules`; generated UI output remains ignored.

## Tasks

### T1 — Read the relevant Kilo UX implementation — COMPLETE

Read current Kilo Code `c8271ad6` directly from its Git objects:

- `ChatView`, `TaskHeader`, `MessageList`, `AssistantMessage`;
- `PermissionDock`, `QuestionDock`, `RevertBanner`, `PromptInput`;
- Agent Manager layout, sidebar, tabs, split detail, diff and terminal hosts;
- flat tool trigger/card styles and tool error behavior.

Extracted lessons:

- one vertical shell: header → transcript → dock → prompt;
- human-blocking controls remain adjacent to the prompt;
- messages and tool receipts form a continuous transcript;
- manager uses sidebar + tabbed detail + optional split inspector;
- streaming updates existing rows instead of generating a new visual card per event;
- the activity timeline is separable and will not be adopted.

### T2 — SVG wireframes — COMPLETE

Produce founder-reviewable, implementation-neutral SVGs:

1. Compact Agent UI at 420×900.
2. Pulse Manager at 1440×900.
3. In-editor integration at 1440×900 if needed after the first two are accepted.

Wireframe rules:

- flat rows and thin separators;
- no floating card collection;
- no excessive rounded containers;
- dense IDE spacing;
- SVG status, tool, file, branch, approval and hierarchy marks;
- no graph, chart, sparkline, activity timeline, or node canvas.

### T3 — Replace rejected browser implementation — COMPLETE

The browser UI now follows the approved wireframe direction:

- card-heavy Agent UI replaced with a flat transcript and inline action ledger;
- dashboard-like Manager sections replaced with dense sidebar/detail/evidence panes;
- deterministic streaming and Playwright interaction tests retained;
- wide Agent UI, compact 420px Agent UI, and wide Manager screenshots captured;
- shared event state and host contract retained;
- native File/Edit/Selection/View/Go/Run/Terminal/Help menu bar added;
- Pulse menu added for sessions, Manager, changes, checkpoints, stop, and settings;
- compact mode, model, and approval-policy dropdowns added to the Agent UI;
- Kilo's tool pipeline was reviewed end-to-end and flat tool disclosures now expand Read/Edit/Verify details in place;
- queued disclosures are locked while approval/running/error tools can default open;
- all 34 current Pulse runtime tool names are catalogued by renderer family with an AST drift test;
- Terminal is implemented as a default-open disclosure with command, exit code, output, copy, and native-terminal actions;
- a UI Lab-only Tool Gallery exposes all 34 names and 13 family-specific disclosure bodies for browser review.

### T4 — Canonical Code OSS fork — FOUNDATION COMPLETE

The full Code OSS checkout is vendored in-repo at `desktop/vscode/` and pinned to upstream commit `6c27443ce6fdf6ac798c64025d45175e2e23c4b4`. The Pulse overlay is applied **in place** inside the fork and committed along with it: `desktop/vscode/product.json`, `build/buildfile.ts`, the branded platform resources under `desktop/vscode/resources/`, and the first-party contribution under `desktop/vscode/src/vs/workbench/contrib/pulseai/`.

No files are copied piecemeal into `desktop/`; the fork root itself carries only metadata (`README.md`, `SELECTIVE_MANIFEST.json`, `UPSTREAM_PIN`, `.nvmrc`). The manifest pins every overlay receipt and the upstream commit; `desktop/vscode/.gitignore` protects build outputs.

Branding now has one canonical pulse-and-agent-node SVG plus reproducible Windows ICO/tile, macOS ICNS, Linux PNG, server icon, and browser favicon outputs. Eight expected Code OSS resource replacements are receipt-pinned separately from the four-file source boundary. The IDE chrome is VS Code Dark 2026 native-neutral: the earlier global cyan/navy workbench color defaults were removed, and Pulse contributes only semantic color tokens (cyan running/focus/primary, violet delegation, green verified, amber approval/warning, red failure), preserving user overrides and high-contrast behavior.

### T5 — PulseAI Bridge Protocol v2 — CONTRACT FOUNDATION COMPLETE

The v2 JSON manifest now generates TypeScript frame-name/version constants, the handwritten payload union is parity-pinned against every current Python method/event, approvals are pinned to `tool_id`, and the fork overlay metadata has a hard size gate. Focused protocol/bridge result: **13 passed**.

The Python sidecar now advertises v2, negotiates v1 for legacy clients, and returns the negotiated version in its hello frame. Remaining: reconnect replay integration through the workbench service.

Contract coverage:

- session and turn identity;
- prompt/token/tool streams;
- approvals keyed by `tool_id`;
- cancel, steer and queue;
- verification and checkpoints;
- sub-agent lifecycle;
- reconnect/event replay;
- unknown-event compatibility.

### T6 — Workbench host — NATIVE RENDERER FOUNDATION COMPLETE

The pinned current Code OSS registration patterns were read from Terminal and Getting Started without copying their trees (the vendored fork is the tree). The overlay inside the fork now contains the native Agent `ViewPane`, view container registration, Pulse top-level menu, command palette actions, engine service contract, semantic tokens, and the one upstream workbench import. Static overlay/tool/protocol/bridge verification: **20 passed**.

Pulse Manager is now registered as a pinned, serializable `EditorInput` + `EditorPane` in the main editor area. The Pulse menu opens that editor tab, while the Activity Bar opens the compact Agent view. All eight first-party contribution TypeScript files pass an automated decorator-aware syntax check.

A 29-capability Code OSS audit and stable `IPulseAIWorkbenchService` sensor/actuator contract now cover dirty editor text, language providers, diagnostics, search, SCM, native bulk edits, terminal, tests, trust, extensions, debug, notebooks, MCP/editor tools and remote workspaces.

The first real adapter now reads the active/diff editor model, selected and visible unsaved text, marker diagnostics, extension-provided document symbols/definitions/references, opens resources/native diffs, listens for trust/marker changes, and applies version-pinned multi-file edits through `IBulkEditService` with native preview and undo confirmation.

Native workspace search, SCM snapshots, test discovery/runs/results, task discovery/runs, and terminal command execution are wired with trust/approval gates. Terminal execution now listens to shell-integration command completion, captures bounded line/output evidence, reports exit state and duration, applies bounded timeouts, and can opt into `SIGINT` on timeout.

The desktop-only sidecar chain is now implemented: existing Code OSS utility-process worker → Node frame/process service → `python -m src.bridge` → negotiated Protocol v2. Common/web code never imports Electron or `child_process`; the desktop workbench import registers only the desktop service. Optimized-packaging inspection then proved that string-addressed utility workers require their own bundle entry. The founder approved `build/buildfile.ts` as the fourth upstream edit, and it now emits `pulseAIWorkerMain` in `workbenchDesktop` only.

The compact Agent `ViewPane` and Pulse Manager `EditorPane` now mount the same framework-neutral `pulseAIRenderer.ts` through one singleton `PulseAIRendererService`. That service owns the shared Protocol v2 event model, session/prompt routing, streaming text, tool lifecycle, approvals, plans, verification, telemetry, engine status, and workbench reveal intents. The native catalog covers the same 34 tool names as the browser catalog and selects family-specific disclosures. Terminal disclosures include command, bounded output, state/exit evidence, duration, copy, and reveal actions. Common/web construction is safe through a no-process fallback engine descriptor; the later desktop descriptor replaces it during service collection initialization.

Current focused branding/renderer/sidecar/capability/overlay/catalog/Protocol/bridge verification: **46 passed**. All **25** first-party contribution TypeScript files inside the fork—including the three upstream entrypoints—pass the decorator-aware syntax check. The browser production build and **7/7** Chromium tests pass, with zero npm audit findings. Optimized package inclusion is structurally pinned through `buildfile.ts`; a complete pinned Code OSS type-check, build, and launch have not yet run.

Engine retry now uses at most three exponential-backoff attempts while a Pulse surface is mounted. A successful restart resumes the active session, requests replay, and de-duplicates bounded `event_id` history before applying replayed frames. Startup failures release partially created workers and transition out of `starting`. Cancel is de-duplicated in the renderer, displays a `Stopping…` state, consumes the bridge's `cancel_requested` receipt, and maps `turn_done.completed = false` to an explicit cancelled-run receipt. Safety requests carrying `{ path, old_text, new_text }` now materialize bounded read-only `pulseai-diff:` models and open the native Code OSS diff editor; URI-backed receipts still use the direct path. Event-bus streaming/tool/approval fields and durable replay rows are normalized into Protocol v2 names before reaching the renderer. Still required before T6 completes: non-shell-integration terminal fallback evidence, richer test/task output correlation, and validation in a complete pinned Code OSS tree.

Implementation scope:

- Agent View registration;
- Pulse Manager editor registration;
- engine process service;
- native diff/open/reveal/terminal/SCM/diagnostic actions;
- UI renderer host and message boundary;
- shutdown/restart/replay behavior.

### T7 — Real-engine vertical slice

Exit criteria:

1. PulseAI IDE starts the Python sidecar.
2. Prompt streams into the compact UI.
3. Tool rows update in place.
4. Approval opens a native diff and resolves by `tool_id`.
5. Verification evidence appears.
6. Engine restart restores the session without duplicate events.
