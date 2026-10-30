---
name: object-storage-architect
description: Architect-level object storage design — bucket and prefix layout, naming and immutability, lifecycle and storage classes, access patterns and presigned URLs, versioning and replication, and the egress and request costs that surprise teams. Use when files, media, backups, or data-lake content live in object storage.
license: MIT
compatibility: S3, GCS, Azure Blob, R2
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/data-services-architect/object-storage-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/AmazonS3/latest/userguide; cloud.google.com/storage/docs; learn.microsoft.com/azure/storage/blobs"
  crusor-triggers: "s3, object storage, bucket, presigned url, lifecycle policy, storage class, glacier, egress cost, gcs, blob storage"
  crusor-verified-on: "2026-10-30"
---

# Object Storage Architect

Object storage is **a namespace with a billing model attached**. The layout decides
what you can delete, replicate, and afford.

## When to use

- User uploads, media, documents, exports.
- Data lake landing zones, backups, logs archive.
- Static site assets and build artefacts.

## When NOT to use

- Anything needing partial update or transactions → a database.
- A filesystem with random writes → block storage or EFS/managed NFS.
- Serving small hot files repeatedly → put a CDN in front.

## Decision 1 — Layout

```
<bucket-per-domain>
  env=<prod>/<dataset>/dt=2026-10-30/part-*.parquet     analytics
  <tenant>/<entity>/<uuid>/<filename>                    user content
  _meta/manifests/, _quarantine/                          pipeline metadata
```

- Prefixes are not directories: listing cost and partition pruning depend on a
  deliberate key layout.
- One bucket per purpose and environment; a shared bucket mixes permissions,
  retention, and billing.
- Never encode mutable state in the key — keys are permanent.
- Content-address (hash) for deduplication of blobs; uuid for user-owned assets.

## Decision 2 — Access

- Block public access by default at the account level; public assets are served
  through a CDN origin, not a public bucket.
- Workload access by role; presigned URLs for user downloads with a short expiry
  and a content-disposition.
- Bucket policies scoped by prefix and principal; deny-by-default elsewhere.
- Encryption at rest (SSE-KMS for sensitive data) and in transit enforced by
  policy.
- Cross-account access by bucket policy + role, never by copying credentials.

## Decision 3 — Durability and versioning

- Versioning on for anything irreplaceable; it also protects against ransomware and
  accidental deletes.
- Object lock for compliance retention; understand that it is irreversible until
  expiry.
- Cross-region replication for DR; define RPO and verify replication lag.
- MFA delete for the buckets that hold the backups of everything else.

## Decision 4 — Lifecycle and class

| Data | Class progression |
|---|---|
| hot user content | standard, no transition |
| warm analytics | standard → infrequent (30 d) → archive (180 d) |
| logs | infrequent (7 d) → expire (90 d) |
| backups | archive after 30 d, expire after retention |

- Lifecycle rules are the cheapest cost control in cloud; write them per bucket at
  creation.
- Incomplete multipart uploads must expire — they are invisible cost.
- Request costs matter at high volume (millions of small GETs); batch and cache.

## Decision 5 — Pipeline interaction

- Landing zone is append-only; downstream jobs read a manifest, not a raw listing.
- Atomic publication: write to a temp prefix, then move/rename via a manifest
  commit.
- Schema and partition layout documented once, enforced by the writer.
- Quality checks on ingest; quarantine prefix for rejects.

## Failure modes at scale

- Public bucket discovered by a scanner; every object world-readable.
- Lifecycle rules absent; five years of logs in standard storage.
- Egress from object storage to the internet cheaper to serve from a CDN, ignored.
- Key layout by uuid only, so listing a tenant's files requires a full scan.
- Versioning off; a bad deploy overwrites the only copy of user uploads.

## Verification receipts

1. Bucket inventory: purpose, public-access block, encryption, versioning, owner.
2. Lifecycle policy per bucket with the expected monthly saving.
3. Access test: presigned URL expires; direct anonymous GET denied.
4. Replication lag measured for DR buckets.
5. Cost report split by storage, requests, and egress.
