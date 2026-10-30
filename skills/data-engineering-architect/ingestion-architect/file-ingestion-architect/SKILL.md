---
name: file-ingestion-architect
description: Architect-level file and batch transfer ingestion — SFTP and object-drop patterns, manifests and idempotent arrival detection, encoding and delimiter reality, validation before load, and the operational contract with partners who send files on their schedule. Use when data arrives as files rather than API calls or streams.
license: MIT
compatibility: S3/GCS drops, SFTP, managed transfer services, Kafka-less batch
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/ingestion-architect/file-ingestion-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/transfer/latest/userguide; cloud.google.com/storage-transfer/docs; csvkit.readthedocs.io"
  crusor-triggers: "file ingestion, sftp, csv ingestion, manifest, batch file exchange, partner feed, drop folder, fixed width, encoding"
  crusor-verified-on: "2026-10-30"
---

# File Ingestion Architect

Files arrive **late, partial, duplicated, and with the wrong encoding**. The design
problem is knowing which arrival is real.

## When to use

- Partners or legacy systems exchange CSV/XML/EDI files.
- Batch drops into object storage drive daily processing.
- SFTP is the only integration the other side supports.

## When NOT to use

- The source offers an API with incremental sync — prefer it.
- Real-time requirements exceed what a scheduled drop can satisfy.

## Decision 1 — Arrival detection

| Signal | Reliability |
|---|---|
| manifest file after the drop | best — declares the batch |
| `_SUCCESS` marker | good, if the sender writes it |
| filename convention with a timestamp | medium |
| file count + size heuristic | weak |
| "process any new file" | fragile — partial uploads look new |

- Require a completion signal or a manifest; processing on first sight of a file is
  how half-uploaded CSVs get loaded.
- Idempotency by content hash + filename; a re-sent file must not duplicate rows.
- Quarantine unexpected files rather than silently ignoring them.

## Decision 2 — Transfer

- SFTP with key-based auth, host key verification, and a dedicated per-partner path.
- Object storage drops with least-privilege bucket policies per partner.
- Retries on transfer failure; checksum verification for large files.
- Delete or archive source files only after a successful load and verification.

## Decision 3 — Parsing reality

| Problem | Handling |
|---|---|
| encoding (latin-1, UTF-16, BOM) | detect, do not assume UTF-8 |
| delimiters inside quoted fields | real CSV parser, never `split(",")` |
| header variations | map by name with an explicit alias table |
| trailing empty lines, CRLF | normalise before type inference |
| fixed-width legacy | column spec versioned with the file |
| Excel exports with formulas/merged cells | convert server-side, validate |

## Decision 4 — Validation before load

- Schema expectations: required columns, types, allowed values.
- Row-level rejects go to a quarantine table with the reason; the batch continues.
- Batch-level gates: row count within an expected band, totals reconciling with a
  partner-provided control record.
- Never partially publish a batch to consumers; publish only after full validation.

## Decision 5 — Contract with the sender

- Written expectations: filename pattern, schedule, encoding, manifest, control
  totals, contact for failures.
- Freshness SLA per feed; alert when a batch is missing, not only when it fails.
- Versioning: a new file layout is announced and versioned, not discovered.
- Escalation path for the partner when no file arrives.

## Failure modes at scale

- Partial upload processed; half a day's transactions loaded and published.
- Encoding assumed UTF-8; customer names with accents corrupted permanently.
- Re-sent file double-loads a day of revenue.
- Silent feed failure for three days; dashboards show stale numbers as flat lines.
- Partner changes column order; the positional parser writes garbage into the wrong
  columns.

## Verification receipts

1. Arrival-detection mechanism documented per feed.
2. Idempotency test: same file processed twice, no duplicate rows.
3. Encoding and delimiter test with a deliberately messy file.
4. Reconciliation against control totals, executed for one real batch.
5. Missing-feed alert configured and tested.
