---
name: mobile-deep-linking-architect
description: Architect-level deep linking — universal links and app links versus custom schemes, association files and verification, deferred deep links, routing into authenticated state, and the failure behaviour when a link lands on the wrong screen or a cold start. Use when links must open the app correctly.
license: MIT
compatibility: Universal Links, Android App Links, Branch/Firebase Dynamic Links
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/devices-architect/mobile-deep-linking-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/xcode/allowing-apps-and-websites-to-link-to-your-content; developer.android.com/training/app-links; developer.apple.com/documentation/xcode/supporting-associated-domains"
  crusor-triggers: "deep link, universal link, app link, associated domains, deferred deep link, url routing, custom scheme, app links verification"
  crusor-verified-on: "2026-10-30"
---

# Deep Linking Architect

A link is **an entry point into arbitrary app state** — including not-signed-in,
wrong-account, and deleted-content states. The architecture is the routing contract,
not the URL.

## When to use

- Marketing links, emails, push notifications, and QR codes open the app.
- Sharing content between users.
- Cross-app handoffs and OAuth redirects.

## When NOT to use

- In-app navigation only — that is the navigation stack's job.

## Decision 1 — Link type

| Type | Behaviour |
|---|---|
| universal link / app link | https, verified, falls back to web |
| custom scheme (`myapp://`) | no verification, works from anywhere, spoofable |
| deferred deep link | install → first launch → route |

- Prefer https universal/app links: verified, shareable, and they degrade to the web.
- Custom schemes are for internal handoffs; never for anything privileged.
- Deferred links require a matching strategy (fingerprint or a token in a landing page)
  and are best-effort.

## Decision 2 — Verification

- Apple: `apple-app-site-association` at the domain root, correct content type, paths
  scoped narrowly.
- Android: `assetlinks.json` with the signing certificate SHA-256; debug and release
  variants differ.
- Changes propagate slowly and caching bites; test on a device that has never opened
  the app.
- Keep the web fallback real — the link must work in a browser.

## Decision 3 — Routing

```
URL → parse → validate → auth check → resolve target → present
```

- One router owns URL → destination mapping; screens never parse URLs.
- Unknown or malformed paths go to a safe home screen, never a crash.
- Unauthenticated: route to login with a return intent, then resume. Do not drop the
  deep link.
- Cold start vs warm start behave differently — both paths get the same handling.
- Handle in-app links (from notifications) through the same router.

## Decision 4 — Safety

- Validate every parameter: ids, paths, redirect targets. A deep link is untrusted
  input.
- Never allow an open redirect or execution of an action (delete, pay) from a link
  alone — require confirmation.
- Account context: a link from user A must not open a record in user B's session.
- Rate-limit and log suspicious patterns.

## Decision 5 — Observability

- Log link open → route resolved → screen shown, with source (email, push, web).
- Track conversion per campaign; a broken association file is invisible otherwise.
- Alert on route-resolution failures spiking after a release.

## Failure modes at scale

- Association file with a wildcard path; every URL opens the app.
- Android assetlinks missing release certificate; links open the browser in production.
- Deep link lost during login; the user lands on home.
- Link to a deleted item crashes on parse.
- Custom scheme hijacked by another app.

## Verification receipts

1. Link inventory: type, domain, path patterns, destination.
2. Association files validated for both platforms with release certificates.
3. Cold-start test from a link while signed out.
4. Malformed and hostile link tests handled safely.
5. Conversion metrics per source for one campaign.
