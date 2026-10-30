---
name: native-desktop-architect
description: Architect-level native desktop guidance — choosing per-OS toolkits, sharing a core across platforms, UI and threading models, sandboxing and permissions, and the packaging and lifecycle rules that native apps are held to. Use when the product needs platform-native desktop software.
license: MIT
compatibility: macOS AppKit/SwiftUI, Windows WinUI/WPF, Linux GTK/Qt; C++/C#/Swift/Rust cores
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/native-desktop-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/appkit; learn.microsoft.com/windows/apps/winui; docs.gtk.org"
  crusor-triggers: "native desktop, winui, wpf, appkit, gtk, qt, sandbox, code signing, native app architecture"
  crusor-verified-on: "2026-10-30"
---

# Native Desktop Architect

Native desktop means **one product, several platforms, one shared core**. The
architecture question is what is shared and what is deliberately per-OS.

## When to use

- Deep OS integration: system extensions, accessibility APIs, drivers, MDM.
- Performance- or latency-critical work (audio, video, CAD, games-adjacent).
- Enterprise distribution with strict signing and management requirements.

## When NOT to use

- Business CRUD UI with a small team (see `electron-architect`,
  `tauri-architect`).

## Decision 1 — What is shared

```
core/            domain logic, persistence, protocols — platform-free, fully tested
  platform/      UI, OS integration, lifecycle — one per OS
    packaging/   installers, signing, updates — one per OS
```

- Share the core, not the UI: platform users notice foreign widgets immediately.
- The core exposes a stable interface (C ABI, Rust FFI, .NET library) with tests
  that run without a GUI.
- Platform UI layers stay thin; business rules never fork per OS.

## Decision 2 — UI model per platform

| Platform | Idiomatic stack |
|---|---|
| macOS | SwiftUI for new surfaces, AppKit for depth |
| Windows | WinUI 3 for new apps, WPF for existing estates |
| Linux | GTK4 or Qt, chosen by the distro target |

- Use the platform's threading rules: UI on the main thread, work off it, and
  marshal results back explicitly.
- Accessibility is part of the UI contract per platform (VoiceOver, Narrator,
  Orca).
- Respect platform conventions for menus, shortcuts, window chrome and
  preferences placement.

## Decision 3 — Privileges and sandboxing

- Run with the least privilege the product can tolerate; request entitlements
  one at a time with a stated reason.
- macOS: App Sandbox + hardened runtime + notarization; security-scoped
  bookmarks for user-chosen files.
- Windows: MSIX or installer with per-user install; avoid requiring admin.
- Linux: Flatpak/Snap sandboxes constrain filesystem and device access; test the
  packaged build, not just the dev run.

## Decision 4 — Lifecycle and data

- The app must survive sleep/wake, network changes, and running for weeks.
- Persist on state change, not only on quit; crashes are a fact.
- Single-instance + file-open events routed to the running instance.
- Migrations versioned, with a backup before destructive upgrades.

## Decision 5 — Updates and enterprise reality

- Signed updates; on macOS notarized; on Windows Authenticode; on Linux the
  distro channel is the update mechanism.
- Enterprise deployments need MSI/PKG, silent install flags, and version
  pinning — plan for the fleet, not the individual.
- Crash reporting with symbol uploads, or every report is unreadable.

## Failure modes at scale

- Business logic triplicated per platform, fixed three times.
- Core tested only through the UI, so regressions are found by users.
- Sandbox entitlements added until the app has full disk access "to work".
- Updates unsigned in a beta build that a customer installs.
- Blocking the UI thread with file I/O on a network share.

## Verification receipts

1. Core test suite runs headless in CI on every platform.
2. UI automation on at least the primary journey per OS.
3. Sandbox/entitlement review with a written justification per entitlement.
4. Signed, notarized artefact installed on a clean machine.
5. Long-run test: sleep/wake, network change, 24-hour session.
