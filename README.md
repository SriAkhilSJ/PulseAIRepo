# CrusorAI

CrusorAI is a local-first AI coding agent integrated into a vendored Code OSS
desktop fork. The active product surface is a native workbench pane backed by a
Python/LangGraph agent, a versioned JSON-lines bridge, durable sessions, guarded
tools, sub-agents, project preview, and web/native verification pipelines.

> **Repository snapshot — 2026-10-23.** Verified against `main` commit
> `590fe542306ef89547e7909b89da01a9c730e55c`. This describes the source tree;
> it is not a release certification. See
> [Agent Core current state and trusted-shipping MVP](docs/AGENT_CORE_CURRENT_STATE.md)
> for the evidence audit, limitations, and proposed product direction.

## Current status

| Area | Current repository state |
|---|---|
| Desktop UI | Native TypeScript renderer in `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/` |
| Agent transport | Bridge Protocol v2: 33 client methods and 38 server events |
| Agent runtime | Python/LangGraph graph with durable SQLite checkpoints and session metadata |
| Verification | Completion gate plus browser and native target evidence pipelines |
| Current automated CI | Cross-platform host compatibility plus the Agent Core workflow added on this branch |
| Latest `main` CI checked | Host compatibility run `39987746530` passed for `590fe542` |
| Python inventory | 214 non-test source files, 213 `test_*.py` files, 2,576 syntactic test definitions (2,290 top-level + 286 methods) |
| Broad Agent Core lane | `.github/workflows/agent-core.yml`; locally validated before activation: **2,585 passed, 16 skipped** |

Inventory counts are not passed-case counts. The existing host workflow is a
focused cross-platform target contract. The newly activated Agent Core workflow
adds a broad hermetic Linux lane and keeps generated-desktop parity visible but
non-blocking.

On 2026-10-23/Linux/Python 3.11, the host selection passed **78/78**. The
focused evidence/telemetry/permission selection passed **98/98**, or **102/102**
with four new durable-persistence security tests. The exact staged blocking
lane then passed **2,585 tests with 16 skips**. Its separate informational
desktop lane produced **116 passed, 8 skipped, 1 expected failure, and 2
failures** (tracked-output hash drift and a renderer-parity pin); those two are
visible debt, not hidden by the Agent Core result.

### Native-only pane boundary

The old repository-owned `crusor-webview/` application and native CopilotKit
surface were removed in October 2026. `crusorAIViewPane.ts` now mounts the
native renderer directly. Do not use old webview, CopilotKit, or port `3001`
runbooks as the current architecture.

Commit `590fe542` nevertheless restored **541 generated files** under
`desktop/vscode/out/**/media/crusorai-spa/`. There is no matching source SPA
under `desktop/vscode/src/**`, and the native pane does not load that payload.
Treat it as orphaned build-output debt, not as an active UI or a source of
truth. See [the desktop fork notes](desktop/README.md).

## What is implemented

### Agent loop and completion integrity

- Agent, Plan, Debug, and Ask execution modes.
- LangGraph planning, tool execution, compaction, verification, and finalization.
- Named-deliverable checks, post-edit verification invalidation, early-finish
  nudges, tool-call/result pairing, and explicit terminal verdicts.
- Reasoning tokens count toward delivery budgets; incomplete provider tool
  calls are rejected rather than partially executed.
- Durable sessions, forks, checkpoints, cancellation, steering, and queued
  follow-up prompts.

### Tools and safety

- Workspace-contained file reads, writes, edits, copies, search, and code
  navigation.
- Foreground and managed-background terminal execution with streamed output,
  stable process IDs, lifecycle receipts, timeout handling, and cancellation.
- Browser automation, preview, media, web, LSP, MCP, skills, target, and
  artifact tools.
- Pre-mutation shadow checkpoints and per-call safety checks.
- OpenCode-style permission rules (`allow`, `ask`, `deny`) and session-only
  **Allow always** grants for the exact resource shown to the user.
- Approval waits are indefinite until answered or cancelled; there is no
  automatic five-minute denial.

Child clarifying questions can surface through the session tree and route back
to the asking child. The desktop also contains tree-aware approval UI, but the
current core auto-denies approval-requiring child tool calls (unless the unsafe
`CRUSORAI_SUBAGENT_AUTO_APPROVE=1` escape hatch is enabled). Child approvals
are therefore not end-to-end today; see [Permissions](docs/PERMISSIONS.md).

### Sub-agents

- Durable parent/child identity and lineage.
- Foreground and experimental background execution.
- Parallel batch delegation, live child streaming, navigation, sibling links,
  cancellation cascade, and persisted results.
- Built-in and workspace/global custom agents, model override, resume, depth
  limit, and allow/deny spawn policy.

Scoped parent tool binding was tried and reverted (`ff24590b`); the parent
currently receives the full configured tool registry. Do not describe the
reverted tool-waist experiment as shipped behavior.

### Preview and verification

- A token-gated local preview proxy, detached workbench preview window, element
  inspection, annotated feedback, and source-aware edit prompts.
- Deterministic web verification that performs static checks, starts the app,
  probes readiness, inspects the DOM and browser console, captures screenshots,
  and rejects blank or broken output.
- Target detection and build/run/probe receipts for web, Android, iOS, Flutter,
  React Native, Electron, Tauri, and desktop targets, subject to host SDK and
  device availability.
- Completion policy that requires stronger browser/screenshot evidence when
  the task asks for rendered or visual proof and reports unavailable evidence
  instead of inventing a pass.

These are useful building blocks, but they are not yet a unified release gate.
Dependency vulnerability, secret, license/SBOM, mutation/property-testing, and
clean-room reproducibility checks are not integrated into one ship verdict.

### Evidence and observability

- `~/.crusorai/runtime_events.db`: append-only `tool.intent` / `tool.result`
  transactions. Intent commits before invocation; result commits before live
  projection.
- `~/.crusorai/verification.db`: command/edit verification state with stale and
  unverified transitions.
- `~/.crusorai/sessions.db`: durable graph checkpoints and conversations.
- `~/.crusorai/telemetry/calls-YYYY-MM.jsonl`: local model-call cost/token
  ledger and final run verdicts (enabled by default; disable with
  `CRUSORAI_TELEMETRY=off`).
- `diagnostics/` and `~/.crusorai/traces/`: StepTracker traces and reports.
- Optional OpenTelemetry traces to console, a local JSONL file, or an OTLP
  endpoint such as self-hosted Langfuse (`CRUSORAI_OTEL=...`).

Evidence is currently fragmented across these stores. The detailed audit
explains what is durable, what is heuristic, and what must be unified before a
non-developer-facing **safe to ship** claim is credible.

## Architecture

```text
Code OSS native Agent pane
  desktop/vscode/src/vs/workbench/contrib/crusorai/
                    │  Protocol v2 over child-process stdio
                    ▼
Python bridge  ── sessions / replay / cancellation / approvals
  src/bridge/__main__.py
                    │
                    ▼
LangGraph Agent Core
  planner → model → guarded durable tools → verification gate → verdict
                    │
          ┌─────────┼──────────┐
          ▼         ▼          ▼
      workspace   preview   web/native targets
          │         │          │
          └──── evidence, checkpoints, telemetry, optional OTel ────┘
```

The bridge is the production desktop transport. `src/server.py` remains an
optional AG-UI/FastAPI adapter and is not the native pane's runtime path.

## Repository map

```text
src/
  graphs/             Agent graph, routing, completion and verification gates
  runtime/            Journal, session services, tracing, diagnostics, control
  telemetry/          Per-call token/cost ledger and pricing
  context/            Context engine, compaction, verification evidence
  tools/              File, terminal, browser, host, preview, target tools
  targets/            Typed multi-platform plans, runners, probes, receipts
  agents/             Sub-agent coordinator, lifecycle, registry, policies
  bridge/             Protocol v2 and desktop stdio server
  preview/            Token-gated local preview proxy and prompt pipeline
  tests/              Hermetic unit, contract, architecture, and regression tests
desktop/vscode/       Vendored Code OSS fork and native Crusor contribution
preview-lab/           Browser-only preview-flow demonstration
scripts/               Test, diagnostic, benchmark, and verification utilities
ci/                    Staged full Agent Core workflow (not active on GitHub)
docs/                  Current runbooks, plans, audits, and historical evidence
langfuse/              Optional local observability stack
```

## Requirements

- Python 3.11+ for the supported test/runtime path (`.python-version` currently
  records `3.14`).
- [`uv`](https://github.com/astral-sh/uv) for the recommended Python setup.
- A provider key for live model calls; hermetic tests intentionally remove all
  provider credentials.
- Node.js `24.18.0` for the vendored desktop checkout.
- Platform SDKs/devices only for the native targets you intend to verify.

## Set up the Agent Core

```bash
git clone https://github.com/SriAkhilSJ/PulseAIRepo.git
cd PulseAIRepo
uv sync --group dev
cp .env.example .env
```

Configure one provider in `.env`, for example:

```dotenv
LLM_PROVIDER=groq
LLM_MODEL=qwen/qwen3.6-27b
GROQ_API_KEY=...
```

See `.env.example` for context, compaction, sub-agent, telemetry, tracing,
preview, and tool settings. Do not commit `.env` or credentials.

## Test and inspect

Always use the hermetic wrapper rather than bare `pytest`. It unsets provider
keys, creates a fresh home directory, and fixes timezone/locale so local state
cannot create a false pass.

```bash
# Full Agent Core suite
scripts/run_tests.sh

# One file or arbitrary pytest selection
scripts/run_tests.sh src/tests/test_bridge.py -q
scripts/run_tests.sh -k verification

# Cross-platform target doctor (no SDK installation)
python scripts/targets_doctor.py

# Local usage/cost and outcome summary
python -m src.telemetry.call_ledger
```

`.github/workflows/host-compatibility.yml` remains the focused cross-platform
contract. This branch also installs the locally validated broad definition as
`.github/workflows/agent-core.yml`; `ci/agent-core.yml` remains its reviewed
source/template. See [CI status and validation](ci/README.md).

## Build and run the desktop fork

The canonical build and overlay invariants live in
[`desktop/README.md`](desktop/README.md). In summary:

```bash
cd desktop/vscode
npm install
npm run typecheck-client
npm run valid-layers-check
npm run compile
node scripts/emit-crusorai-bundle.mjs
cd ../..

# macOS/Linux source launcher
./crusor.sh /absolute/path/to/a/project

# Windows
crusor.bat C:\absolute\path\to\a\project
```

The desktop starts the stdio bridge and preview proxy as needed; do not start a
separate webview dev server. After changing the Crusor workbench contribution,
recompile, refresh the source manifest/bundle receipts as documented in
`desktop/README.md`, fully quit the desktop app, and reopen it.

## Optional local tracing

```bash
# No backend: spans to the terminal
CRUSORAI_OTEL=console ./crusor.sh /path/to/project

# Local JSONL
CRUSORAI_OTEL=file ./crusor.sh /path/to/project

# Self-hosted Langfuse
cd langfuse && docker compose up -d
# Then set CRUSORAI_OTEL=on and Langfuse keys in .env.
```

Tracing is diagnostic telemetry, not release evidence. Prompt/response content
is excluded from the call-cost ledger. Durable tool/verification writes now
force recursive secret redaction, and persisted tool intents omit source/edit
bodies; stores still retain non-secret paths, commands, and bounded/redacted
results, so use trusted local storage while retention/deletion controls remain
to be implemented.

## Recent mainline changes that affect behavior

- `590fe542` — refreshed tracked Code OSS `out/` artifacts and restored an
  orphaned generated SPA payload.
- `0edce5c3`, `7315b599` — repaired the active host-compatibility workflow.
- `c5bc40f9` — made reasoning consume the delivery cap.
- `794a5555`, `996aa894` — added structured terminal output lifecycle and its
  streamed-pipe regression coverage.
- `ff24590b` — reverted scoped parent tool binding.
- `1ab5671b` through `b8f068f2` — added per-call metering, dynamic pricing,
  request-anatomy measurements, and tool-name telemetry.
- `f4f3a14e`, `7fd8ea61` — removed the native CopilotKit surface and deleted
  the old webview lab.
- October 19–20 fixes tightened final verdict integrity, made SDK installs
  cancellable, and changed approval waits from timeout-deny to wait-until-
  decision-or-cancel.

Use `git log`, not old status documents, for commit-level provenance.

## Documentation

Start with [`docs/README.md`](docs/README.md), which marks current runbooks,
plans, and historical evidence. Important entry points:

- [Agent handoff](AGENT_HANDOFF.md)
- [Agent Core evidence audit and trusted-shipping MVP](docs/AGENT_CORE_CURRENT_STATE.md)
- [Permissions](docs/PERMISSIONS.md)
- [Multi-platform targets](docs/MULTI_PLATFORM_TARGETS.md)
- [Preview setup](CRUSOR_PREVIEW_SETUP.md)
- [Desktop fork](desktop/README.md)
- [CI](ci/README.md)
- [Local Langfuse tracing](langfuse/README.md)

## License

No root license file is currently present. Treat reuse and redistribution terms
as unspecified until the repository owner adds one.
