---
name: desktop-testing-architect
description: Architect-level desktop testing — the unit/UI/E2E split for apps with native windows, driving UI automation across platforms, fixture data and test profiles, long-session and migration testing, and the release gate for signed installers. Use when a desktop app needs a test strategy.
license: MIT
compatibility: Playwright/WebdriverIO (Electron), WinAppDriver, XCUITest, AT-SPI
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/quality-architect/desktop-testing-architect
  crusor-origin: original
  crusor-sources: "playwright.dev/docs/api/class-electron; developer.apple.com/documentation/xctest; github.com/microsoft/WinAppDriver"
  crusor-triggers: "installer, packaged app, desktop testing, ui automation, playwright electron, winappdriver, xcuitest mac, e2e desktop, installer test, migration test"
  crusor-verified-on: "2026-10-30"
---

# Desktop Testing Architect

Desktop tests differ from web tests in one crucial way: **the artefact under test is
the installed app**, not a URL. If you never test the installer, you have not tested
the product.

## When to use

- A desktop app with native windows, menus, and file dialogs.
- Existing E2E suite that is slow, flaky, or tests only the dev build.
- Preparing a release gate for signed installers.

## When NOT to use

- A CLI tool — normal unit/integration tests apply.

## Decision 1 — Layers

| Layer | Share | Notes |
|---|---|---|
| unit (domain, mappers) | 60% | fast, no UI |
| component (single window, fakes) | 20% | rendering + state |
| integration (IPC, storage, network fakes) | 15% | the desktop-specific risk |
| E2E on packaged build | 5% | money paths only |

- IPC contracts deserve dedicated tests: they are where desktop bugs live
  (`desktop-ipc-architect`).
- E2E on the packaged, signed build catches what the dev build hides (paths,
  entitlements, sandbox).

## Decision 2 — Automation

- Electron: Playwright's Electron support or WebdriverIO.
- Tauri: drive the webview with a browser driver; native side via commands in tests.
- Native Windows: WinAppDriver/Appium; macOS: XCUITest; Linux: AT-SPI or dogtail.
- Prefer stable, accessible selectors (`data-testid`, accessibility id) over screen
  coordinates.

## Decision 3 — Environment

- Isolated user profiles and app-data directories per test run; never the developer's
  real data.
- Deterministic fixtures for files, databases, and settings.
- Disable animations and auto-update during tests.
- Reset state between tests; leftover windows cause cascading failures.

## Decision 4 — Desktop-specific cases

- Long session: 8-hour memory and handle stability (`desktop-ipc-architect`).
- Upgrade and migration: install N-1, upgrade to N, verify data (`desktop-update-architect`).
- Offline and slow-network behaviour.
- Multiple monitors, DPI changes, and window resize/restore.
- Permission and filesystem edge cases: read-only paths, missing directories, path
  length limits.

## Decision 5 — Release gate

- Automated: packaged build smoke tests on each OS.
- Manual: installer, first-run experience, uninstall (does it leave junk?).
- Crash-free rate in the wild plus a staged rollout gate.

## Failure modes at scale

- E2E only against the dev build; the shipped installer is broken.
- Tests share one profile; flakiness nobody can reproduce.
- Coordinates-based selectors break on every layout change.
- Upgrade path untested; users' local databases are corrupted.
- Suite takes 40 minutes and is skipped on PRs.

## Verification receipts

1. Layer counts and the E2E list.
2. Packaged-build smoke test running in CI per OS.
3. Upgrade test from the previous release with real data.
4. Long-session stability measurement.
5. Install/uninstall review with leftover files identified.
