---
name: electron-architect
description: Architect-level Electron guidance — main/renderer/preload separation, IPC contracts and context isolation, native module and packaging strategy, update signing, and the memory and startup costs that make an Electron app feel heavy. Use when building or reviewing an Electron app.
license: MIT
compatibility: Electron 30+; Node 20+
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/runtimes-architect/electron-architect
  crusor-origin: original
  crusor-sources: "electronjs.org/docs/latest; electronjs.org/docs/latest/tutorial/security"
  crusor-triggers: "electron, main process, renderer, preload, contextbridge, ipc, electron builder"
  crusor-verified-on: "2026-10-30"
---

# Electron Architect

Electron is **Chromium plus Node in one product**. The architecture is the wall
between those two, and most Electron incidents are that wall being missing.

## When to use

- A web team shipping a desktop app quickly.
- Existing web codebase reused on desktop.
- Native module ecosystem (serial ports, filesystem, OS APIs) is needed.

## When NOT to use

- Install size and memory are hard constraints (see `tauri-architect`).
- Deep OS integration and platform-native UI are the product.

## Decision 1 — The three processes

```
main        window lifecycle, OS APIs, files, updates — Node, full trust
preload     the ONLY bridge: contextBridge, explicit API surface
renderer    UI — sandboxed, no Node, strict CSP
```

- `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true` — always.
- Preload exposes a **named, typed API** (`window.api.readConfig()`), never
  `ipcRenderer` itself.
- Main validates every IPC argument; the renderer is untrusted input.
- One renderer per window; shared logic in a plain library, not in the preload.

## Decision 2 — IPC contracts

| Pattern | Use |
|---|---|
| `invoke`/`handle` | request/response (default) |
| `send`/`on` | one-way notifications |
| `MessageChannel` | streaming/high-frequency channels |
| web workers | CPU work inside the renderer |

- Channel names are namespaced (`config:read`, `files:pick`), documented, and
  covered by tests.
- No generic passthrough (`invoke('exec', cmd)`); each channel is a deliberate
  capability.
- Never send file paths from the renderer and trust them — resolve and validate
  in main.

## Decision 3 — Native modules and updates

- Native modules need rebuilds per Electron ABI; pin Electron and use prebuilt
  binaries where possible.
- `electron-updater` (or an equivalent) with signed packages and a staged
  rollout; the update server is part of the threat model.
- Code signing: macOS notarization, Windows Authenticode — required by the OS,
  not optional polish.
- Auto-launch, tray and file associations declared in the installers.

## Decision 4 — Performance reality

- Startup: lazy-load windows, defer heavy requires, show a shell immediately.
- Memory: each window is a renderer; close hidden windows, avoid background
  renderers for idle features.
- Long sessions leak through listeners and intervals — audit on unmount and on
  window close.
- Bundle size: the app ships Chromium; do not also ship the entire web catalog.

## Decision 5 — Security posture

- Strict CSP in every renderer; disable remote module and `webview` unless
  required.
- No `shell.openExternal` on unvalidated URLs; allow-list schemes.
- Block new-window and navigation to unknown origins.
- Filesystem access via user dialogs; scope to the chosen directory.

## Failure modes at scale

- `nodeIntegration: true` left on "temporarily".
- Preload exposing raw `ipcRenderer` → renderer can call any channel.
- Unsigned auto-update: an attacker with DNS control pushes the next release.
- Three hidden windows per feature, 1.2 GB RSS after a day.
- OS-level integration broken because the manifest was edited post-build.

## Verification receipts

1. `webPreferences` audit: isolation on, node off, sandbox on, CSP set.
2. IPC surface reviewed: named channels, validated arguments, no passthrough.
3. Memory profile over 8 hours of real usage.
4. Update flow: signed, staged, rollback verified.
5. Cold start measured with the production build, not `npm start`.
