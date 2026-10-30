---
name: backup-and-dr-architect
description: Architect-level backup and disaster recovery — RPO and RTO stated per dataset, backup tiers and immutability, cross-region and cross-account copies, restore drills that measure real recovery time, and the runbook that turns a disaster into a procedure. Use when data loss or region loss must be survivable.
license: MIT
compatibility: Any cloud; snapshots, object versioning, PITR, vaults
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/operations-architect/backup-and-dr-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws; cloud.google.com/architecture/dr-scenarios; learn.microsoft.com/azure/architecture/framework/resiliency"
  crusor-triggers: "backup, disaster recovery, rpo, rto, restore drill, snapshot, cross region, immutable backup, failover region, data loss"
  crusor-verified-on: "2026-10-30"
---

# Backup & DR Architect

DR is **two numbers and a rehearsal**: how much data you can lose (RPO), how long
you can be down (RTO). Everything else is tooling in service of those numbers.

## When to use

- Designing backups for a new data store.
- A compliance requirement names retention or recovery.
- Preparing for region-level failure or ransomware.

## When NOT to use

- Ephemeral data that can be regenerated cheaply — say so explicitly instead.
- The real issue is a bug deleting rows; that is also a backup concern, but the fix
  is code.

## Decision 1 — State the numbers

| Dataset | RPO | RTO | Method |
|---|---|---|---|
| transactional DB | 5 min | 1 h | PITR + cross-region replica |
| object storage | 0 | 4 h | versioning + CRR |
| analytics warehouse | 24 h | 8 h | daily snapshot + rebuild |
| logs/audit | 1 h | 24 h | archive, immutable |

- RPO/RTO per dataset, agreed with the business, written in the design doc.
- RTO includes DNS, credentials, and verification — not just data restore.
- Anything without a stated number has an implicit number of "forever".

## Decision 2 — Backup design

- Automated, scheduled, monitored — a backup job that fails silently is worse than
  none.
- Immutable/copies in a separate account or region; ransomware deletes what it can
  reach.
- Encryption at rest with keys in a different account where possible.
- Retention: daily × 30, weekly × 12, monthly × 7 — or whatever the policy says,
  enforced by lifecycle rules.
- Verify integrity as part of the job, not only at restore time.

## Decision 3 — DR strategies

| Strategy | RTO | Cost |
|---|---|---|
| backup and restore | hours | lowest |
| pilot light (data replicated, infra off) | 1–2 h | low |
| warm standby (scaled-down running) | minutes | medium |
| active-active multi-region | seconds | highest |

- Choose by the stated RTO, not by ambition.
- Active-active requires conflict-free writes or a partitioning strategy — a much
  bigger commitment than "deploy to two regions".
- Region failover needs DNS strategy, credential replication, and a runbook.

## Decision 4 — Restore drills

- Restore on a schedule into an isolated environment; measure the time end to end.
- Validate data: row counts, checksums, application-level smoke tests.
- Drill the *whole* procedure: credentials, DNS, config, and traffic switch.
- Record time per stage; the bottleneck is usually not the database.
- Keep the drill artefacts; auditors and post-incidents will ask.

## Decision 5 — Runbook

- One page per scenario: region loss, data corruption, accidental deletion,
  ransomware.
- Steps with commands, owners, and decision points; no paragraphs of theory.
- Communication plan: who is told, when, and by whom.
- Exit criteria and post-recovery validation.

## Failure modes at scale

- Backups in the same account and region as production; one compromise loses both.
- Restore never attempted; the backup format changed two versions ago.
- RTO claimed at one hour, actual restore takes six.
- PITR window shorter than the detection time of corruption.
- Runbook exists but names people who left.

## Verification receipts

1. RPO/RTO table per dataset with business sign-off.
2. Restore drill executed with measured time per stage.
3. Backup failure alert wired and tested.
4. Cross-account/region copy verified, immutability confirmed.
5. Runbook executed by someone who did not write it.
