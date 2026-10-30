---
name: gtk-architect
description: Architect-level Linux desktop design — GTK4/libadwaita versus Qt, Wayland and X11 realities, Flatpak/Snap packaging and portals, distribution across diverse desktops, and the accessibility and theming expectations Linux users hold. Use when shipping a Linux desktop app.
license: MIT
compatibility: GTK4/libadwaita, Qt6, Flatpak, Snap, AppImage
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/runtimes-architect/gtk-architect
  crusor-origin: original
  crusor-sources: "docs.gtk.org/gtk4; developer.gnome.org/documentation; docs.flatpak.org; doc.qt.io/qt-6"
  crusor-triggers: "gtk, gtk4, libadwaita, qt, linux desktop, flatpak, snap, appimage, wayland, x11"
  crusor-verified-on: "2026-10-30"
---

# Linux Desktop Architect

Linux means **one binary and a dozen desktops**. The architecture question is which
display stack, which packaging, and which conventions you target.

## When to use

- A native Linux app is required (performance, system integration, licensing).
- Packaging for multiple distributions is in scope.
- Wayland-specific behaviour matters (fractional scaling, input methods, screen
  capture).

## When NOT to use

- Cross-platform UI with a webview meets the need → Tauri/Electron.
- The app is a CLI with a config file.

## Decision 1 — Toolkit

| Toolkit | Fit |
|---|---|
| GTK4 + libadwaita | GNOME-native feel, modern adaptive widgets |
| Qt 6 | KDE-native, commercial apps, broad platform support |
| Electron/Tauri | web skills, faster delivery, heavier or lighter footprint |

- GTK and Qt both work on any desktop, but native look comes from the toolkit matching
  the user's environment; libadwaita assumes GNOME conventions.
- Respect the desktop's dark mode and accent colour APIs rather than hardcoding.

## Decision 2 — Display server

- Wayland is the default on modern desktops; X11 remains on older setups.
- Test on both: global shortcuts, screen capture, window positioning, and tray icons
  behave differently.
- Fractional scaling and input method (IBus/Fcitx) support decide whether text entry
  works for non-Latin users.
- Avoid APIs that only exist under X11 unless you ship a documented fallback.

## Decision 3 — Packaging

| Format | Notes |
|---|---|
| Flatpak | sandboxed, portals, Flathub distribution |
| Snap | sandboxed, Ubuntu-centric, automatic updates |
| AppImage | portable, no sandbox, manual updates |
| distro packages (deb/rpm) | native integration, maintenance burden |

- Flatpak is the default recommendation for broad reach; portals replace direct
  filesystem access.
- Sandboxing changes file access: use XDG portals (`xdg-desktop-portal`) for file
  chooser, notifications, and opening URIs.
- Ship the runtime dependencies; do not assume the user's distro versions.

## Decision 4 — Desktop integration

- `.desktop` entry, icon at multiple sizes, AppStream metadata for store listings.
- Notifications via the freedesktop spec; actions where supported.
- Respect the user's theme, fonts, and scaling — do not force a look.
- Accessibility: GTK/Qt provide the AT-SPI bridge; test with Orca.

## Decision 5 — Updates

- Flatpak/Snap update automatically; document the channel and rollback.
- AppImage and distro packages need your own update path or none at all — say which.
- Long-term support: track the runtime (e.g. GNOME runtime) lifecycle.

## Failure modes at scale

- Sandboxed Flatpak with direct `~/.config` writes; the file silently goes to the
  sandbox.
- Tray icon that only works under X11; missing on GNOME Wayland.
- Hardcoded light theme; unreadable in dark mode.
- AppImage requiring a library the user's distro does not ship.
- Custom window decorations that break under tiling window managers.

## Verification receipts

1. Toolkit and packaging decision with the target desktops listed.
2. Test pass on GNOME Wayland, KDE Plasma, and one X11 session.
3. Portal-based file access verified inside the Flatpak sandbox.
4. Dark mode, scaling, and non-Latin input tested.
5. AppStream metadata and desktop entry validated by the packaging tools.
