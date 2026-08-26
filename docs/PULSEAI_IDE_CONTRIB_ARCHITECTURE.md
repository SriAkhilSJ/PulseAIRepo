# PulseAI IDE — Workbench Contribution Architecture

**Decision date:** 2026-08-15
**Status:** Founder-approved and implementation-started

## Non-negotiable placement

Pulse is a first-party Code OSS workbench contribution, committed in place inside the canonical vendored fork at `desktop/vscode/`. All paths below are fork-relative:

```text
src/vs/workbench/contrib/pulseai/
├── browser/
│   ├── pulseAI.contribution.ts
│   ├── pulseAIViewPane.ts
│   ├── pulseAIManagerEditor.ts
│   ├── pulseAIRenderer.ts
│   ├── pulseAIRendererService.ts
│   ├── pulseAIWorkbenchService.ts
│   └── media/
├── common/
│   ├── pulseAIProtocol.ts
│   ├── pulseAIEngineService.ts
│   ├── pulseAIRendererService.ts
│   ├── pulseAIToolCatalog.ts
│   ├── pulseAIWorkbenchService.ts
│   └── pulseAIWorkerService.ts
├── electron-browser/
│   ├── pulseAI.desktop.contribution.ts
│   └── pulseAIEngineService.ts
└── node/
    ├── pulseAIWorkerMain.ts
    └── pulseAIWorkerProcessService.ts
```

There is no Pulse extension manifest, activation event, marketplace package, or extension-host implementation. The browser UI Lab is a design and visual-verification harness only.

## Two surfaces, one event model

### Agent UI

A compact sidebar view for the current workspace and session:

- streaming conversation;
- plan state;
- tool cards;
- approval and question docks;
- verification receipts;
- cancel, steer, and queue;
- compact numeric usage.

### Pulse Manager

A wide workbench **editor tab inside the VS Code editor area**—not a separate VS Code application and not the source-code text editor itself. It is registered through `PulseAIManagerInput` + `PulseAIManagerEditor`; the compact Agent UI remains an Activity Bar `ViewPane`.

It manages multiple projects and sessions:

- workspace/session list;
- parent/sub-agent hierarchy;
- diffs and changed files;
- verification evidence;
- checkpoints;
- terminals;
- costs and runtime state.

No activity timeline, token graph, or node-canvas visualization is part of the product.

## Browser-first without a rewrite

The approved visual language and deterministic interaction fixtures remain under `ui/`. The production renderer is now a framework-neutral DOM module, `browser/pulseAIRenderer.ts`, mounted by both first-party workbench surfaces. One singleton `PulseAIRendererService` is the production host adapter and Protocol v2 event model:

```text
PulseAIViewPane ─┐
                 ├─ pulseAIRenderer.ts ← PulseAIRendererService
ManagerEditor ───┘                         ├─ IPulseAIEngineService
                                           └─ IPulseAIWorkbenchService
```

The renderer emits typed host intents for prompts, cancel/steer, approvals, file reveal, checkpoints, and engine retry. The host decides how to execute them. This keeps Code OSS internal APIs, Electron, and Node out of the portable renderer. The browser UI Lab remains the visual regression and tool-gallery harness; parity tests pin both catalogs to the same 36 canonical runtime names.

## Code OSS services to use

All imports are isolated behind `IPulseAIWorkbenchService` and focused Pulse adapters. This contains upstream API churn. The current 29-capability sensor/actuator audit—including dirty buffers, language providers, native bulk edit, tests, SCM, MCP, debug, notebooks and remote workspaces—is in `docs/VSCODE_AGENT_CAPABILITIES_AUDIT.md`.

| Code OSS capability | PulseAI use |
|---|---|
| `IViewsService` / view registries | Register and focus the compact Pulse view |
| `IEditorService` / `IEditorGroupsService` | Open Pulse Manager, files, and native side-by-side diff editors |
| `IFileService` / `ITextFileService` | Observe workspace files and dirty-buffer state without bypassing editor lifecycle |
| `IWorkspaceContextService` | Resolve workspace/folder identity for bridge sessions |
| Workspace trust service | Block dangerous host actions in untrusted workspaces |
| `IMarkerService` | Feed diagnostics and verification evidence to Pulse |
| Language feature services | Definitions, references, symbols, formatting, code actions, and hover context supplied by installed language extensions |
| `ITerminalService` | Open/focus native terminals and attach command receipts |
| `ISCMService` | Show repository/change state and open source-control resources |
| `ICommandService` | Expose `PulseAI: Open Manager`, focus, cancel, explain, and fix commands |
| `IQuickInputService` | File/symbol/session pickers and command-palette flows |
| `INotificationService` / dialog service | Crash, approval, restore, and verification notifications |
| `IStatusbarService` | Compact engine/session state with no decorative graph |
| `IConfigurationService` | Model, engine path, approval policy, and UI preferences |
| `IStorageService` | Window/workspace-scoped UI state; no secret keys |
| Secret storage/credential services | Provider keys and tokens; never persisted by the UI bundle |
| Lifecycle/host services | Graceful engine shutdown, restart, and window reload recovery |
| Native `ViewPane` / `EditorPane` DOM hosts | Mount the portable renderer without an extension webview |

Exact interface names can move between Code OSS versions. The pinned fork commit is the source of truth; only the host adapter may depend on these internals.

## How existing extensions improve Pulse without containing Pulse

Language and platform extensions remain useful. Pulse consumes the capabilities they register with the workbench:

- TypeScript/JavaScript language service;
- Python, Go, Rust, Java, C/C++ language extensions when installed;
- Git and SCM providers;
- debuggers;
- formatters and linters;
- test controllers;
- remote workspace providers.

Pulse itself still lives in `src/vs/workbench/contrib/pulseai/` (committed in place inside `desktop/vscode/`). Extensions are capability providers, not the Pulse host.

## Native actions that must stay outside the UI renderer

- opening and applying a native diff;
- reading dirty editor buffers;
- revealing a file and line range;
- opening/focusing terminal instances;
- workspace trust and path authorization;
- credential access;
- spawning or terminating the Python engine;
- restoring checkpoints;
- extension/language-feature invocation.

## Desktop sidecar process boundary

Pulse uses Code OSS's existing `IUtilityProcessWorkerWorkbenchService`, not Node privileges in the renderer:

```text
Pulse View / Manager → IPulseAIEngineService
  → Code OSS utility process
  → PulseAIWorkerProcessService
  → python -m src.bridge
```

The utility worker validates the engine root and frames, spawns with `shell:false`, bounds stdout/stderr, negotiates Protocol v2, and terminates with the workbench window. A desktop-only registration import keeps Electron APIs out of web builds. Because Code OSS utility workers are string-addressed, optimized packages do not discover them through the workbench import graph; the founder-approved overlays `desktop/vscode/build/buildfile.ts` (legacy gulp path) and `desktop/vscode/build/next/index.ts` (current esbuild path) each list `pulseAIWorkerMain` as a desktop-only bundle entry point. The esbuild path hardcodes its `desktopEntryPoints` and does not consume `buildfile.ts`.

## Bridge direction

The current Python bridge exposes sessions, prompt/streaming, cancel, steer, queue, approvals, checkpoints, sub-agents, event replay, and shutdown. Protocol v2 is negotiated by the desktop client and Python bridge; frame-name/version constants are generated from the JSON manifest and payload unions are parity-tested.

The contract covers:

- Python encoder/decoder;
- TypeScript discriminated unions;
- `tool_id` approval identity;
- turn/session/event identity;
- unknown-event forward compatibility;
- crash/reconnect replay.

Protocol types must not be maintained independently by hand.

## Product identity

- Product: **PulseAI IDE**
- Agent: **Pulse**
- Manager: **Pulse Manager**
- Runtime: **PulseAI Engine**
- Contribution directory: `pulseai`
- Editor data: `.pulseai-ide`
- Engine data: `.pulseai`

Pulse cyan marks running/connected intelligence. Agent violet marks delegation and the endpoint node. Green is verification, amber is approval/warning, and red is failure/destructive action.

The canonical app mark lives at `branding/pulseai-mark.svg` and generates the Code OSS Windows, macOS, Linux, server, and browser icon resources. The IDE chrome stays VS Code Dark 2026 native-neutral: no global workbench chrome is recolored (`browser/pulseAIBranding.ts` was removed). Pulse contributes only semantic color tokens via `browser/media/pulseAI-tokens.css`, so user customizations and high-contrast themes remain authoritative.
