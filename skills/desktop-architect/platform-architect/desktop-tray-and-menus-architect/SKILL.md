---
name: desktop-tray-and-menus-architect
description: Architect-level shell integration — tray/menu-bar behaviour, global menus and shortcuts, background vs quit semantics, notifications from the shell, and the platform conventions that decide whether an app feels native. Use when the app lives in the system tray or drives global commands.
license: MIT
compatibility: Tray APIs, global shortcuts, Windows toast, macOS menu bar, Linux AppIndicator
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/platform-architect/desktop-tray-and-menus-architect
  crusor-origin: original
  crusor-sources: "electronjs.org/docs/latest/api/tray; developer.apple.com/design/human-interface-guidelines/the-menu-bar; docs.gtk.org/gtk4"
  crusor-triggers: "system tray, menu bar app, global shortcut, notification, window close behaviour, appindicator, tray, menubar, background app"
  crusor-verified-on: "2026-10-30"
---

# Tray & Menus Architect

A tray app is **a background process with a UI affordance**. The architecture
question is what "close" means — and every platform answers differently.

## When to use

- Always-available utilities: sync, capture, clipboard, monitoring.
- Background workers with occasional user interaction.
- Apps that need global shortcuts.

## When NOT to use

- Primary window apps that would confuse users by living in the tray.
- Platforms where tray support is unreliable (some Linux desktops without
  AppIndicator).

## Decision 1 — Lifecycle semantics

| Action | Convention |
|---|---|
| close window | Windows/Linux: often quit; macOS: window closes, app stays |
| quit | explicit menu item / Cmd+Q |
| launch at login | opt-in, visible in settings |
| background work | must be visible via an indicator |

- Decide and document what closing does; a tray app that quits on close becomes an
  invisible background process the user cannot find.
- Provide a single explicit "Quit" and make the tray icon's state visible.
- First run: explain that the app runs in the tray, or users will think it crashed.

## Decision 2 — Tray behaviour

- Menu items: primary action first, settings, then quit; keep it under ~8 items.
- Tooltip/status text reflects live state (connected, syncing, errors).
- Left click = primary action or open window; right click = menu (platform-dependent).
- Badges/counters where supported; do not animate the icon continuously.

## Decision 3 — Menus and shortcuts

- Menu structure follows platform convention (macOS app menu, Windows/Linux menu bar).
- Accelerators use the platform modifier and are discoverable in the menu.
- Global shortcuts: register, detect conflicts, and let the user change them.
- Every menu action must also be reachable without the tray, or the app is unusable
  when the tray fails.

## Decision 4 — Shell notifications

- Native notifications with actions where supported; respect Do Not Disturb.
- Never spam: rate-limit, deduplicate, and provide a per-event mute.
- Clicking a notification should open the relevant context, not just the app.

## Decision 5 — Platform variance

- macOS: menu bar extra + dock icon policy (LSUIElement for menu-bar-only apps).
- Windows: notification area overflow; users may never see the icon — provide an
  in-app path.
- Linux: AppIndicator/StatusNotifier support varies; GNOME needs an extension, so
  always have a window-based fallback.

## Failure modes at scale

- Tray-only app on GNOME where the icon never appears; unusable.
- Close quits the app; background sync silently stops.
- Global shortcut conflicts with the OS or another app, unchangeable.
- Notification flood from a sync error loop.
- Dock icon and tray icon both present with different menus.

## Verification receipts

1. Lifecycle semantics documented and tested per platform.
2. Tray menu on each OS, including a no-tray fallback path.
3. Global shortcut conflict detection and rebinding.
4. Notification rate limiting and click routing verified.
5. First-run explanation of background behaviour.
