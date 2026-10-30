---
name: desktop-offline-storage-architect
description: Architect-level local data design for desktop apps — embedded database choice, file layout and app-data conventions, backup and corruption recovery, large local datasets, sync with a server when one exists, and the long-session durability a desktop app is expected to provide. Use when the app owns data on the user's machine.
license: MIT
compatibility: SQLite, DuckDB, LevelDB, IndexedDB, LMDB, filesystem
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/desktop-offline-storage-architect
  crusor-origin: original
  crusor-sources: "sqlite.org/wal.html; sqlite.org/lang_vacuum.html; developer.apple.com/documentation/foundation/file_system; learn.microsoft.com/windows/apps/design/app-settings"
  crusor-triggers: "local database, sqlite, app data, local storage, offline data, file corruption, backup, data directory, embedded database, local cache, loses data, data loss, crash recovery"
  crusor-verified-on: "2026-10-30"
---

# Desktop Offline Storage Architect

A desktop app owns **durable user data**. The bar is not "it saves" — it is "it
survives a power cut, a full disk, and a corrupted file".

## When to use

- The app stores user documents, history, or state locally.
- Choosing between SQLite, a document store, and plain files.
- Data grows to GBs, or users report lost/corrupt data.

## When NOT to use

- Server-authoritative data with only a small preference cache.
- The issue is the remote schema → `website-architect/database-*`.

## Decision 1 — Store choice

| Store | Use for |
|---|---|
| SQLite (WAL) | relational, queries, transactions, most apps |
| DuckDB | analytical, columnar, local reporting |
| key-value (LevelDB/LMDB) | huge KV sets, caches |
| JSON/JSONL files | settings, small portable configs |
| files on disk | documents, media, exports |

- SQLite is the default answer; it is a bounded, transactional, well-understood
  engine.
- Do not store a database in a network/synced folder (Dropbox/OneDrive) — file
  locking is unreliable there. Sync via the app instead.

## Decision 2 — Layout and conventions

```
app data dir/            (OS-correct per platform)
  db/app.db              transactional state
  files/                 user documents (content-addressed or uuid)
  cache/                 disposable, deletable
  logs/                  rotating, bounded
  backups/               last N snapshots
```

- Cache is always safe to delete; never store anything irreplaceable there.
- Per-user vs per-machine scope is a decision; roaming profiles change the answer.
- Paths derived from the OS API, never hardcoded.
- File names sanitised; user input never becomes a path component.

## Decision 3 — Durability

- WAL mode with a sensible checkpoint interval; `synchronous=NORMAL` is usually
  the right trade, `FULL` for critical writes.
- Transactions wrap multi-step writes; a crash mid-sequence leaves no partial
  state.
- Write-then-rename for atomic file replacement.
- Handle a full disk explicitly: detect, surface, and do not corrupt existing data.
- Flush before reporting success to the UI.

## Decision 4 — Corruption and backup

- Assume the file can be corrupt: run `PRAGMA integrity_check` on startup after an
  unclean shutdown.
- Keep rotating snapshots (on version change, daily, before migrations).
- Recovery path: attempt open → integrity check → restore from latest good backup
  → move the corrupt file aside for support (never delete it).
- Export/import a portable format so users are never trapped.
- Log the recovery event and tell the user what happened.

## Decision 5 — Scale

- Index for the queries the UI actually runs; a full scan on 2 GB is a bug.
- Paginate reads; never load a whole table into memory for a list view.
- Vacuum/compact on a schedule or after large deletes; disk grows otherwise.
- Blobs: filesystem with references in the DB, unless you need transactional
  blobs and the size is small.
- Measure: open time and query time on a production-size dataset.

## Decision 6 — Sync with a server

- The local DB is authoritative for the session; the server is authoritative for
  shared state — decide per entity.
- Sync via the app's API with ids and versions; never by syncing the database file.
- Conflicts resolved per field; deletions as tombstones.
- Offline queue survives restarts and is idempotent on replay.

## Failure modes at scale

- Database inside a Dropbox folder; two machines, one corrupted file.
- No backup before migration; a failed upgrade destroys history.
- Cache directory used for user documents, purged by a cleaner.
- Full disk during save; the app truncates the file and reports success.
- Startup integrity check absent; every user sees a crash loop after a power cut.

## Verification receipts

1. Store choice and layout documented with the OS-correct paths.
2. Crash test: kill mid-write, data intact, WAL recovers.
3. Corruption drill: truncate the DB file, recovery path restores from backup.
4. Full-disk test: write fails cleanly, existing data untouched.
5. Open and query timings on a production-size dataset.
