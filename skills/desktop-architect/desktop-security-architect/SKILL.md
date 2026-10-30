---
name: desktop-security-architect
description: Architect-level desktop hardening — the full-privilege trust model, secret storage in the OS keychain, CSP and remote content, local file and protocol exposure, code signing as an integrity control, and the enterprise expectations (MDM, EDR, allowlisting) that desktop apps must satisfy. Use when a desktop app touches files, credentials, or enterprise networks.
license: MIT
compatibility: Electron, Tauri, native; Windows/macOS/Linux
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/desktop-security-architect
  crusor-origin: original
  crusor-sources: "electronjs.org/docs/latest/tutorial/security; developer.apple.com/documentation/security; learn.microsoft.com/windows/security"
  crusor-triggers: "desktop security, keychain, credential manager, csp, remote content, sandbox, code signing, mdm, local file access, threat model, security review, desktop hardening"
  crusor-verified-on: "2026-10-30"
---

# Desktop Security Architect

A desktop app runs **with the user's full privileges on the user's machine**. There
is no browser sandbox to fall back on: the architecture is the perimeter.

## When to use

- The app reads local files, stores credentials, or loads remote content.
- Enterprise distribution, EDR/allowlisting, or a security review.
- Auditing an Electron/Tauri app against its own config.

## When NOT to use

- A thin client where all data is server-side and no local capability is used —
  still check CSP and secret storage.

## Decision 1 — Threat model

| Asset | Adversary | Control |
|---|---|---|
| user files | malicious content, path traversal | allowlisted roots, sandboxed code |
| credentials | local malware, other users | OS keychain, per-user scope |
| app integrity | tampering, supply chain | code signing, update verification |
| network trust | MITM, hostile proxies | TLS, certificate handling policy |
| user session | shared machine | lock, re-auth, clear on logout |

Write it down. Desktop incidents are usually "we never considered that the user
could open a file they downloaded".

## Decision 2 — Secrets

- OS keychain (Keychain / Credential Manager / libsecret); never a plaintext config
  file, never `localStorage` for tokens.
- Per-user, not per-machine, for user credentials; per-machine only for
  service-level secrets with a clear rationale.
- Long-lived API keys belong to the backend. The app holds short-lived tokens.
- Secrets are never logged; log scrubbing is configured, not hoped for.
- Environment variables are visible to same-user processes — not a secret store.

## Decision 3 — Content and network

- CSP in every window, no `unsafe-eval`, no `unsafe-inline` for scripts.
- Remote content loads in a separate, locked-down window with the minimal bridge;
  ideally no bridge at all.
- Block unexpected navigation and `window.open` to external schemes; open links in
  the system browser.
- Disable node integration; enable sandbox and context isolation.
- Custom protocol handlers validate input before acting (`app://`, `myapp://`).

## Decision 4 — Files and OS integration

- All file access through an explicit allowlist of roots (user-chosen folders,
  app data, documents), resolved and canonicalised.
- Symlink and junction resolution before the allowlist check — otherwise the
  check is decorative.
- File type validation by content, not extension.
- Clipboard, drag-and-drop, and shell integration are input surfaces: validate
  dropped files the same way.
- No auto-executing anything from a downloaded or opened file.

## Decision 5 — Integrity and enterprise

- Code signing on every platform; notarisation on macOS; reputation builds over
  time on Windows.
- The updater verifies signatures; the app verifies its own update path.
- Respect enterprise controls: MDM configuration, proxy settings, certificate
  stores, EDR hooks. Do not disable AV or TLS inspection silently — document the
  pinning trade-off.
- Provide an allowlisting-friendly installer (stable paths, signed binaries, no
  dropped executables at runtime).

## Failure modes at scale

- `localStorage` holding a refresh token for a year.
- A "preview" window with `nodeIntegration: true` shipped to production.
- Path check on the input string, bypassed by a symlink.
- An auto-update channel served over plain HTTP with no signature check.
- EDR quarantines the app because it writes an executable into temp at launch.

## Verification receipts

1. Threat model table with assets, adversaries, controls.
2. Secret inventory: keychain entries only, verified on disk.
3. CSP and isolation settings inspected in the built app's runtime config.
4. Traversal/symlink tests rejected with typed errors.
5. Signed build verified on a clean machine; EDR/allowlist check passed.
