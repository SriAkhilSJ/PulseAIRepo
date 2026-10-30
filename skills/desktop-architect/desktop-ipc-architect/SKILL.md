---
name: desktop-ipc-architect
description: Architect-level desktop process and IPC design — main/renderer or Rust-core boundaries, typed command surfaces versus generic bridges, sandboxing and context isolation, worker and child processes, and the message-passing discipline that survives long sessions. Use when the privileged core and the UI must talk.
license: MIT
compatibility: Electron contextBridge/ipcMain, Tauri commands, Chromium IPC
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/desktop-ipc-architect
  crusor-origin: original
  crusor-sources: "electronjs.org/docs/latest/tutorial/context-isolation; electronjs.org/docs/latest/tutorial/ipc; v2.tauri.app/develop/calling-rust"
  crusor-triggers: "ipc, contextbridge, ipcmain, tauri command, preload script, context isolation, renderer, main process, sandbox, worker thread, bridge, secure bridge, freeze, freezes, blocking the ui"
  crusor-verified-on: "2026-10-30"
---

# Desktop IPC Architect

IPC is **an API you are publishing to an untrusted caller**. Design it like a public
interface: typed, minimal, validated, and documented.

## When to use

- Wiring a renderer to a privileged core (Electron, Tauri, CEF, WebView2).
- Moving work off the UI thread.
- An existing bridge with `exec`, `require`, or a generic `invoke(channel, …)`.

## When NOT to use

- A single-process native app with direct API calls.
- The problem is the remote HTTP contract → web API books.

## Decision 1 — The boundary

| Model | Privileged side | Untrusted side |
|---|---|---|
| Electron | main + preload bridge | renderer (Chromium) |
| Tauri | Rust core | webview |
| CEF/WebView2 | host process | embedded page |
| multi-process native | broker service | UI process |

- `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true` are defaults,
  not hardening extras.
- The preload exposes **named functions with narrow types**, never `ipcRenderer` or
  a generic `invoke`.
- Every renderer page — including remote content — gets the same minimal surface.

## Decision 2 — Command surface

- One module per domain (`files.*`, `settings.*`, `window.*`), each function with
  an explicit input schema and a documented return or error type.
- Validate arguments in the privileged process, always; the renderer's TypeScript
  types are not enforcement.
- Paths: resolve against an allowed root and reject traversal; never pass raw
  user-supplied absolute paths to a privileged operation.
- Return serialisable data only; no functions, no class instances, no cycles.

## Decision 3 — Async, streams and cancellation

- Request/response for commands; events for push (progress, state changes) with a
  clear unsubscribe path.
- Long operations return an id and stream progress; provide cancel.
- Large payloads: pass a file path or stream, never a 200 MB JSON blob.
- Backpressure: bound the event rate — a renderer that cannot keep up must not
  grow an unbounded queue.

## Decision 4 — Concurrency and threading

- UI thread never blocks: filesystem, CPU-heavy, and network work goes to worker
  threads, child processes, or the Rust side.
- Child processes are spawned with an explicit argument list (no shell string),
  a working directory, and an environment allowlist.
- Resource caps on workers; a runaway worker must be killable.
- Crash of a worker is recoverable; crash of the main process is not — keep
  privileged code small and well-tested.

## Decision 5 — Lifecycle and long sessions

- Windows can live for weeks: no unbounded listener registration, no leaked
  handles, no timers left running after a window closes.
- Recreate state deliberately on reload; do not assume process memory persists.
- Windows/instances: one owner of global state (tray, menu, single-instance lock).

## Failure modes at scale

- A preload exposing `invoke(channel, args)` — that is remote code execution with
  extra steps.
- Path traversal from a "recent files" entry.
- Event listeners re-registered on every navigation, leaking memory for days.
- UI freezes during a large file read done on the main thread.
- Child process spawned through a shell, argument injection follows.

## Verification receipts

1. Bridge surface inventory: every exposed function with its schema.
2. Isolation settings verified in the built app, not just the config file.
3. Traversal test: hostile paths rejected with a typed error.
4. Profiling of a long session showing flat memory and stable listener counts.
5. Worker crash injection: app recovers, UI reports it.
