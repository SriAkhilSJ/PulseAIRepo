---
name: tauri-architect
description: Architect-level Tauri guidance — Rust core versus webview boundary, command and capability permissions, IPC design, update signing, and the platform webview differences that decide what you can rely on across Windows, macOS and Linux. Use when building or reviewing a Tauri app.
license: MIT
compatibility: Tauri 2.x; Rust 1.75+; system webviews
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/tauri-architect
  crusor-origin: original
  crusor-sources: "v2.tauri.app/start; v2.tauri.app/security/capabilities; v2.tauri.app/plugin/updater"
  crusor-triggers: "tauri, rust desktop, webview2, wkwebview, tauri commands, capabilities, tauri updater"
  crusor-verified-on: "2026-10-30"
---

# Tauri Architect

Tauri is **a Rust binary hosting the OS webview**. Small binaries are the
headline; the real architectural work is the command surface and the fact that
three different webviews run your UI.

## When to use

- Small install size and low memory matter.
- Rust on the privileged side (crypto, files, networking, native libraries).
- Security posture: capability-scoped APIs instead of a full Node runtime.

## When NOT to use

- The team cannot maintain Rust alongside the frontend.
- You need identical rendering across OSes with no per-webview testing budget.

## Decision 1 — The webview is a dependency

| OS | Engine | Consequence |
|---|---|---|
| Windows | WebView2 (Chromium) | modern feature support |
| macOS | WKWebView (Safari) | older feature set, different quirks |
| Linux | WebKitGTK | the most divergent; test it or exclude it |

- Baseline your CSS/JS features to the *oldest* engine you support.
- Test on all three, or state explicitly which platforms you support.
- No heavy polyfill strategy: pick features all engines have.

## Decision 2 — Commands and capabilities

- Every `#[tauri::command]` is a capability. Name it for the operation
  (`read_config`), take typed arguments, return typed results.
- Capability files (permissions) declare what windows can call — scope them per
  window, not globally.
- No generic command that takes a path or an HTTP URL and does whatever it says.
- Validate paths against an allow-list of user-chosen directories.
- Keep the Rust core as a library with tests; `main.rs` stays thin.

## Decision 3 — Layer split

```
src/            UI (framework of choice)
  src-tauri/    Rust core: commands, store, updater, plugins
    core/       domain logic, pure Rust, unit-tested
```

- Business rules live in Rust only if they need Rust (performance, OS, secrets);
  otherwise keep them in one place, not duplicated on both sides.
- Long-running work runs on a Rust thread with progress events — never blocks
  the caller indefinitely.
- State shared via `tauri::State`; no globals mutated from commands.

## Decision 4 — Updates and distribution

- Signed updates are mandatory: `tauri-plugin-updater` verifies a signature
  against a public key embedded in the app.
- Private key custody is a production secret — losing it means every installed
  app must be manually replaced.
- Notarization (macOS) and Authenticode (Windows) still apply; Tauri does not
  remove OS requirements.
- Staged rollout: publish the manifest to a percentage, monitor, then widen.

## Decision 5 — Operations

- Log to a file (`tauri-plugin-log`) with rotation; users cannot open devtools in
  production for you.
- Crash/error reporting wired from day one.
- Bundle size check in CI: the advantage is the point — do not ship a 200 MB
  installer.
- Auto-start, tray and deep links configured in the bundle config, tested on
  each OS.

## Failure modes at scale

- Linux support claimed but never tested; WebKitGTK breaks the app.
- A single `run_command(cmd: String)` capability — remote shell via IPC.
- Updater key in the repo, so anyone can sign a release.
- Rust core with all business logic and no tests, because "it compiles".
- Bundle bloat from bundling assets that should be downloaded.

## Verification receipts

1. Capability manifest reviewed per window; no wildcard permissions.
2. Command list with argument validation and tests.
3. Test matrix run on Windows, macOS and Linux (or documented exclusions).
4. Signed update installed end to end, including a failed-signature rejection.
5. Installer size and cold-start time recorded per platform.
