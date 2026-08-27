# How Copilot Is Registered, and What Pulse Should Reuse

**Reviewed:** 2026-08-26  
**Scope:** The vendored Code OSS fork under `desktop/vscode`; provider-free source review only.

## Short answer

GitHub Copilot is not registered in one place. It is a three-layer system:

1. **Code OSS core chat infrastructure** is imported into the workbench bundles from `workbench.common.main.ts` and `workbench.desktop.main.ts`.
2. **The built-in Copilot extension** at `extensions/copilot` activates in the extension host and contributes chat participants, language-model tools, session providers, MCP definitions, commands, settings, and proposed-API integrations through `package.json` and extension code.
3. **Product metadata** in `product.json` identifies Copilot as the default chat agent and grants its extension trusted GitHub authentication integration.

Pulse is intentionally different. Pulse is a **first-party Code OSS workbench contribution**, not an extension:

- `workbench.common.main.ts` imports `contrib/pulseai/browser/pulseAI.contribution.js` once, so Pulse's view, actions, renderer, and shared services are registered in both desktop and web workbench compositions.
- `workbench.desktop.main.ts` imports `contrib/pulseai/electron-browser/pulseAI.desktop.contribution.js` once, replacing the web-safe unavailable engine with the desktop utility-process/Python implementation.
- the optimized desktop build includes the Pulse utility-process worker entry point;
- Pulse registers views, editor panes, commands, menus, dependency-injection services, configuration, and workbench adapters directly inside Code OSS;
- there is deliberately no `extensions/pulseai` package.

This means Pulse is already registered across the correct fork entry points. It should **not** be placed into `product.json.defaultChatAgent`, because that contract expects an extension ID, extension activation, Copilot entitlement/authentication behavior, and the stock chat-participant lifecycle. Doing that would couple Pulse to GitHub Copilot rather than make Pulse more native.

## Copilot registration map

### 1. Core workbench substrate

Code OSS imports shared chat contributions from `src/vs/workbench/workbench.common.main.ts`, including:

- shared chat services and views;
- agent-host contributions;
- MCP workbench contributions;
- chat sessions and extension-point handlers;
- language-model tool registries.

Desktop-only chat and tunnel integrations are added by `workbench.desktop.main.ts`.

This substrate is useful to Pulse even when Copilot UI is hidden. Pulse can consume stable Code OSS services without becoming a Copilot participant.

### 2. Built-in Copilot extension

`extensions/copilot/package.json` declares:

- startup and language-model activation events;
- many proposed VS Code APIs;
- `languageModelTools` with compact manifest metadata and JSON schemas;
- `chatParticipants`;
- chat-session providers and customizations;
- MCP server definitions;
- commands, settings, authentication-dependent behavior, and other extension contributions.

The extension host turns those declarations into providers through the main-thread/ext-host API bridges. For Pulse, the important reusable boundary is the **registered provider/tool service**, not Copilot's private implementation or credentials.

### 3. Product metadata

`product.json.defaultChatAgent` names the GitHub Copilot extensions, documentation, entitlement endpoints, account providers, quota context keys, and commands. `trustedExtensionAuthAccess` grants the Copilot Chat extension trusted GitHub authentication access.

These entries are product-specific Copilot wiring. Pulse must not reuse them for its own provider credentials or identity.

## Pulse registration map

### Shared workbench registration

`contrib/pulseai/browser/pulseAI.contribution.ts` owns:

- `IPulseAIWorkbenchService`, renderer, and web-safe engine registrations;
- the Auxiliary Bar view container and Pulse Agent view;
- Pulse Manager editor pane and serializer;
- command palette, menu, title-bar, keybinding, session, review, checkpoint, stop, and settings actions;
- Pulse CSS and Copilot-UI visibility policy.

Because it is imported from `workbench.common.main.ts`, this layer is available wherever the common workbench is composed.

### Desktop registration

`contrib/pulseai/electron-browser/pulseAI.desktop.contribution.ts` owns:

- the real utility-process-backed `IPulseAIEngineService` implementation;
- machine/window settings for engine root, Python path, and automatic startup.

Because it is imported only by `workbench.desktop.main.ts`, Node/Electron functionality does not leak into web builds.

### Native capability adapter

`PulseAIWorkbenchService` already wraps editor context, dirty buffers, diagnostics, language intelligence, search, SCM, edits, terminal, tasks, tests, and trust behind Pulse-owned interfaces. The renderer currently consumes only a subset of this adapter. The Python agent does not yet have a canonical invocation path to it.

## What Pulse should adopt from Copilot

1. **Contribution layering:** shared workbench registration, desktop-only implementation, and extension-host providers remain separate.
2. **Declarative discovery:** index tool/provider metadata before loading complete schemas or implementations.
3. **Stable service boundaries:** consume `ILanguageModelToolsService`, MCP services, language features, diagnostics, task/test services, and extension registries rather than importing extension-private code.
4. **Lazy activation:** activate an extension or MCP server only when a selected capability requires it.
5. **Context-key availability:** availability should react to trust, extension enablement, workspace, remote authority, and provider state.
6. **Namespaced identities:** preserve extension/tool/server provenance to avoid collisions.
7. **Main-thread/ext-host mediation:** extension tools execute through existing API bridges, cancellation, and permissions—not by calling extension files directly.

## What Pulse should not copy

- Copilot product identity, entitlement, quota, or trusted-auth metadata;
- GitHub-specific commands or credentials;
- the full Copilot tool catalog in every Pulse model request;
- private extension implementation classes;
- stock chat UI ownership when Pulse already has a first-party view and manager;
- automatic trust merely because a tool came from a built-in extension.

## Bridge design implied by this review

The existing stdio bridge is already duplex: Python turns run on worker threads while the bridge main loop continues accepting client frames. Therefore Phase 2 can add bounded host-tool reverse requests without a second process or socket.

Recommended flow:

1. Desktop sends a compact `host_capabilities_update` after handshake, workspace binding, trust changes, extension changes, or MCP changes.
2. Python indexes only descriptors: ID, summary, source, risk, trust requirement, availability, and schema digest.
3. When the agent selects a native capability, Python emits `host_tool_request` with session, turn, tool-call, workspace, capability ID, bounded arguments, and deadline.
4. Desktop validates workspace identity, current availability, trust, approval, argument limits, and cancellation before invoking `IPulseAIWorkbenchService` or an existing extension/MCP service.
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

## Registration conclusion

Pulse is already correctly installed as a first-party contribution across the fork's common and desktop entry points. The next strengthening step is not another top-level registration. It is a protocol-safe capability broker that connects the already-registered `IPulseAIWorkbenchService` and Code OSS provider registries to the Python agent.
