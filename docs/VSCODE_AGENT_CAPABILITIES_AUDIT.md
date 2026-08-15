# PulseAI IDE — Code OSS Agent Capability Audit

**Date:** 2026-08-15
**Code OSS pin:** `6c27443ce6fdf6ac798c64025d45175e2e23c4b4`
**Method:** GitHub tree/API + selected raw source files. No Code OSS checkout was created.

“Secrets” below means underused internal capabilities—not credentials or private data. Pulse must never inspect another extension's secrets.

## CTO verdict

The Python engine remains the autonomous runtime. Code OSS becomes its **native sensor and actuator layer**. Pulse should not duplicate editor capabilities already supplied by Code OSS or installed extensions.

A narrow `PulseAIWorkbenchService` will own every internal import. The portable UI and Python engine receive stable Pulse contracts only; they never import Code OSS internals directly.

## P0 — capabilities that materially improve correctness

| Capability | Current Code OSS source | Pulse value |
|---|---|---|
| Unsaved/dirty editor truth | `services/textfile/common/textfiles.ts` — `ITextFileService` | Read the buffer the user sees, not stale disk. Detect dirty files before agent edits; save/revert through editor lifecycle. |
| Language feature registries | `editor/common/services/languageFeaturesService.ts` — `ILanguageFeaturesService` | Definitions, references, declarations, implementations, symbols, hover, rename, code actions, formatting, completions, semantic tokens, inlay hints. Providers come from installed language extensions. |
| Diagnostics | `platform/markers/common/markers.ts` — `IMarkerService.read()` | Real errors/warnings, related locations and owner/source. Use as context and verification evidence. |
| Native workspace edits | `contrib/bulkEdit/browser/bulkEditService.ts` — `IBulkEditService.apply()` | Apply multi-file `WorkspaceEdit` with native preview, conflict detection and undo/redo instead of raw writes. |
| Native search | `services/search/common/searchService.ts` — `ISearchService` | File/text search that honors excludes, remote providers and open editor models. Better than a local filesystem-only grep. |
| Test controllers | `contrib/testing/common/testService.ts` — `ITestService` | Discover tests contributed by extensions, run selected tests, cancel runs and map tests to code. |
| Test receipts | `contrib/testing/common/testResultService.ts` — `ITestResultService` | Stream per-test outcomes and diagnostics into verification evidence. |
| Workspace trust | `platform/workspace/common/workspaceTrust.ts` — `IWorkspaceTrustManagementService` / request service | Hard safety gate before terminal/process/file-write capabilities. |
| SCM state | `contrib/scm/common/scmService.ts` — `ISCMService` | Repositories, resource groups, staged/unstaged changes and provider state without parsing Git porcelain for UI truth. |
| Native terminal | Terminal services under `contrib/terminal/` | Open/focus terminals, attach agent receipts and preserve the user's native terminal experience. |

## P1 — high-value differentiators

| Capability | Source | Pulse use |
|---|---|---|
| Native editing sessions | `contrib/chat/common/editing/chatEditingService.ts` — `IChatEditingService` | Streaming edits, per-file accept/reject, snapshots, diff-between-stops and interaction undo/redo. Powerful, but coupled to chat models; adopt behind an adapter only. |
| Language model tool registry | `contrib/chat/common/tools/languageModelToolsService.ts` | Discover editor-native and extension-contributed tools, confirmations, model filters, streaming tool state and tool-specific UI data. Pulse may bridge approved tools rather than duplicate them. |
| MCP registry/service | `contrib/mcp/common/mcpService.ts` | Discover workspace/profile MCP servers, roots, enablement and interaction requirements. Never auto-import MCP capabilities without policy review. |
| Extension lifecycle | `services/extensions/common/extensions.ts` — `IExtensionService` | Wait for extensions, activate only relevant language/test/debug providers, inspect availability and degrade explicitly. |
| Debugger state | `contrib/debug/browser/debugService.ts` | Breakpoints, sessions, call stack, variables and evaluate. Enables real debug-agent workflows later. |
| Outline | `services/outline/browser/outlineService.ts` | Editor-native document outline for focused symbol context. |
| Timeline | `contrib/timeline/common/timelineService.ts` | Per-file history from Git and other providers; useful for regression archaeology. |
| Editor history | `services/history/browser/historyService.ts` | Recently active files/workspace roots and navigation state—high-signal context without scanning everything. |
| Notebooks | `contrib/notebook/browser/services/notebookEditorService.ts` | Active notebook editors/cells; enables Jupyter workflows without flattening notebooks to JSON. |
| Remote workspaces | `services/remote/common/remoteAgentService.ts` + path service | Correctly target WSL/SSH/dev-container files and processes instead of assuming local disk. |
| Agent-host terminal | `contrib/terminal/browser/agentHostTerminalService.ts` | Current Code OSS already has terminal lifecycle for remote agent-host connections, reconnection and output attachment. Reuse patterns for Pulse remote execution. |

## P2 — product polish and leverage

- `ICommandService`: invoke editor/build/test/debug commands.
- `IQuickInputService`: file, symbol, session and checkpoint pickers.
- `IProgressService`: native progress and cancellation.
- `INotificationService` / dialogs: crash, approval and restore UX.
- `IStatusbarService`: engine state and active run.
- `IContextKeyService`: enable/disable commands based on engine, trust, selection and approval state.
- `IStorageService`: UI state scoped to window/workspace/profile.
- `ISecretStorageService`: Pulse-owned provider credentials only.
- Decorations/code lenses/code actions: “Explain/Fix/Test with Pulse” at the selection or diagnostic.
- Editor groups: open Pulse Manager, native diffs and evidence side by side.

## Extension leverage without making Pulse an extension

Installed extensions remain capability providers:

1. Wait for `IExtensionService.whenInstalledExtensionsRegistered()`.
2. Activate only the event/provider required by the current task.
3. Read registered language capabilities through `ILanguageFeaturesService`.
4. Read tests through `ITestService`, SCM through `ISCMService`, debuggers through debug services, and tasks through task services.
5. Report `available / unavailable / degraded`; never silently pretend a provider exists.

Examples:

- Python extension → definitions, references, diagnostics, tests, debug.
- Rust Analyzer → semantic symbols, references, code actions, formatting.
- Go extension → test/debug/language providers.
- Git provider → SCM and timeline.
- ESLint/linters → marker diagnostics and code actions.
- Remote extensions → remote filesystem and execution context.

## Security boundaries

- Pulse can access **only Pulse-owned** secret keys. Never enumerate or read another extension's secrets.
- Workspace trust gates process execution, writes, MCP and debug.
- Extension/MCP/editor tools go through the Pulse approval policy and `tool_id` receipts.
- Dirty buffers are never overwritten; native conflict checks and previews win.
- Remote authority and URI scheme are preserved end-to-end.
- Native bulk edits and test/debug commands are auditable host operations, not hidden model side effects.

## Implementation status

**Host milestone A started:** active/diff editor selection, dirty/visible buffer text, diagnostics, document symbols, definitions, references, open resource, native diff, trust status/events, and capability availability are implemented behind `PulseAIWorkbenchService`.

**Safe actuators:** `IBulkEditService` applies expected-version text edits only in trusted workspaces, requires the originating approval `tool_id`, supports native preview, and requests confirmation before undo. Native terminal commands and Code OSS tasks likewise require trust + approval identity.

**More native sensors:** workspace search now uses `QueryBuilder` + `ISearchService` (workspace excludes, remote providers and open models); SCM snapshots use `ISCMService`; tests are discovered/run through `ITestService` and streamed from `ITestResultService`.

## Implementation order

### Host milestone A — Context sensors

1. Active editor/selection and dirty text.
2. Diagnostics.
3. document symbols, definitions and references.
4. native search.
5. SCM and editor history.

### Host milestone B — Safe actuators

1. Native diff preview.
2. `IBulkEditService` apply with undo/redo.
3. native terminal and tasks.
4. test discovery/run/results.
5. workspace-trust enforcement.

### Host milestone C — Advanced integration

1. debug sessions;
2. notebook context;
3. MCP/editor-native tool bridge;
4. remote workspaces and agent-host terminal;
5. optional native chat-editing-session adapter.

## Explicit anti-goals

- Do not couple the engine directly to dozens of unstable internal interfaces.
- Do not call private APIs from the portable renderer.
- Do not activate every extension at startup.
- Do not replace the engine's durable checkpoint store with Code OSS chat internals.
- Do not expose secrets or silently auto-approve extension/MCP tools.
