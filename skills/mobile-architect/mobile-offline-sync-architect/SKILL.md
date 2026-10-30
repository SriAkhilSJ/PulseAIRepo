---
name: mobile-offline-sync-architect
description: Architect-level offline-first design — local database choice, the sync engine and its queue, conflict resolution that matches the domain, idempotency and ordering, partial sync and eviction, and the UX states that make stale data honest. Use when the app must work without a reliable connection.
license: MIT
compatibility: SQLite/GRDB, Room, WatermelonDB, Supabase/Couchbase sync, CloudKit
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/mobile-offline-sync-architect
  crusor-origin: original
  crusor-sources: "developer.android.com/topic/architecture/data-layer/offline-first; developer.apple.com/documentation/coredata; docs.couchbase.com"
  crusor-triggers: "offline first, offline sync, local database, conflict resolution, sync queue, optimistic update, stale data, sync engine, background sync, offline, works offline, sync conflict"
  crusor-verified-on: "2026-10-30"
---

# Mobile Offline-Sync Architect

Offline-first means **the local database is the source of truth for the UI**, and
the network is a synchroniser. Every other design is a cache with extra steps.

## When to use

- Users are on trains, in basements, in factories, or just have bad signal.
- Edits must survive a lost connection.
- The same record is edited on two devices.

## When NOT to use

- Data is inherently server-authoritative and live (live pricing, seat maps) —
  cache with explicit staleness instead of pretending to be offline-first.
- There is one writer and no offline need.

## Decision 1 — Local store

| Store | Use |
|---|---|
| SQLite (GRDB/Room/SQLDelight) | relational, queries, large sets |
| key-value | settings, small cache, flags |
| document (Realm/Watermelon) | object graphs, fast sync primitives |
| files | media, exports |
| in-memory only | single-session scratch |

- The UI reads **only** from the local store — one data path, no "is it cached or
  fetched" branching in screens.
- Migrations are versioned and tested with real old data.

## Decision 2 — The sync engine

```
local write → outbox (queued op) → push to server → ack → apply server state
                                          ↓
                              conflict? → resolve → re-apply
```

- Every local mutation enqueues an **operation with a client-generated id**, not a
  raw row replacement.
- Push is idempotent: the same op applied twice produces one effect (server keys
  on the client op id).
- Pull is incremental: a server cursor/sync token, not "fetch everything".
- Ordering per entity by local sequence; parallel across entities.
- Backoff with jitter; a permanently failing op is surfaced, not retried forever.

## Decision 3 — Conflict resolution

| Strategy | Use when |
|---|---|
| last-write-wins (server clock) | low-stakes fields, presence, preferences |
| field-level merge | independent fields edited concurrently |
| server authority | prices, inventory, entitlements |
| CRDT / operational transform | collaborative text or lists |
| manual resolution | money, medical, legal records |

- Decide **per field**, not per app. A generic LWW across the schema loses edits
  silently and cannot be debugged later.
- Conflicts are visible in the data model (versions / updated_at / server seq) or
  they cannot be resolved at all.

## Decision 4 — Deletes and identity

- Use tombstones; a missing row is not a delete signal in an offline world.
- Client ids (UUIDs) minted locally so records exist before the server knows.
- Soft delete with a retention window; hard delete only after every device syncs
  or after a stated period.

## Decision 5 — Scope, eviction and honesty

- Store what the user needs offline, not the whole database: recent + pinned +
  pending-change items.
- Evict with a policy that never deletes unsynced work.
- Media: cache with size caps and explicit "download for offline" controls.
- UI must show sync state: pending, synced, failed, stale. Silent staleness is a
  trust failure.
- Background sync windows are OS-controlled — design for "maybe", not "every 15
  minutes".

## Failure modes at scale

- Two devices, last-write-wins, one user's morning work vanished.
- Outbox without idempotency: a retried push creates duplicate records.
- Delete synced before the edit that referenced it.
- Local database grows unbounded until the app is uninstallable.
- Screens that fetch on open and show a spinner while the local copy sits unused.

## Verification receipts

1. Airplane-mode test: full edit → kill app → reconnect → one correct record.
2. Duplicate-push test: same op sent twice → server state unchanged.
3. Conflict test: two devices edit the same record, the chosen rule applies and is
   visible in the UI.
4. Eviction test: unsynced items survive a cache purge.
5. Sync-state UI verified for pending, failed and stale paths.
