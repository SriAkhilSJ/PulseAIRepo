---
name: winui-architect
description: Architect-level Windows-native design — WinUI 3 and WPF selection, XAML composition and MVVM, MSIX packaging and identity, Windows integration (notifications, file associations, shell), and the deployment model enterprise customers expect. Use when the app must be Windows-native.
license: MIT
compatibility: WinUI 3, WPF, .NET 8, MSIX
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/runtimes-architect/winui-architect
  crusor-origin: original
  crusor-sources: "learn.microsoft.com/windows/apps/winui/winui3; learn.microsoft.com/dotnet/desktop/wpf; learn.microsoft.com/windows/msix"
  crusor-triggers: "winui, wpf, windows app sdk, xaml, msix, windows native, dotnet desktop, windows shell integration"
  crusor-verified-on: "2026-10-30"
---

# WinUI / WPF Architect

Windows-native means **shell integration and enterprise deployment**, not just a XAML
window. The packaging decision shapes everything downstream.

## When to use

- Deep Windows integration: shell, file associations, background tasks, enterprise
  deployment.
- Existing .NET desktop estate.
- Performance-critical UI that a webview cannot deliver.

## When NOT to use

- Cross-platform is a hard requirement → Electron/Tauri.
- The team is web-only and the app is a form over an API.

## Decision 1 — Framework

| Choice | When |
|---|---|
| WinUI 3 | new apps, Fluent design, Windows App SDK |
| WPF | existing .NET Framework/XAML investment |
| Windows Forms | internal tools, legacy maintenance |
| MAUI | .NET across Windows/mobile (weaker desktop shell) |

- WinUI 3 for new work; WPF remains valid where the codebase is large and stable.
- Do not mix UI frameworks in one app; interop is a permanent tax.

## Decision 2 — Packaging

| Packaging | Consequences |
|---|---|
| MSIX | identity, clean uninstall, store, auto-update |
| unpackaged (exe/msi) | more install freedom, fewer APIs, manual updates |

- MSIX gives a package identity required for notifications, startup tasks, and some
  shell APIs.
- Enterprise: provide both where needed, with a documented silent-install path.
- Code-sign everything; unsigned installers trigger SmartScreen.

## Decision 3 — Architecture

- MVVM with a view-model per screen; no business logic in code-behind.
- Dependency injection via the host builder; no static service locators.
- Long operations on background threads; UI thread only for binding updates.
- Navigation service owning the frame/stack; deep links map into it.

## Decision 4 — Windows integration

- Toast notifications with an AppUserModelID (needs identity).
- File associations and "Open with" declared in the manifest.
- Jump lists, taskbar progress, and thumbnail toolbars where they add value.
- Tray icon: background behaviour must be explicit — closing a window is not quitting.
- Credential storage in Windows Credential Manager/DPAPI, not a settings file.

## Decision 5 — Deployment and updates

- MSIX + App Installer for auto-update, or your own updater for unpackaged builds.
- Per-user vs per-machine install decided by IT requirements, not preference.
- Respect MDM/Intune policies; provide an ADMX template if you have settings.
- Test on Windows 10 (oldest supported), Windows 11, ARM64, and a clean VM without
  the .NET runtime if self-contained packaging.

## Failure modes at scale

- Unpackaged build, then notifications silently unavailable.
- Code-behind with business logic; untestable and duplicated.
- Per-machine install requiring admin; enterprise rollout blocked.
- Tray app that keeps running after "close", confusing users and IT.
- ARM64 build missing; Surface and Snapdragon devices run under emulation.

## Verification receipts

1. Framework and packaging decision with the constraint that drove it.
2. MVVM structure with a view model unit test.
3. Toast notification and file association working from an installed MSIX.
4. Silent install and uninstall tested on a clean VM.
5. Build matrix: Windows 10, Windows 11, ARM64.
