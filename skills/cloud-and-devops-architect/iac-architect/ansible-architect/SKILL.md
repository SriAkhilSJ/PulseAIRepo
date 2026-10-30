---
name: ansible-architect
description: Architect-level configuration management — inventory and grouping, idempotent roles, variable precedence discipline, secrets via Vault, and the boundary between provisioning (Terraform) and configuring (Ansible), including when to replace Ansible with an immutable image. Use when servers must be configured rather than just created.
license: MIT
compatibility: Ansible; comparable to Salt/Chef/Puppet
metadata:
  crusor-domain: cloud-and-devops-architect
  crusor-path: cloud-and-devops-architect/iac-architect/ansible-architect
  crusor-origin: original
  crusor-sources: "docs.ansible.com/ansible/latest; docs.ansible.com/ansible/latest/playbook_guide; ansible-lint.readthedocs.io"
  crusor-triggers: "ansible, playbook, inventory, configuration management, role, ansible vault, idempotent, provisioning servers, ansible lint"
  crusor-verified-on: "2026-10-30"
---

# Ansible Architect

Ansible configures **machines that already exist**. Used as a provisioning tool it
duplicates Terraform badly; used as a config tool it needs the same discipline as
code.

## When to use

- Long-lived VMs or bare metal that must be configured in place.
- Network devices, appliances, and systems without an API-first tool.
- Bootstrap steps a golden image cannot express.

## When NOT to use

- Creating cloud resources → `terraform-architect` / `pulumi-architect`.
- Immutable container workloads — bake an image instead.

## Decision 1 — Scope boundary

| Concern | Owner |
|---|---|
| VPCs, instances, buckets, IAM | Terraform/Pulumi/CFN |
| OS packages, config files, services | Ansible |
| Application deployment | CI/CD pipeline or orchestrator |
| Cluster workloads | Kubernetes manifests/GitOps |

- Do not create instances in Ansible and then manage them in Terraform; pick one
  owner per resource.
- Ansible's dynamic inventory reading cloud tags is the clean bridge.

## Decision 2 — Structure

```
inventories/<env>/{hosts.yml,group_vars/,host_vars/}
roles/<name>/{tasks,handlers,templates,defaults,vars,meta}
playbooks/<site>.yml
```

- Roles are the unit of reuse: one purpose, documented inputs in `defaults`.
- Variables: `defaults` < `group_vars` < `host_vars` < `-e`. Anything overridden
  with `-e` in production is a design smell.
- Prefix role variables with the role name to avoid collisions.
- Inventory from cloud tags, not a hand-maintained file.

## Decision 3 — Idempotency

- Every task is idempotent: `state: present`, `creates:`, `changed_when`,
  `failed_when` set deliberately.
- No `shell`/`command` without a guard; prefer modules.
- Handlers for restarts, notified, not restarted inline on every run.
- A second run on an unchanged host reports zero changes — that is the test.
- `check` mode in CI for drift detection on critical hosts.

## Decision 4 — Secrets

- `ansible-vault` with a key from a secret manager or CI, never committed.
- No secrets in `group_vars` plaintext or in `-e` on a shared terminal.
- Credentials fetched at runtime (facts from cloud APIs) where possible.
- Vault password rotation documented; a lost key locks every encrypted variable.

## Decision 5 — Safety at scale

- Serial and max_fail_percentage for rolling changes; never blast a whole fleet.
- `--limit` in production; the default should be a small batch, not "all".
- Backups before destructive changes (config file, database schema).
- Logging: the run output is an audit record — store it.
- Test roles in a container or ephemeral VM before touching a fleet.

## Decision 6 — When to stop using Ansible

- If the host is rebuilt often, bake an image and delete the config role.
- If Kubernetes runs the workload, use GitOps instead.
- Remaining Ansible should be a small, auditable set of bootstrap and legacy roles.

## Failure modes at scale

- 800-host inventory, one playbook, one typo, whole fleet down.
- Non-idempotent shell tasks that append to a config file on every run.
- Vault key in the repo "encrypted", with the key file next to it.
- Ansible and Terraform both managing the same instances.
- Roles with 40 variables, half unused, nobody knows which are required.

## Verification receipts

1. Boundary document: which tool owns which resource class.
2. Idempotency test: second run reports zero changes.
3. Vault key handling documented and verified in CI.
4. Rolling deploy demonstrated with serial limits on a real fleet.
5. Role lint and test results from CI.
