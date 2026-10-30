---
name: managed-databases-architect
description: Architect-level managed database selection and operation — choosing between relational, document, key-value, and analytical engines, sizing and IOPS, multi-AZ and read replicas, connection pooling, backup and point-in-time recovery, and the operational limits of the managed tier. Use when a database is a cloud service rather than a server you run.
license: MIT
compatibility: RDS/Aurora, Cloud SQL, Azure SQL, DynamoDB, Cosmos, Firestore
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/data-services-architect/managed-databases-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/AmazonRDS/latest/UserGuide; cloud.google.com/sql/docs; docs.aws.amazon.com/amazondynamodb/latest/developerguide"
  crusor-triggers: "rds, aurora, dynamodb, managed database, read replica, point in time recovery, connection pooling, database sizing, cloud sql, cosmos db"
  crusor-verified-on: "2026-10-30"
---

# Managed Databases Architect

A managed database removes operations, not design. **Schema, access pattern, and
connection discipline are still yours**, and in some ways more consequential
because you cannot tune the box.

## When to use

- Choosing a managed engine for a new service.
- Performance or cost problems on RDS/Aurora/Cloud SQL/DynamoDB.
- Designing backups, replicas, or failover.

## When NOT to use

- Schema modelling detail → web `database-engineering-architect/*`.
- Self-managed clusters on Kubernetes → `kubernetes-architect` (and question the
  choice).

## Decision 1 — Engine

| Need | Engine |
|---|---|
| relational, joins, transactions, known schema | PostgreSQL (often Aurora/Cloud SQL) |
| relational, extreme read scale, storage growth | Aurora/Spanner-class |
| key-value at scale, predictable access by key | DynamoDB/Bigtable |
| document, evolving schema, per-document queries | MongoDB/Cosmos/Firestore |
| analytical OLAP | warehouse, not OLTP engine |

- Managed multi-model engines tempt you into one engine for everything; the
  access-pattern mismatch shows up at scale, not at launch.
- DynamoDB design is access-pattern-first: get the keys wrong and the fix is a
  rewrite, not an index.

## Decision 2 — Sizing

- Size on the working set (fits in memory?) plus IOPS, not on row count.
- Provision IOPS explicitly on gp3-style storage; default burst credits run out
  under sustained load.
- Serverless/on-demand tiers are for spiky, low-duty workloads; sustained load is
  cheaper on provisioned capacity.
- Measure p95 query latency and buffer cache hit ratio; both predict the wall.

## Decision 3 — Availability

- Multi-AZ for anything in the request path; understand the failover time
  (seconds to minutes) and that connections drop.
- Read replicas for read scale and for analytics isolation — not as a backup.
- Failover tested; an untested failover is a guess about the app's retry logic.
- Cross-region replicas for DR with a documented RPO and promotion runbook.

## Decision 4 — Connections

- The app's pool size × instance count must be below the database's max
  connections. This is the single most common cloud outage.
- Use a proxy/pooler (RDS Proxy, PgBouncer, Cloud SQL connector) for
  serverless/bursty workloads.
- Timeouts: connect, statement, idle — all set; a missing one becomes a stuck
  service.
- Long transactions block vacuum and locks; cap and alert on them.

## Decision 5 — Backups

- Automated backups with PITR enabled and retention matching the business.
- Snapshots copied to another region/account; test a restore, not just a backup.
- Know the restore time: a 1 TB database is not a 5-minute operation.
- Logical exports for reporting/portability alongside physical backups.

## Decision 6 — Cost

- Idle multi-AZ instances in dev; schedule them off.
- Storage grows with WAL/backups — set retention explicitly.
- Reserved capacity for steady instances; on-demand for dev.
- The expensive surprise is usually cross-AZ data transfer and replicas nobody
  reads.

## Failure modes at scale

- 500 app connections from 20 Lambdas; database refuses connections under load.
- Failover takes 90 s, app has no retry and no connection refresh.
- Read replica used for writes in a reporting job, silently failing writes.
- PITR off; a bad migration requires restoring a week-old snapshot.
- DynamoDB table with one hot partition key; throttling in production only.

## Verification receipts

1. Engine choice with the access pattern it serves.
2. Connection budget: pool × instances vs max connections, with headroom.
3. Failover drill: connection loss handled, recovery time measured.
4. Restore drill from PITR to a timestamp, verified data intact.
5. Cost breakdown: instance, storage, IOPS, replicas, transfer.
