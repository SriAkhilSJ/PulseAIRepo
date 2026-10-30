---
name: appkit-architect
description: Architect-level macOS-native design — AppKit versus SwiftUI for desktop, window and menu architecture, document-based apps and NSDocument, sandboxing and entitlements, Mac App Store versus direct distribution, and the macOS conventions users expect. Use when the app must feel native on macOS.
license: MIT
compatibility: AppKit, SwiftUI on macOS, Swift, notarisation
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/runtimes-architect/appkit-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/appkit; developer.apple.com/documentation/swiftui; developer.apple.com/documentation/security/app_sandbox"
  crusor-triggers: "appkit, macos app, nsdocument, mac app sandbox, mac catalyst, app store mac, menu bar app, notarization mac, mac app, macos, menu bar, menubar app"
  crusor-verified-on: "2026-10-30"
---

# AppKit / macOS Architect

A macOS app is judged on **menus, windows, and sandbox behaviour**. Users do not
forgive a Mac app that behaves like a website in a frame.

## When to use

- A native Mac experience is the product (pro apps, developer tools, utilities).
- Deep system integration: services, drag and drop, menu bar, document handling.
- App Store or notarised direct distribution.

## When NOT to use

- The same UI must ship on Windows/Linux → Electron/Tauri first.
- A thin client where a web app suffices.

## Decision 1 — AppKit or SwiftUI

| Need | Choice |
|---|---|
| new app, mostly standard UI | SwiftUI, AppKit where it falls short |
| document-based, complex window management | AppKit with SwiftUI views inside |
| menu bar utility | SwiftUI `MenuBarExtra` or AppKit status item |
| pro app with custom canvases | AppKit + Metal/SceneKit |

- SwiftUI on macOS still lacks mature equivalents for some AppKit patterns; use
  `NSViewRepresentable` deliberately rather than fighting the framework.
- One navigation model: sidebar/split view, not a pile of windows.

## Decision 2 — macOS conventions

- Menu bar with the standard menus and keyboard shortcuts; a Mac app without a proper
  menu feels foreign.
- Preferences via `Settings` scene/`NSWindowController`, not a custom modal.
- Window state restoration; users expect the app to reopen where they left it.
- Drag and drop, Quick Look, Services, and keyboard navigation where applicable.

## Decision 3 — Documents

- `NSDocument`/`ReferenceFileDocument` for document-based apps — undo, autosave, and
  versions come almost free.
- iCloud Drive or a user-chosen folder; the sandbox restricts arbitrary paths.
- Autosave and version browsing are expected behaviours in a document app.

## Decision 4 — Sandbox and entitlements

- App Sandbox required for the App Store; strongly recommended for direct distribution.
- Entitlements are per capability: file access (user-selected), network client,
  printing, camera.
- Security-scoped bookmarks for persistent access outside the container.
- Hardened runtime + notarisation for direct distribution; check Gatekeeper on a clean
  machine.

## Decision 5 — Distribution

- App Store: sandbox, review, 30% (or reduced rate), no self-update.
- Direct: notarised DMG, Sparkle-style update, licence handling you own.
- Both: one codebase, capability detection at build time; keep the differences in a
  thin layer.

## Failure modes at scale

- No menu bar; keyboard shortcuts absent, users assume the app is broken.
- Sandbox enabled late; file access patterns need a redesign.
- Custom window chrome with broken full-screen and Split View.
- Sparkle updates without signature verification.
- App Store build shipped without sandbox, rejected after weeks.

## Verification receipts

1. Framework split documented: SwiftUI screens, AppKit integrations.
2. Menu bar and shortcut inventory matching macOS conventions.
3. Sandbox entitlements list with the feature each enables.
4. Notarised build launched on a clean machine.
5. Window restoration and document autosave tested.
