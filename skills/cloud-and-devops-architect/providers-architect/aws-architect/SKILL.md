---
name: aws-architect
description: Architect-level AWS guidance — account and VPC topology, IAM and workload identity, compute and data service selection, queue and event patterns, and the quotas and billing behaviours that break systems at scale. Use when designing on AWS.
license: MIT
compatibility: AWS; any IaC toolchain
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/providers-architect/aws-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com; aws.amazon.com/architecture/well-architected"
  crusor-triggers: "aws, amazon web services, ec2, s3, lambda, iam, vpc, rds, sqs, cloudfront"
  crusor-verified-on: "2026-10-30"
---

# AWS Architect

AWS is **a very large set of primitives with sharp edges at the quota and
pricing level**. Architecture is picking few of them and knowing their limits.

## When to use

- Designing or reviewing an AWS estate.
- Choosing between EC2, ECS, EKS, Lambda or Fargate.
- Diagnosing throttling, cost spikes, or IAM surprises.

## When NOT to use

- Multi-cloud abstractions that hide provider behaviour you depend on.

## Decision 1 — Accounts and network

- AWS Organizations: one account per environment and per blast-radius group;
  production isolated.
- VPC per environment; public subnets only for ALB/NAT; data in private
  subnets.
- VPC endpoints (S3, DynamoDB, ECR, CloudWatch) to avoid NAT data charges.
- One CIDR plan for the whole org; overlapping ranges make peering impossible
  later.

## Decision 2 — Identity

- IAM roles everywhere: instance profiles, IRSA/pod identity, OIDC for CI.
- No long-lived access keys; if a key must exist, it is rotated and monitored.
- Permission boundaries and SCPs for guardrails; least privilege per role.
- Human access through SSO with MFA; break-glass is audited.

## Decision 3 — Compute choice

| Workload | Service |
|---|---|
| small services, containers | ECS Fargate |
| complex, multi-team container platform | EKS (accept the operational cost) |
| event-driven, bursty, short | Lambda |
| steady high CPU, special hardware | EC2 with ASG |
| batch | AWS Batch |

- Serverless has limits: 15-minute runtime, cold starts, concurrency quotas,
  connection pooling problems with relational DBs.
- Containers need someone to own the cluster; EKS is not free operationally.

## Decision 4 — Data and messaging

- RDS/Aurora for relational; multi-AZ on; automated backups with PITR; restore
  tested.
- S3: versioning, lifecycle rules, block public access at account level.
- SQS for buffering and retries (with DLQ), SNS/EventBridge for fan-out;
  understand at-least-once and make consumers idempotent.
- DynamoDB: design access patterns first; hot partitions come from low-cardinality
  keys.

## Decision 5 — Edge and delivery

- CloudFront in front of everything public; cache policy per content type.
- WAF managed rules plus rate limits; Shield for the obvious.
- Route 53 health checks only if you actually fail over.

## Decision 6 — Quotas, limits, cost

- Know the quotas that bite: Lambda concurrency, API Gateway throttle, EBS IOPS,
  NAT throughput, SES sending.
- Request quota increases **before** launch, not during an incident.
- Cost drivers: NAT gateway data, cross-AZ traffic, idle RDS, unattached EBS,
  log ingestion, egress.

## Failure modes at scale

- Everything in one account, staging credentials able to touch production.
- Lambda inside a VPC without NAT or endpoints → timeouts everywhere.
- SQS consumers not idempotent, so retries duplicate work.
- RDS without PITR, discovered when the restore is needed.
- NAT data charges exceeding compute spend.

## Verification receipts

1. Account/VPC diagram with subnets, endpoints and egress paths.
2. IAM credential report: zero long-lived keys; roles mapped per workload.
3. Quota check for the top five services against projected peak.
4. Restore drill from backup with measured RTO.
5. Cost Explorer by service and tag; top three drivers explained.
