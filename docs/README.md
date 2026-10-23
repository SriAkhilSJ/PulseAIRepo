# Documentation index and currency policy

> **Status:** canonical documentation map  
> **Last reviewed:** 2026-10-23  
> **Verified against:** `main` at
> `590fe542306ef89547e7909b89da01a9c730e55c`

The repository contains current runbooks, future plans, dated audits, benchmark
reports, and field evidence. They answer different questions. This index marks
which documents may be used as the current product description and how older
evidence should be maintained.

## Start here

| Document | Authority | Use it for |
|---|---|---|
| [`../README.md`](../README.md) | **Current / canonical** | Product boundary, setup, active architecture, current CI/test scope |
| [`../AGENT_HANDOFF.md`](../AGENT_HANDOFF.md) | **Current / canonical** | Engineering onboarding, invariants, known gaps, validation commands |
| [`AGENT_CORE_CURRENT_STATE.md`](AGENT_CORE_CURRENT_STATE.md) | **Current analysis** | Evidence/monitoring capability audit and trusted-shipping MVP design |
| [`../desktop/README.md`](../desktop/README.md) | **Current / canonical** | Vendored Code OSS build and overlay invariants |
| [`../ci/README.md`](../ci/README.md) | **Current / canonical** | What CI is active, what is only staged, and how to install it |
| [`PERMISSIONS.md`](PERMISSIONS.md) | **Current behavior** | Permission rules, approval semantics, child limitation |
| [`MULTI_PLATFORM_TARGETS.md`](MULTI_PLATFORM_TARGETS.md) | **Current subsystem guide** | Target detection, plans, runners, receipts, host constraints |
| [`../CRUSOR_PREVIEW_SETUP.md`](../CRUSOR_PREVIEW_SETUP.md) | **Current subsystem runbook** | Preview proxy and desktop preview setup |
| [`../CRUSOR_PREVIEW_LAUNCH_CHECKS.md`](../CRUSOR_PREVIEW_LAUNCH_CHECKS.md) | **Current checklist** | Preview launch validation |

If one of these disagrees with source or tests, source plus reproducible evidence
wins and the document should be corrected in the same change.

## Current implementation guides

These describe live subsystems, but still check their header date/commit before
using exact counts or claiming a behavior is release-proven.

- [`CRUSORAI_IDE_CONTRIB_ARCHITECTURE.md`](CRUSORAI_IDE_CONTRIB_ARCHITECTURE.md)
- [`CRUSOR_SKILLS_HUB.md`](CRUSOR_SKILLS_HUB.md)
- [`LAPTOP_VERIFICATION_PACK.md`](LAPTOP_VERIFICATION_PACK.md)
- [`OUTPUT_LIMIT_RECOVERY_REPAIR.md`](OUTPUT_LIMIT_RECOVERY_REPAIR.md)
- [`CONTEXT_ENGINE_EXPLAINED_NON_TECHNICAL.md`](CONTEXT_ENGINE_EXPLAINED_NON_TECHNICAL.md)
- [`DESIGN/`](DESIGN/) — design-specific source audits and parity notes; each
  document's snapshot date controls.

`LAPTOP_VERIFICATION_PACK.md` is a manual field checklist, not proof that its
steps were run against the current commit.

## Plans and proposals — not shipped by implication

A plan can describe excellent intended behavior and still have no runtime
caller, UI, or required check. The following are design inputs, not current
feature claims:

- [`AGENT_RELIABILITY_PLAN.md`](AGENT_RELIABILITY_PLAN.md)
- [`CRUSORAI_AGENTOPS_PLAN.md`](CRUSORAI_AGENTOPS_PLAN.md)
- [`CRUSOR_AGENT_STRENGTHENING_PLAN.md`](CRUSOR_AGENT_STRENGTHENING_PLAN.md)
- [`CRUSORAI_IMPROVEMENT_SCOPE.md`](CRUSORAI_IMPROVEMENT_SCOPE.md)
- [`CRUSORAI_UI_IMPLEMENTATION_PLAN.md`](CRUSORAI_UI_IMPLEMENTATION_PLAN.md)
- [`CRUSOR_SUBAGENT_FULL_PIPELINE_PLAN.md`](CRUSOR_SUBAGENT_FULL_PIPELINE_PLAN.md)
- `PLAN-*.md`, `TASK-*.md`, and context-engine `P*` workstream documents
- [`P2-roadmap.md`](P2-roadmap.md) and related `P2-*` analyses

Use explicit status words in plans:

- **proposed** — no implementation evidence;
- **implemented** — source path exists;
- **tested** — named test/command proves it;
- **field-verified** — dated run receipt proves it in the target environment;
- **required** — an active blocking CI/release policy enforces it.

Do not collapse those words into “done.”

## Historical audits and evidence

These preserve why decisions were made and what a particular run observed.
Their original claims should not be silently rewritten to match current code.
Add a short supersession banner when a reader could mistake them for current
status.

- [`../bench-results/`](../bench-results/) and
  [`../diagnostics/`](../diagnostics/) — dated run receipts, reports, and
  benchmark artifacts; inspect each artifact's commit/environment.
- [`HARNESS_STATUS.md`](HARNESS_STATUS.md) — historical harness snapshot.
- [`AGENT_CORE_AUDIT_FIXES.md`](AGENT_CORE_AUDIT_FIXES.md) — audit/fix snapshot.
- [`HERMES_RUNTIME_AUDIT.md`](HERMES_RUNTIME_AUDIT.md) and
  [`hermes-extraction-report.md`](hermes-extraction-report.md).
- [`OPENCODE_DESKTOP_SUBAGENT_UI.md`](OPENCODE_DESKTOP_SUBAGENT_UI.md) and
  [`OPENCODE_SUBAGENT_PIPELINE.md`](OPENCODE_SUBAGENT_PIPELINE.md) — upstream
  2026-09 reference snapshots, not current Crusor status.
- `TEST4_*`, `TEST5_*`, `ATTEMPT11_*`, `CTO_BENCHMARK_*`, and
  `CRUSOR_VS_HERMES_*` — attempt-specific results.
- [`BRANCH_AUDIT_arena_01a02a5c.md`](BRANCH_AUDIT_arena_01a02a5c.md),
  [`RENOVATION_2026-08-29.md`](RENOVATION_2026-08-29.md), and
  [`SESSION_LOG_2026-08-28.md`](SESSION_LOG_2026-08-28.md).
- [`DESKTOP_AGENT_VERIFICATION.md`](DESKTOP_AGENT_VERIFICATION.md) and
  [`DESKTOP_MANAGER_REGISTRATION_VERIFY.md`](DESKTOP_MANAGER_REGISTRATION_VERIFY.md)
  — branch-era desktop instructions with old paths/counts.
- Root reviews such as [`../AGENT_STARTUP_REVIEW.md`](../AGENT_STARTUP_REVIEW.md),
  [`../ARCHITECTURE_REVIEW.md`](../ARCHITECTURE_REVIEW.md), and
  [`../bridge_status.md`](../bridge_status.md).

A historical pass count proves only the named command, tree, environment, and
date. It is not a standing repository-health claim.

## Currency rules

### 1. Current-state headers

A canonical/current document should begin with:

```text
Status: current | current subsystem | proposed | historical snapshot
Last reviewed: YYYY-MM-DD
Verified against: full commit SHA (or “not reverified”)
```

If exact runtime evidence matters, also name the command/run ID and host.

### 2. Preserve historical evidence

Do not edit an old field report so it appears to have predicted the present.
Instead:

1. retain the original result;
2. add a banner naming what superseded it;
3. link to a current canonical document;
4. put new measurements in a new dated artifact.

### 3. Separate source, generated output, tests, and runtime proof

A feature claim should identify its evidence class:

- **source:** code path exists;
- **generated output:** compiled artifact exists, but may be orphaned/stale;
- **test:** behavior is exercised under a named harness;
- **CI:** active workflow ran and blocked/passed;
- **field:** real provider, app, device, or desktop run was observed.

Generated files alone do not prove an active feature. The current
`desktop/vscode/out/**/media/crusorai-spa/` payload is the concrete warning: 541
tracked outputs exist with no matching source SPA and no active pane loader.

### 4. Never publish ambiguous test counts

State whether a number means files, collected test functions, selected cases,
or passed cases. A pass claim must include:

- command or workflow;
- commit;
- date;
- operating system/runtime;
- exclusions and expected failures.

Current static inventory after the follow-up is 214 non-test Python files, 213
`test_*.py` files, and 2,576 syntactic `test_*` definitions (2,290 at module
level plus 286 methods). Those are inventory figures, not collected
or passed-case results. The 2026-10-23 audit's Linux/Python 3.11 runs were
78/78 for the host selection. After repairing two stale contracts, the focused
evidence selection is 98/98, or 102/102 with four new durable
persistence-security tests. The activated broad Agent Core lane also passed
2,585 tests with 16 skips locally; see the root README for exact exclusions and
the separate desktop-parity result.

### 5. Link checking

For changed Markdown, validate local links from the repository root. A minimal
check is:

```bash
python - <<'PY'
from pathlib import Path
import re, subprocess
names = subprocess.check_output(
    ['git', 'diff', '--name-only', '--', '*.md'], text=True
).splitlines()
names += subprocess.check_output(
    ['git', 'ls-files', '--others', '--exclude-standard', '--', '*.md'], text=True
).splitlines()
bad = []
for doc in {Path(name) for name in names}:
    text = doc.read_text(encoding='utf-8', errors='replace')
    for raw in re.findall(r'(?<!!)\[[^]]*\]\(([^)]+)\)', text):
        target = raw.split('#', 1)[0].strip()
        if not target or '://' in target or target.startswith(('mailto:', '#')):
            continue
        path = (doc.parent / target).resolve()
        if not path.exists():
            bad.append(f'{doc}: {raw}')
if bad:
    raise SystemExit('\n'.join(bad))
print('changed Markdown local links: OK')
PY
```

This checks file targets, not anchor spelling.

### 6. Review triggers

Update the canonical docs in the same change when any of these move:

- active UI or transport boundary;
- protocol method/event inventory;
- permission or approval behavior;
- final-verdict/verification policy;
- test or CI scope;
- source/generated-output contract;
- setup command, runtime requirement, or provider configuration;
- user-visible release/readiness claim.

## Current known documentation traps

- **Copilot vs CopilotKit:** upstream Code OSS Copilot sources are retained as a
  reference; Crusor's deleted CopilotKit/webview surface is a different thing.
- **Approval timeout:** current approval waits do not auto-deny after 300s.
- **Child HITL:** clarifying questions are routed end-to-end; child tool
  approvals are not, despite tree-aware desktop plumbing.
- **Tool waist:** scoped parent binding was reverted.
- **CI:** a YAML file under `ci/` is not an active GitHub workflow.
- **Telemetry:** traces and cost ledgers monitor work; they do not certify a
  release.
- **“Verified”:** a passing command can become stale after an edit and may not
  cover a rendered UI, deployment, security, or user journey.
