---
name: browser-security-architect
description: Architect-level browser security — CSP and the header baseline, cookie and cross-origin policy, XSS and clickjacking defences, postMessage and third-party script boundaries, and the client-side assumptions that decide whether an XSS becomes a breach. Use when hardening a web frontend or auditing its headers.
license: MIT
compatibility: Modern browsers; any frontend stack
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/security-architect/browser-security-architect
  crusor-origin: original
  crusor-sources: "owasp.org/www-project-secure-headers; developer.mozilla.org/Content_Security_Policy; web.dev/articles/csp"
  crusor-triggers: "csp, content security policy, security headers, cors, cookies, xss, clickjacking, postmessage, same-site"
  crusor-verified-on: "2026-10-30"
---

# Browser Security Architect

The browser is a hostile environment running **your code next to someone else's**.
Headers and origin rules are the only real boundaries it gives you.

## When to use

- Setting headers, CSP, cookies, or CORS for a web app.
- Embedding third-party scripts, iframes, or widgets.
- An XSS or clickjacking finding needs fixing at the architecture level.

## When NOT to use

- Server-side authorization problems — headers do not fix those (see
  `authz-models-architect`).

## Decision 1 — Header baseline

| Header | Value |
|---|---|
| `Content-Security-Policy` | explicit allow-list (below) |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `X-Frame-Options` / `frame-ancestors` | `DENY` unless embedding is required |
| `Permissions-Policy` | disable camera/mic/geolocation you do not use |

- Set at the edge/server config so every response carries them — a header set in
  one framework middleware is a header missing from static assets.

## Decision 2 — CSP that actually helps

- Start restrictive: `default-src 'self'`; add `script-src` with explicit hosts
  and nonces/hashes for inline.
- `'unsafe-inline'` defeats most of the value; if a framework needs it, use
  nonces per response or move to hashes.
- `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`.
- Roll out with `Content-Security-Policy-Report-Only` first, collect violations,
  then enforce.
- Prefer `strict-dynamic` plus nonces over host lists where supported.

## Decision 3 — Cookies and sessions

- `httpOnly` (no JS access), `Secure`, `SameSite=Lax` by default (`Strict` for
  sensitive flows).
- `__Host-` prefix for cookies that must not be domain-shared.
- CSRF defence for cookie-authenticated writes: same-site cookies + origin
  check or a double-submit token.
- Never store tokens in `localStorage` when an httpOnly cookie will do — XSS
  turns into full account takeover otherwise.

## Decision 4 — Cross-origin rules

- CORS: explicit origins, no `*` with credentials, minimal methods/headers, no
  reflected `Origin`.
- `postMessage`: always check `event.origin` against an allow-list, and target a
  specific origin in `postMessage(data, origin)`.
- Iframes: `sandbox` with the minimum tokens; `allow` only what the embed needs.
- Third-party scripts: load from a proxy/subresource integrity where possible;
  `integrity` + `crossorigin` for CDN assets you cannot self-host.

## Decision 5 — Client-side trust

- Anything in the bundle is public: keys, endpoints, feature flags, hidden
  routes.
- Client-side validation is UX; the server re-validates everything.
- Never render untrusted HTML; sanitise with a maintained library if you must
  render markup, and keep the allow-list small.
- DOM APIs: prefer `textContent` over `innerHTML`; avoid `eval`, `new Function`,
  and `javascript:` URLs.

## Failure modes at scale

- CSP present but containing `'unsafe-inline' 'unsafe-eval'` — theatre.
- CORS reflecting any origin with credentials → any site can read user data.
- Session token in `localStorage`, one XSS away from takeover.
- Third-party script with full page access; compromise of the vendor is
  compromise of you.
- Security headers applied to HTML but not to the API responses.

## Verification receipts

1. Header scan on production responses (HTML, API, static) via `curl`/observatory.
2. CSP report-only collection reviewed, then enforce with no violations.
3. Cookie attributes verified in a real browser session (devtools).
4. CORS test from an unlisted origin → rejected, with credentials.
5. XSS test: injected script in an input does not execute anywhere it is echoed.
