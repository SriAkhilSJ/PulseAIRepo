---
name: desktop-distribution-architect
description: Architect-level desktop distribution — code signing and notarization, installer and package formats per OS, auto-update channels with staged rollout and rollback, and the enterprise deployment requirements (silent install, MDM, versions) that decide whether an app can be sold. Use when shipping desktop software.
license: MIT
compatibility: Any desktop stack; Authenticode, Apple notarization, MSIX/DMG/AppImage/Flatpak
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/delivery-architect/desktop-distribution-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/security/notarizing; learn.microsoft.com/windows/msix; electron.build; v2.tauri.app/distribute"
  crusor-triggers: "signing, sign the app, code signing, certificate, notarization, installer, msix, dmg, appimage, auto update, staged rollout, silent install, mdm, mac app, sign our"
  crusor-verified-on: "2026-10-30"
---

# Desktop Distribution Architect

Desktop distribution is **the part users meet before they trust you**. An unsigned
build, a SmartScreen warning, or an update that bricks installs ends the product
faster than any bug.

## When to use

- Preparing installers, signing, notarization, or auto-update.
- Shipping to enterprises (silent install, MDM, version pinning).
- Users report "unknown publisher" or blocked installs.

## When NOT to use

- Internal tools run from source — but sign anyway if anyone outside the team
  installs it.

## Decision 1 — Signing identity

| Platform | Requirement |
|---|---|
| macOS | Developer ID + hardened runtime + notarization + stapling |
| Windows | Authenticode (EV recommended for SmartScreen reputation) |
| Linux | distro signing; Flatpak/AppImage signatures |

- Certificates in a managed secret store with HSM/cloud signing; never on a
  laptop.
- Rotation and expiry monitored — an expired cert stops all releases.
- Sign **the installer and the binaries**, and verify signatures in CI.

## Decision 2 — Package formats

| OS | Format | Notes |
|---|---|---|
| macOS | DMG or PKG | PKG for MDM; DMG for direct download |
| Windows | MSIX or EXE/MSI | MSIX for clean install/update; EXE for broad compatibility |
| Linux | AppImage, deb/rpm, Flatpak, Snap | pick per target distro; Flatpak for sandboxed distribution |

- One canonical download per platform; do not make users choose between five
  artefacts.
- Universal/arm64+x64 builds decided explicitly; Rosetta is a bridge, not a plan.
- Include uninstall path and data location in the docs.

## Decision 3 — Auto-update

- Signed manifests and signed packages; HTTPS only; the update feed is part of
  the attack surface.
- Channels: stable / beta / internal — with separate feeds and separate signing
  keys.
- Staged rollout percentages with automatic halt on crash-rate regression.
- Delta updates where supported to keep downloads small.
- Rollback: keep the previous version installable, and make downgrade possible
  on request.

## Decision 4 — Enterprise requirements

- Silent install flags documented; MSI/PKG/MSIX for MDM deployment.
- Version pinning and a documented support window per major version.
- No mandatory online activation that breaks air-gapped installs, unless the
  product is explicitly cloud-tied.
- Proxy support, offline licensing, and centralised configuration for managed
  fleets.
- Security questionnaires: an SBOM and a signing policy make them survivable.

## Decision 5 — Release operations

- CI builds all platforms from one commit; artefacts archived with hashes.
- Release notes per version; update channel notes for breaking changes.
- Crash and update telemetry by version; adoption visible within days.
- A "can we ship a fix in an hour?" drill: if not, the pipeline is the problem.

## Failure modes at scale

- Unsigned beta handed to a customer, then SmartScreen blocks the paid release.
- Notarization step skipped after a certificate rotation.
- Auto-update feed unauthenticated — update hijack is RCE.
- Each platform's installer built by hand on one engineer's machine.
- Enterprise customer cannot deploy silently, so the deal dies in IT review.

## Verification receipts

1. Signature verification on each artefact (`codesign -dv`, `signtool verify`).
2. Clean-machine install, launch, update, uninstall cycle per OS.
3. Staged rollout with a halt threshold demonstrated.
4. Silent install tested in a clean VM with the MDM command.
5. Certificate expiry and rotation dates tracked with alerts.
