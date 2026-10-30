---
name: desktop-architect
description: Architect-level desktop direction — choosing native, Electron or Tauri from real constraints, the main/renderer and process boundaries, filesystem and OS integration ownership, update and distribution reality, and the resource footprint a desktop app is judged on. Use before any platform-specific desktop skill.
license: MIT
compatibility: Windows, macOS, Linux; native, Electron, Tauri
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect
  crusor-origin: original
  crusor-sources: "electronjs.org/docs; v2.tauri.app; developer.apple.com/documentation; learn.microsoft.com/windows/apps"
  crusor-triggers: "desktop app, electron, tauri, native desktop, cross platform desktop, auto update, desktop architecture, ipc, local database, desktop security, update channel"
  crusor-verified-on: "2026-10-30"
---

# Desktop Architect

A desktop app is **a long-lived local process with real privileges**. It can read
files, run native code, and live for weeks without a restart — which is exactly
why the boundaries matter more than on the web.

## Leaf map

| Need | Skill |
|---|---|
| web stack, huge ecosystem, fast delivery | `electron-architect` |
| small binary, low memory, Rust backend | `tauri-architect` |
| platform-perfect integration, native UI | `native-desktop-architect` |
| typed bridges between UI and privileged core | `desktop-ipc-architect` |
| local database, durability, corruption | `desktop-offline-storage-architect` |
| keychain, CSP, file exposure, hardening | `desktop-security-architect` |
| channels, staged rollout, migrations, rollback | `desktop-update-architect` |
| signing, notarization, updates, installers | `desktop-distribution-architect` |

## Decision 1 — Runtime choice

| Constraint | Choose |
|---|---|
| team is web-only, needs native modules fast | Electron |
| memory/install size matter, security posture strict | Tauri |
| OS-native UI, deep system APIs, MDM/enterprise | native per platform |
| heavy offline data + long sessions | any, but measure memory over 8h |

- Electron ships Chromium per app (~100 MB+); Tauri uses the system webview
  (~5–10 MB) and Rust for the privileged side.
- Native means writing the app N times — a product decision, not a technical
  preference.
- Choose once: hybrid migrations carry both costs.

## Decision 2 — Process boundaries

```
UI (renderer/webview)      → no filesystem, no native calls directly
  privileged core (main/Rust) → files, network, OS APIs, secrets
    OS integrations           → keychain, notifications, trays, deep links
```

- The renderer is **untrusted**: treat it like a browser tab. A compromised
  renderer must not be able to exfiltrate the filesystem.
- IPC is a typed API surface: explicit methods, validated arguments, no
  arbitrary command passthrough.
- Never expose `require`, `eval`, or a generic `exec` to the UI.

## Decision 3 — Local state and data

- SQLite (or an embedded store) for application data; JSON files only for
  config.
- Large binary assets live on disk, referenced by path — not in a database blob.
- Single-instance enforcement; concurrent writers corrupt state.
- Migrations versioned from v1, run at startup with a backup before destructive
  steps.

## Decision 4 — Offline and updates

- Desktop apps are offline by default; sync is a feature with a conflict policy.
- Auto-update is a **security-critical channel**: signed updates, HTTPS, and a
  rollback path. Unsigned updates are remote code execution by design.
- Check for updates on a schedule, on demand, and after long uptime; show what
  changed and let the user defer.
- The app must behave sanely when the update server is unreachable forever.

## Decision 5 — OS integration

- Filesystem access through user-chosen paths (file dialogs), not broad home
  directory permissions.
- Credentials in the OS keychain (Keychain/Credential Manager/libsecret), never
  in a config file.
- Deep links / file associations / tray icons declared in the installer manifest,
  not patched at runtime.
- Respect platform conventions: menu bar on macOS, window controls per OS,
  keyboard shortcuts per platform.

## Decision 6 — Resource discipline

- Memory over a long session is the user-visible metric: leaks surface after
  hours, not minutes.
- Background polling and timers are budgeted; a laptop battery drain is a bug
  report.
- Cold start under 2 s, first interaction under 1 s, measured on a mid-tier
  machine.

## Failure modes at scale

- Renderer with `nodeIntegration` enabled and filesystem access — one XSS is
  full machine compromise.
- IPC exposing `exec(command)`, making the app a remote shell.
- Unbounded memory growth from caches that never evict.
- Auto-update unsigned, or signed with a key nobody can rotate.
- Filesystem writes to paths the user never chose, discovered after data loss.

## Verification receipts

1. Process diagram: renderer, privileged core, IPC surface.
2. Security posture check: context isolation on / strict CSP / no node in
   renderer.
3. Memory measured over an 8-hour session with normal usage.
4. Update flow tested: signed package, rollback, offline server.
5. Cold start and first-interaction timing on a mid-tier device.
