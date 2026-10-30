---
name: native-feel-architect
description: Architect-level "native feel" for cross-platform desktop — the native-shell + system-WebView + shared-core architecture, why Electron and Tauri lose material and windowing control, WebView throttling and first-paint failures with their fixes, and honest memory baselines. Use when a multi-OS app must feel native.
license: MIT
compatibility: AppKit + WKWebView, WPF/WinUI + WebView2, UniFFI, Node sidecar
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/runtimes-architect/native-feel-architect
  crusor-origin: adapted
  crusor-sources: "github.com/yetone/native-feel-skill@9bd88c6378e1a80a4da165f3ee7bebb761a74945 (MIT, Copyright (c) 2026 yetone)"
  crusor-triggers: "cross platform desktop, electron alternative, webview wrapper, wry, wails, raycaster architecture, webview2, wkwebview, hidden window throttling, feels like a web, native feel, ram, memory usage, flicker, white flash, first paint, feels like a website, feels like a web app, looks like a web app, feel native, feels native"
  crusor-verified-on: "2026-10-30"
---

# Native-Feel Architect

A native-feel cross-platform app is **not a web app with native hooks** and not
Electron with a theme. It is a native shell that owns the window, hotkeys, menu bar,
materials and lifecycle, embedding the OS WebView purely as a rendering surface.

Adapted from `yetone/native-feel-skill` (MIT, (c) 2026 yetone), which distilled this
architecture from Raycast's public rewrite notes and reverse-engineering of the
shipping binary. See `skills/THIRD-PARTY-NOTICES.md`.

## When to use

- A multi-OS desktop app where launch speed, window behaviour and OS materials decide
  adoption.
- Users say the app "feels like a website", or the app competes with a native
  incumbent (launcher, mail, notes).
- Hotkey-driven, always-available surfaces where first-frame latency is the product.

## When NOT to use

- Utilities where Electron/Tauri is fine and native feel is not a differentiator.
- One OS only — write it natively and skip the whole tax.
- Teams without native-platform skills on at least macOS and Windows.

## Decision 1 — Architecture shape

| Layer | Owns |
|---|---|
| native shell (Swift/AppKit, C#/WPF) | window, tray, menu bar, materials, hotkeys, lifecycle |
| system WebView | rendering only — one shared TypeScript UI |
| long-lived Node/core process | business logic, background work |
| Rust library via UniFFI | hot paths: indexing, crypto, parsing |

- The shell must be the app's owner; the WebView is a view, never the app.
- One declared interface generates typed clients for every side. Hand-written IPC
  types in four languages drift within a sprint.
- Performance-critical and security-critical code goes to Rust behind typed
  bindings, not into the renderer.

## Decision 2 — Why not Electron or Tauri

- Electron abstracts away the system WebView, the window class and material APIs;
  vibrancy/acrylic/Liquid Glass cannot be reached without forking it.
- Tauri ships its own WebView wrapper and abstracts platform APIs too — acceptable
  for utilities, not for apps where every window animation must match the OS.
- Both are the right answer when native feel is **not** the requirement. Say so
  rather than over-engineering.

## Decision 3 — WebView survival

Defaults assume a browser tab, not a native surface; override precisely.

- **Hidden-window throttling:** a prewarmed but invisible window gets `rAF` at ~1 Hz,
  so the first animation hitches. Fix in three parts — disable occlusion detection on
  the host window, prewarm with `alphaValue = 0` while ordering front, and keep a
  no-op `requestAnimationFrame` loop running so the frame budget stays allocated.
- **First-paint flicker:** ordering the window front before the WebView has drawn
  shows an empty frame. Synchronise visibility with the next presentation update, or
  fall back to a short delay after load. The synchronised call on macOS is a
  long-stable *private* API — treat it as a liability with a documented fallback.
- Audit every platform default that assumes browsing: text selection, cursor
  changes, scroll physics, rubber-banding, context menus.

## Decision 4 — Native conventions

- Rows and buttons do not change the cursor on hover; that is what makes a UI feel
  web.
- Use the OS blur/material APIs; the OS draws them better than any CSS approximation.
- Menu bar, settings window, About panel and quit semantics follow the platform, even
  when the UI inside is HTML.
- Respect system appearance, accent colour, and reduced motion.

## Decision 5 — Honest cost

- Baseline resident memory you cannot optimize away: roughly 90 MB on macOS and
  130 MB on Windows for shell + one blank WebView, before app code.
- A mature app of this shape lands in the hundreds of MB; a native-only build would
  be lower. That gap is the cross-platform tax, paid to ship one UI.
- Measurement lies: compressed pages, shared frameworks charged per process, and GPU
  helper memory inflate "usage". Memory **pressure**, not the usage column, is the
  signal that matters.

## Failure modes at scale

- Choosing this architecture for an app where native feel was never the requirement;
  permanent complexity for no user-visible gain.
- Renderer doing work that belongs in the core process; UI freezes under load.
- Private-API dependency in the launch path; an OS update breaks startup.
- Four runtimes with hand-written IPC; contract drift and silent field mismatches.
- Optimising memory against Activity Monitor numbers until the real leak is missed.
- Shipping the "native" theme without native menus, quit semantics, or hotkeys.

## Verification receipts

1. Architecture diagram naming the four runtimes and the single IDL.
2. Cold-start to first painted frame measured on both OSes, plus hotkey-to-visible.
3. Hidden-window throttling reproduced and fixed, with the before/after frame rate.
4. Private-API inventory with fallbacks documented for each.
5. Resident memory reported as baseline versus margin, with pressure observed under load.
