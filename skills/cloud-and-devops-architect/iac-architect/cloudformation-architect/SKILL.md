---
name: cloudformation-architect
description: Architect-level native IaC design on CloudFormation or CDK — stack boundaries and blast radius, nested stacks versus CDK constructs, change sets and rollback behaviour, drift detection, and the update failures that leave a stack wedged. Use when infrastructure must live in the provider's own tooling.
license: MIT
compatibility: AWS CloudFormation, CDK, SAM
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/iac-architect/cloudformation-architect
  crusor-origin: original
  crusor-sources: "docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide; docs.aws.amazon.com/cdk/v2/guide; docs.aws.amazon.com/serverless-application-model"
  crusor-triggers: "cloudformation, cdk, sam, change set, stack rollback, nested stack, drift detection, infrastructure as code aws, update stack"
  crusor-verified-on: "2026-10-30"
---

# CloudFormation / CDK Architect

CloudFormation is **the provider's own reconciliation loop**, which means its
failure modes are provider failure modes — and rollbacks are not always possible.

## When to use

- An AWS-only shop wants the native tool with no extra moving parts.
- CDK for typed, reusable infrastructure in TS/Python/Java.
- SAM for serverless-first delivery.

## When NOT to use

- Multi-cloud or multi-provider estates → Terraform/Pulumi.
- Teams already standardised on another tool — consistency wins.

## Decision 1 — Stack boundaries

| Unit | Guidance |
|---|---|
| one stack per lifecycle | deploy together, delete together |
| nested stacks | reuse and isolation, but painful to debug |
| CDK stacks + constructs | preferred reuse mechanism over nesting |
| exports between stacks | minimal; exports cannot be removed while consumed |

- Keep stacks under a few hundred resources: rollback time and blast radius grow
  with size.
- Cross-stack references via exports create hard coupling; prefer SSM parameters
  or explicit config.
- Stateful resources (databases, buckets) in their own stack with deletion
  protection and `Retain` policies.

## Decision 2 — Change safety

- Change sets reviewed before every apply in shared environments.
- Read the replacement column: that is where data loss hides.
- Deletion policy and update-replace-policy set for anything holding data.
- Rollback configuration with CloudWatch alarms; automatic on failure.
- A stack in `UPDATE_ROLLBACK_FAILED` requires a documented recovery (skip
  resources, continue update rollback) — write the runbook before you need it.

## Decision 3 — Drift

- Drift detection scheduled on production stacks; console changes are found in
  hours, not quarters.
- Any drift is either reverted by redeploy or codified — never "leave it, it works".
- Import existing resources (`IMPORT`) rather than recreating them; document the
  import template state.

## Decision 4 — CDK specifics

- Synthesise to review the actual template; a construct can produce surprising
  resources.
- Use L2/L3 constructs for speed, but know what they generate; escape to L1 when
  behaviour must be exact.
- One app, many stacks, with explicit dependencies — CDK orders by reference.
- Pin CDK versions; construct libraries change generated resources between minors.

## Decision 5 — Delivery

- CI runs `cdk diff`/change set creation and posts it to the PR; humans approve the
  diff, not the pipeline log.
- Deploy roles assumed via OIDC, per environment, with least privilege.
- Concurrency: never two deploys of the same stack at once — use a lock or a
  pipeline stage.
- Naming: deterministic names for stateful resources, generated names only for
  replaceable ones.

## Failure modes at scale

- 600-resource stack, one bad resource, rollback takes 40 minutes and fails.
- Export removed while another stack still imports it; both stuck.
- CDK version bumped; a Lambda runtime silently changed and the deploy passed.
- Drift never detected; a hand-edited security group opened a port for a year.
- Destroy on a stack that owns the only copy of production data.

## Verification receipts

1. Stack inventory: owner, lifecycle, data-bearing resources, deletion policies.
2. Change set reviewed for a replace operation, with the data impact stated.
3. Drift detection enabled and one drifted resource resolved.
4. Recovery runbook exercised for a failed update rollback.
5. CDK version pinned and synthesis diff reviewed in CI.
