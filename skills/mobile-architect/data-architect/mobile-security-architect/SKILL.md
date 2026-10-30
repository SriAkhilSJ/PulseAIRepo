---
name: mobile-security-architect
description: Architect-level mobile security — the trust model of a device you do not own, token storage in Keychain/Keystore, biometrics and session lifetime, deep links and IPC as an attack surface, certificate pinning's cost, and what tampering can and cannot be defended against. Use when a mobile app handles accounts, payments, health data, or enterprise access.
license: MIT
compatibility: iOS Keychain, Android Keystore, App Attest, Play Integrity
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/data-architect/mobile-security-architect
  crusor-origin: original
  crusor-sources: "developer.android.com/privacy-and-security/keystore; developer.apple.com/documentation/security; owasp.org/www-project-mobile-top-10"
  crusor-triggers: "mobile security, keychain, keystore, biometric, jwt in app, certificate pinning, app tampering, deep link, jailbreak, auth token, token storage, secure storage, keychain storage"
  crusor-verified-on: "2026-10-30"
---

# Mobile Security Architect

The device is **outside your trust boundary**. Every secret that reaches the app
must be cheap to lose, and every check the client makes must be re-checked on the
server.

## When to use

- Handling accounts, tokens, payments, health or enterprise data.
- Designing login, biometrics, or secure storage.
- Adding deep links, file sharing, or a webview.

## When NOT to use

- Purely anonymous, offline, no-account utility.
- The finding is a server-side authorization bug → web security books.

## Decision 1 — Trust model

| Assumption | Consequence |
|---|---|
| device may be rooted/jailbroken | do not rely on local checks |
| app binary can be extracted | no API keys, no long-lived secrets |
| traffic can be intercepted (user CA) | pinning raises cost, never absolute |
| storage is readable if unlocked+compromised | encrypt with a Keychain-backed key |

- Anything enforcing money, entitlements, or permissions belongs on the server.
- Client checks are UX and defence-in-depth, never the control itself.

## Decision 2 — Tokens and credentials

- Access token: short-lived (minutes), in memory. Refresh token: in Keychain /
  Keystore-backed storage, rotating.
- Never in UserDefaults / SharedPreferences / a plist / build config.
- One keychain item per concern; accessibility class chosen deliberately
  (`whenUnlockedThisDeviceOnly` for anything sensitive).
- Logout clears tokens, cached PII, and the local database of user data.
- Do not put API keys for third-party services in the app — proxy through your
  backend.

## Decision 3 — Authentication and biometrics

- Biometrics unlock a key; they are not the credential. The credential is a
  device-bound key attested by the platform.
- Refresh token rotation with reuse detection: a replayed token means theft.
- Session lifetime, idle timeout, and re-auth on sensitive actions (payment,
  export) are stated, not implied.
- Enterprise: SSO via the system browser (ASWebAuthenticationSession / Custom
  Tabs), never an embedded webview login.

## Decision 4 — Surfaces

| Surface | Rule |
|---|---|
| deep links / universal links | validate the URL, never auto-execute actions |
| webviews | allowlist origins, no JS bridge exposing native APIs |
| file import/export | validate type, size, path traversal |
| clipboard | no secrets written implicitly |
| screenshots/app switcher | blur sensitive screens |
| push payloads | no secrets; they are visible on the lock screen |

## Decision 5 — Network

- TLS everywhere, no ATS exceptions, no cleartext.
- Pinning: protects against user-installed CAs; breaks on cert rotation unless you
  pin a set with a backup. Decide who owns the rotation runbook.
- Certificate rotation and pin expiry must be tested before release, not after.

## Decision 6 — Tamper signals

- Attestation (App Attest / Play Integrity) is a risk signal, not a gate — use it
  to raise friction, not to silently break users.
- Root/jailbreak detection produces false positives; log and step up, do not brick.
- Obfuscation raises cost; it does not protect a secret in the binary.

## Failure modes at scale

- Refresh token in plain preferences, extracted from a backup file.
- Pinning rolled out without a backup pin; one rotation bricks the installed base.
- Deep link that opens an authenticated screen without checking the session.
- Biometric prompt used as the only gate for a payment.
- Logout that leaves the local cache intact on a shared device.

## Verification receipts

1. Secret inventory: what is stored, where, and with which accessibility class.
2. Token lifetime and rotation tested, including refresh-token reuse detection.
3. Deep-link fuzzing: malformed and hostile URLs rejected.
4. Pinning rotation rehearsed with the backup pin.
5. Logout test on a used device: no user data remains in storage or caches.
