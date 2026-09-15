# How Copilot Is Registered, and What Crusor Should Reuse

**Reviewed:** 2026-09-11  
**Scope:** The vendored Code OSS fork under `desktop/vscode`; provider-free source review only.
**Status:** ✅ **MERGED** — PR #14 merged 2026-09-11T21:02:36Z. All 32 layers + provider-fetched output caps now on `main`.

## Short answer

GitHub Copilot is not registered in one place. It is a three-layer system:

1. **Code OSS core chat infrastructure** is imported into the workbench bundles from `workbench.common.main.ts` and `workbench.desktop.main.ts`.
2. **The built-in Copilot extension** at `extensions/copilot` activates in the extension host and contributes chat participants, language-model tools, session providers, MCP definitions, commands, settings, and proposed-API integrations through `package.json` and extension code.
3. **Product metadata** in `product.json` identifies Copilot as the default chat agent and grants its extension trusted GitHub authentication integration.

Crusor is intentionally different. Crusor is a **first-party Code OSS workbench contribution**, not an extension:

- `workbench.common.main.ts` imports `contrib/crusorai/browser/crusorAI.contribution.js` once, so Crusor's view, actions, renderer, and shared services are registered in both desktop and web workbench compositions.
- `workbench.desktop.main.ts` imports `contrib/crusorai/electron-browser/crusorAI.desktop.contribution.js` once, replacing the web-safe unavailable engine with the desktop utility-process/Python implementation.
- the optimized desktop build includes the Crusor utility-process worker entry point;
- Crusor registers views, editor panes, commands, menus, dependency-injection services, configuration, and workbench adapters directly inside Code OSS;
- there is deliberately no `extensions/crusorai` package.

This means Crusor is already registered across the correct fork entry points. It should **not** be placed into `product.json.defaultChatAgent`, because that contract expects an extension ID, extension activation, Copilot entitlement/authentication behavior, and the stock chat-participant lifecycle. Doing that would couple Crusor to GitHub Copilot rather than make Crusor more native.

## Copilot registration map

### 1. Core workbench substrate

Code OSS imports shared chat contributions from `src/vs/workbench/workbench.common.main.ts`, including:

- shared chat services and views;
- agent-host contributions;
- MCP workbench contributions;
- chat sessions and extension-point handlers;
- language-model tool registries.

Desktop-only chat and tunnel integrations are added by `workbench.desktop.main.ts`.

This substrate is useful to Crusor even when Copilot UI is hidden. Crusor can consume stable Code OSS services without becoming a Copilot participant.

### 2. Built-in Copilot extension

`extensions/copilot/package.json` declares:

- startup and language-model activation events;
- many proposed VS Code APIs;
- `languageModelTools` with compact manifest metadata and JSON schemas;
- `chatParticipants`;
- chat-session providers and customizations;
- MCP server definitions;
- commands, settings, authentication-dependent behavior, and other extension contributions.

The extension host turns those declarations into providers through the main-thread/ext-host API bridges. For Crusor, the important reusable boundary is the **registered provider/tool service**, not Copilot's private implementation or credentials.

### 3. Product metadata

`product.json.defaultChatAgent` names the GitHub Copilot extensions, documentation, entitlement endpoints, account providers, quota context keys, and commands. `trustedExtensionAuthAccess` grants the Copilot Chat extension trusted GitHub authentication access.

These entries are product-specific Copilot wiring. Crusor must not reuse them for its own provider credentials or identity.

## Crusor registration map

### Shared workbench registration

`contrib/crusorai/browser/crusorAI.contribution.ts` owns:

- `ICrusorAIWorkbenchService`, renderer, and web-safe engine registrations;
- the Auxiliary Bar view container and Crusor Agent view;
- Crusor Manager editor pane and serializer;
- command palette, menu, title-bar, keybinding, session, review, checkpoint, stop, and settings actions;
- Crusor CSS and Copilot-UI visibility policy.

Because it is imported from `workbench.common.main.ts`, this layer is available wherever the common workbench is composed.

### Desktop registration

`contrib/crusorai/electron-browser/crusorAI.desktop.contribution.ts` owns:

- the real utility-process-backed `ICrusorAIEngineService` implementation;
- machine/window settings for engine root, Python path, and automatic startup.

Because it is imported only by `workbench.desktop.main.ts`, Node/Electron functionality does not leak into web builds.

### Native capability adapter

`CrusorAIWorkbenchService` already wraps editor context, dirty buffers, diagnostics, language intelligence, search, SCM, edits, terminal, tasks, tests, and trust behind Crusor-owned interfaces. The renderer currently consumes only a subset of this adapter. The Python agent does not yet have a canonical invocation path to it.

## What Crusor should adopt from Copilot

1. **Contribution layering:** shared workbench registration, desktop-only implementation, and extension-host providers remain separate.
2. **Declarative discovery:** index tool/provider metadata before loading complete schemas or implementations.
3. **Stable service boundaries:** consume `ILanguageModelToolsService`, MCP services, language features, diagnostics, task/test services, and extension registries rather than importing extension-private code.
4. **Lazy activation:** activate an extension or MCP server only when a selected capability requires it.
5. **Context-key availability:** availability should react to trust, extension enablement, workspace, remote authority, and provider state.
6. **Namespaced identities:** preserve extension/tool/server provenance to avoid collisions.
7. **Main-thread/ext-host mediation:** extension tools execute through existing API bridges, cancellation, and permissions—not by calling extension files directly.

## What Crusor should not copy

- Copilot product identity, entitlement, quota, or trusted-auth metadata;
- GitHub-specific commands or credentials;
- the full Copilot tool catalog in every Crusor model request;
- private extension implementation classes;
- stock chat UI ownership when Crusor already has a first-party view and manager;
- automatic trust merely because a tool came from a built-in extension.

## Bridge design implied by this review

The existing stdio bridge is already duplex: Python turns run on worker threads while the bridge main loop continues accepting client frames. Therefore Phase 2 can add bounded host-tool reverse requests without a second process or socket.

Recommended flow:

1. Desktop sends a compact `host_capabilities_update` after handshake, workspace binding, trust changes, extension changes, or MCP changes.
2. Python indexes only descriptors: ID, summary, source, risk, trust requirement, availability, and schema digest.
3. When the agent selects a native capability, Python emits `host_tool_request` with session, turn, tool-call, workspace, capability ID, bounded arguments, and deadline.
4. Desktop validates workspace identity, current availability, trust, approval, argument limits, and cancellation before invoking `ICrusorAIWorkbenchService` or an existing extension/MCP service.
5. Desktop replies with `host_tool_result`, including status, compact content, truncation/continuation metadata, provenance, workspace generation, and duration.
6. Python routes the result through the same durable tool lifecycle and verification ledger as canonical tools.

The first release should expose read-only capabilities only:

- `workspace.trust`;
- `editor.activeSelection` and dirty text metadata;
- `diagnostics.markers`;
- symbols, definitions, and references;
- bounded workspace search;
- SCM state.

Mutation, execution, extension tools, and MCP invocation remain later gates.

## How Copilot's agent manager is built, and what Crusor's Manager should take from it

**Read:** 2026-09-02, same checkout (`desktop/vscode`), provider-free source reading only.
Everything below is a file:line in this repo, not a recollection.

The thing Crusor's Manager reinvents already exists as a first-party subsystem: the **Agent Sessions**
manager at `src/vs/workbench/contrib/chat/browser/agentSessions/` -- 15 modules and 7 462 lines
at its top level, 77 files and 34 331 lines with `agentHost/` and `experiments/` counted. Copilot
does not own a manager — it plugs into this one through a *session item provider*, and the manager
supplies the list, the state, the a11y and the open path.

### What is where

| concern | upstream mechanism | file |
|---|---|---|
| the list itself | workbench async **tree** view with virtual delegate, identity provider, compression delegate, sorter, keyboard-nav labels, drag-and-drop, sections and show-more/show-less rows | `agentSessionsViewer.ts:222,783,870,957,1107,1599,1629,1636,1697,1720` |
| state | a service (`IAgentSessionsService`) over a model, with per-session `setRead(true)` fired on open | `agentSessionsService.ts`, `agentSessionsOpener.ts:110` |
| live status glyph | `AgentSessionStatusIcon`: a **pixel spinner** — `variant: 'grid'` for `InProgress`, `'ring'` for `NeedsInput`, cached per template, disposed through `MutableDisposable` | `agentSessionsViewer.ts:99-140` |
| motion policy | reduced motion is handled **twice**: the primitive disables its own animation, and the viewer subscribes to `onDidChangeReducedMotion` to re-render rows that are already on screen | `agentSessionsViewer.ts:116-121`, `base/browser/ui/pixelSpinner/pixelSpinner.ts:38` |
| attention | `needs-input` crusors the glyph (2s) *and* the row's background accent (3s), suppressed while the row is selected/focused/hovered; with reduced motion the crusor becomes a static 8 % warning tint | `media/agentsessionsviewer.css:29-40,166-176,454-470` |
| opening | one entry point, `openSession(accessor, session, openOptions)`: participants get first refusal, then default = **the Chat view** (`ChatViewPaneTarget`), `sideBySide` → editor group, and if the provider cannot resolve in the panel it **forces an editor** — with `revealIfOpened: true` always | `agentSessionsOpener.ts:84-140` |
| extensibility | `sessionOpenerRegistry.registerParticipant({ handleOpenSession, handleOpenSessionResource })`; a participant throwing is logged and the default path still runs | `agentSessionsOpener.ts:27-56,64-77` |
| provider readiness | `activateChatSessionItemProvider(session.providerType)` is awaited *before* attempting to open | `agentSessionsOpener.ts:122` |
| wording and time | in-progress rows read `Working…`; a duration under 60 s renders as "now", and elapsed is clamped to a whole second floor | `agentSessionsViewer.ts:565,580-585` |

### The four things this settles for Crusor

1. **Popup or tab: neither, as the fork ships it.** There is no auxiliary-window path in upstream's
   manager. One opener takes a *target* — view pane by default, editor group when asked, editor
   forcibly when the panel cannot host it, `revealIfOpened` so a second click reveals the first
   surface instead of stacking a second one. Crusor's open question
   (`host.openManager()` building an aux window vs the `crusorai.openManager` command opening
   `CrusorAIManagerEditor`) is answered by this shape: keep the command/editor as the surface, give
   the button the same `openSession`-style call with a target option, and let the editor pane stay
   the thing `scripts/validate_crusor_ui_cdp.js` waits for. This is a recommendation with a
   citation, not a change — the decision is still the owner's and the pin is still
   `xfail(strict=True)`.
2. **A participant registry, not a fork of the manager.** `ISessionOpenerParticipant` +
   first-refusal iteration + log-and-continue is ~30 lines and is what keeps several owners of one
   surface from growing several openers. Crusor's Manager, its editor pane and any future
   Copilot-handoff should meet at one such registry rather than at duplicated `openEditor` calls.
3. **`createPixelSpinner` is Crusor's live-status primitive too.** It is already in this checkout
   (`base/browser/ui/pixelSpinner/pixelSpinner.ts`, `createPixelSpinner(parent, { ariaLabel,
   variant })`, `currentColor`-driven, self-disabling under reduced motion). Crusor's
   `crusorai-mini-spinner` CSS duplicates a worse version of it, and the Manager's session row has
   no `NeedsInput` state at all even though the model has one (`model.approval`). Two changes,
   each small: the Manager row gets grid-while-running / ring-while-awaiting plus the needs-input
   crusor, and the thread scaffold keeps Hermes' breathing square — because that is what the webview
   renders, and the thread and the list are deliberately different surfaces upstream as well.
4. **Reduced motion is a re-render, not only a media query.** Upstream subscribes to
   `onDidChangeReducedMotion` because a CSS-only answer leaves already-painted rows animating (or
   frozen) until something else repaints them. Crusor's `@media (prefers-reduced-motion: reduce)`
   block is correct for the animation itself and incomplete for the row's *structure* (the spinner
   is mounted in JS).

### What Crusor should not copy from it

The session *model* is Copilot/GitHub-shaped: `providerType`, GitHub session resources,
`vscodeChatEditor` URIs, background fetch, syncing. Crusor's sessions are local engine sessions over
the stdio bridge, and `crusorAIProtocol` already carries `session_id`. Importing the model would
couple Crusor to Copilot's entitlement and resource conventions — the exact coupling the
registration conclusion above warns against. What transfers is the *manager's* mechanics: an async
tree, one opener with a target, a participant registry, a11y-correct status primitives, and
attention states that respect the accessibility setting.

## Registration conclusion

Crusor is already correctly installed as a first-party contribution across the fork's common and
desktop entry points. The next strengthening step is not another top-level registration: it is
registering a **session type and a controller**, so the manager is fed by the workbench's own
contract instead of a private list. That step landed; see the section below. A protocol-safe
capability broker (connecting `ICrusorAIWorkbenchService` to the Python agent) stays the step after it.

## Step 1 landed: hand craft → fork craft (one store, two skins)

What changed, and why each piece is the smallest honest version of itself:

| file | role |
| --- | --- |
| `common/crusorAISessionProjection.ts` | the whole contract, pure and DOM-free: `CRUSOR_CHAT_SESSION_TYPE = 'crusorai'`, `crusorSessionUri()`, the lifecycle mapping, the elapsed/attention rules, `crusorSessionRows()`. Testable without a browser, so every branch is executed by `src/tests/test_crusor_session_registration_parity.py` |
| `common/crusorAISessionStore.ts` | `ICrusorAISessionStore`: the only writer keeps a session's `firstSeenAt` across re-renders and fires on a *signature* change, not per paint. Bounded at 64 sessions because the engine has no `session_list` call wired yet |
| `browser/crusorAISessionController.ts` | the registration: `registerChatSessionItemController('crusorai', this)`, exactly where upstream's own local controller registers (`localAgentSessionsController.ts:45`), plus a `sessionOpenerRegistry` participant so a click on a Crusor row lands on `crusorai.openManager` instead of asking a chat provider to resolve what it does not own |
| `crusorAIRendererService.ts` | one writer: `noteSession()` runs *before* the mount check (a session nobody painted is still a session the user ran), and opening the manager is what marks it read |
| `crusorAIRenderer.ts` | `sessionList(model)` renders `model.sessions` — the same rows the workbench list consumes — and the in-flight row's narration is the transcript lane's own `summarizeToolRun(...)` call, so one action cannot read differently in the two surfaces |

Two consequences worth naming rather than discovering later:

* **`chatSessionType` and the URI scheme are the same string.** `getChatSessionType()` returns
  `resource.scheme` for contributed types, so `crusorai:` *is* the type. A second scheme would be a
  second identity for one session.
* **Crusor rows now appear in the workbench's own Agents list.** Registering is what buys the
  sorting, sections, pin/archive/rename, filter submenu, find, focus and a11y commands, so this
  comes with it; the list's filter submenu is where a type is hidden. If Crusor should never appear
  there, deleting one line — the `registerChatSessionItemController` call — is the whole revert.

Deliberate gaps, each pinned so it cannot be mistaken for done:

* `IChatSessionItem.changes` stays **absent**. The fork prints "N files +A −D" from it; Crusor has a
  per-tool counter (`diffStats`) and no session-level one, and sharing the first is a refactor with
  its own test, not a field to guess at.
* Rows other than the open one are **disabled**: steering a session needs `session_resume`, which
  this build does not call.
* `setChatSessionItemRead` is **not implemented** on purpose. Implementing it moves read state into
  this in-memory map and off the host's persisted, per-resource tracking — strictly worse.
* The fork's list is *added*, not adopted: `openManagerWindow()` and the manager chrome still
  exist. Retiring them in favour of `AgentSessionsControl` inside the Agent pane is the next step
  and the popup-vs-tab decision still belongs to the owner (still `xfail(strict=True)`).

Branding is a constraint, so it is a test: no `crusorai-copilot*` class, no `'CopilotKit'` label, no
`'@copilot'`/`'GitHub Copilot'` chrome in `crusorAIRenderer.ts`, `crusorAIViewPane.ts`, the service,
the controller, the contribution or the CSS — while the rules that *hide* Copilot's chrome stay.
The optional webview tab now reads `Webview`; its setting ids (`crusorai.copilotWebview.*`) are
unchanged on purpose, because renaming a setting id silently discards the user's `settings.json`.
