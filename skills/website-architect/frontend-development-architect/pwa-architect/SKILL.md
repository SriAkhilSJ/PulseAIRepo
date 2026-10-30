---
name: pwa-architect
description: Architect-level progressive web app guidance — service-worker caching strategies and versioning, offline and stale-while-revalidate behaviour, the update flow users actually see, installability, and the security and debugging traps of a cache you control. Use when a site needs offline support or app-like install.
license: MIT
compatibility: Service Workers, Cache Storage, Workbox or hand-rolled; any framework
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/pwa-architect
  crusor-origin: original
  crusor-sources: "developer.mozilla.org/Service_Worker_API; web.dev/learn/pwa; web.dev/service-worker-caching-and-http-caching"
  crusor-triggers: "pwa, service worker, offline, cache storage, workbox, install prompt, web app manifest, stale-while-revalidate"
  crusor-verified-on: "2026-10-30"
---

# PWA Architect

A service worker is a **programmable proxy you now own**. Every caching decision
becomes a correctness bug when you get it wrong — usually "users see yesterday's
app".

## When to use

- Offline or flaky-network support, app-like installation, background sync.
- Debugging "the site is stale until a hard refresh".
- Adding push notifications.

## When NOT to use

- A marketing site with no offline value — a service worker only adds a stale
  cache failure mode.
- Auth-heavy apps where caching HTML would leak another user's data.

## Decision 1 — Caching strategy per resource

| Resource | Strategy |
|---|---|
| versioned static assets (hash) | cache-first, immutable |
| app shell / HTML | network-first with short cache, or stale-while-revalidate |
| API GET | network-first; cache only explicitly safe endpoints |
| API mutations | never cached; queue with background sync where supported |
| fonts/images | stale-while-revalidate with size cap |

- Never cache authenticated HTML or API responses in a shared cache without
  user scoping.
- Every cached response has an expiry policy; unbounded caches are leaks.

## Decision 2 — Versioning and updates

- Cache names carry a build version; activation deletes old caches.
- The update is a **UX flow**: detect a new worker → show "Update available" →
  activate on demand or on next navigation → never silently strand a running
  session.
- `skipWaiting` + `clientsClaim` only with an explicit reload prompt; otherwise
  mixed versions produce impossible bugs.
- Kill switch: a worker that can be removed remotely (`self.registration.unregister()`)
  when a bad release ships.

## Decision 3 — Offline reality

- Offline is a designed state: an offline page, queued writes, and clear
  indicators of what is pending.
- Reads: last-known data with a timestamp, not a blank screen.
- Writes: outbox with retry, conflict handling on reconnect.
- Navigation fallback serves the app shell, not a browser error.

## Decision 4 — Installability and manifest

- Manifest: name, short_name, icons (192/512 + maskable), `start_url`,
  `display`, theme/background colours.
- Install prompt is earned (after real engagement) and never on first paint.
- iOS support is partial: test add-to-home-screen behaviour explicitly.

## Decision 5 — Security and debugging

- Service workers require HTTPS (localhost excepted); scope is the directory
  they live in.
- Never inject HTML into a cached response without sanitising.
- DevTools: "Bypass for network" and "Update on reload" during development;
  clear storage when switching branches.
- Verify what is actually served: `curl` shows the network, DevTools shows what
  the user gets.

## Failure modes at scale

- Users stuck on an old build for days.
- Cached API responses leaking between users after logout.
- Caching the HTML of a route that changes per user.
- A broken worker shipped with no kill switch — support cannot reproduce.
- Storage quota exceeded silently, offline breaks.

## Verification receipts

1. Strategy table documented per route/asset type.
2. Update test: ship a new build, confirm the prompt and the clean reload.
3. Offline test: cold load with no network on the primary journey.
4. Logout test: no previous user's data served from cache.
5. Cache inventory: names, entries, size, expiry.
