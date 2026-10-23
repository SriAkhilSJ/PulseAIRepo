# Agent handoff — current repository state

> **Status:** current-state onboarding
> **Last reviewed:** 2026-10-23
> **Verified against:** `main` at
> `590fe542306ef89547e7909b89da01a9c730e55c`
> **Canonical companions:** [README](README.md),
> [documentation index](docs/README.md), and
> [Agent Core evidence/MVP analysis](docs/AGENT_CORE_CURRENT_STATE.md)

This file is the fastest safe route into the repository. Older audits and field
reports remain useful evidence, but their dates are part of their meaning; do
not promote an old claim to current status without checking source and tests.

## 1. Read this before changing anything

1. The active desktop Agent pane is the **native TypeScript renderer** under
   `desktop/vscode/src/vs/workbench/contrib/crusorai/`.
2. The repository-owned `crusor-webview/` was deleted, and the native
   CopilotKit surface was stripped. Do not restore either path by following an
   old runbook.
3. HEAD contains 541 tracked generated files under
   `desktop/vscode/out/**/media/crusorai-spa/`, but no matching source SPA. The
   pane does not load it. It is orphaned build-output debt, not architecture.
4. The bridge is a stdio JSON-lines child process. Ordinary stdout from Python
   would corrupt the protocol, so bridge diagnostics belong on stderr.
5. Host compatibility covers target contracts on three hosts. This branch now
   also installs `.github/workflows/agent-core.yml`: its broad blocking lane
   was validated locally at 2,585 passed/16 skipped before activation; generated
   desktop parity remains a visible, non-blocking lane.
6. Use `scripts/run_tests.sh`, not bare `pytest`, for trustworthy local runs.
7. Never infer that all tests pass from the static inventory (213 test files,
   2,576 syntactic test definitions) or from the focused host-compatibility
   workflow.
8. Local audit evidence at this handoff is 78/78 for host compatibility,
   98/98 for the repaired focused evidence selection (102/102 with the new
   persistence tests), and 2,585 passed/16 skipped for the broad Agent Core
   lane. The separate desktop parity lane is intentionally non-blocking and
   still has two visible failures.

## 2. Current architecture

```text
Code OSS native Agent pane
  CrusorAIViewPane → CrusorAIRendererService → CrusorAIRenderer
          │
          │ Protocol v2 (33 client methods / 38 server events)
          ▼
Python stdio bridge (`python -m src.bridge`)
  workspace binding, sessions, replay, turn control, event projection
          │
          ▼
LangGraph Agent Core (`src/graphs/chat_graph.py`)
  task manager / planner / AI / guarded tools / completion gate / finalizer
          │
          ├── durable session checkpoints and metadata
          ├── durable tool intent/result journal
          ├── persistent verification ledger
          ├── local model-call cost/outcome ledger
          ├── optional OTel traces
          ├── preview proxy and browser proof
          └── typed web/native target runner and receipts
```

`src/server.py` is an optional FastAPI/AG-UI adapter. It is not the desktop
pane's production transport.

### Primary code paths

| Concern | Source of truth |
|---|---|
| Graph and final verdict | `src/graphs/chat_graph.py`, `src/graphs/gates.py` |
| Desktop bridge | `src/bridge/__main__.py`, `src/bridge/protocol_v2.json` |
| Native panel | `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/` |
| Tool durability | `src/runtime/tool_middleware.py`, `src/runtime/event_journal.py` |
| Verification state | `src/context/verification_evidence.py` |
| Web verification | `src/tools/ui_verification.py` |
| Native targets | `src/targets/`, `src/tools/target_tools.py` |
| Sessions | `src/runtime/session_store.py`, LangGraph checkpoints |
| Sub-agents | `src/agents/sub_agent.py`, `subagent_lifecycle.py`, `subagent_registry.py` |
| Usage/cost | `src/telemetry/call_ledger.py`, `src/telemetry/pricing.py` |
| Tracing | `src/runtime/step_tracker.py`, `src/runtime/otel_tracing.py` |
| Preview | `src/preview/`, native `media/crusor-preview/` |

## 3. Latest commit sequence and implications

| Commit | What changed | Handoff implication |
|---|---|---|
| `590fe542` | Updated tracked `desktop/vscode/out` and restored `crusorai-spa` files | Build output is newer, but the SPA has no source counterpart and is not active. `BUILD_INFO.json` names parent `0edce5c3`, the source used for the build. |
| `0edce5c3` | Fixed folded YAML command execution | Latest Host compatibility run (`39987746530`) is green. |
| `7315b599` | Removed deleted scaffold test from CI | Scaffold tools were intentionally removed; terminal workflows replaced them. |
| `c5bc40f9` | Reasoning now counts against reply/delivery caps | Budget analysis must include hidden reasoning, not just visible content. |
| `794a5555`, `996aa894` | Structured terminal lifecycle and streamed-pipe test update | Preserve start/output/end ordering and process IDs across bridge/UI changes. |
| `ff24590b` | Reverted scoped parent tool binding | The tool-waist experiment is not shipped; do not document it as current. |
| `1ab5671b`–`b8f068f2` | Call ledger, pricing, request anatomy, tool-name telemetry | Cost/outcome data exists locally but is not a release-quality evidence model. |
| `f4f3a14e`, `7fd8ea61` | Removed native CopilotKit and deleted the webview lab | Native renderer is the only active Agent pane. |

Other material October behavior now in source:

- Sub-agent identities, lineage, results, and live streams are durable/routable.
- Child **clarifying questions** route through the session tree.
- Session-only permission grants replaced persisted project grants.
- Approval waits remain pending until a decision or cancellation.
- Toolchain installs expose progress and stop promptly on cancellation.
- Failed or unavailable verification cannot stamp a successful final verdict.
- Terminal calls stream output and return structured lifecycle receipts.

### Known sub-agent approval limitation

The UI and bridge can route a synthetic child approval request, but
`SafeToolNode` currently intercepts `thread_id.startswith("sub-")` and denies
any guard-unsafe or permission-config `ask` call before the approval channel.
Setting `CRUSORAI_SUBAGENT_AUTO_APPROVE=1` bypasses checks rather than asking.
Therefore:

- child questions: end-to-end;
- child approvals: UI/transport plumbing exists, core execution does not reach it;
- default child safety behavior: immediate deny.

Do not claim full OpenCode child-approval parity until a real child tool call is
proven request → dock → decision → durable execution.

## 4. Evidence and monitoring reality

The repository has several useful but separate evidence systems:

| Store/surface | What it proves | Important limit |
|---|---|---|
| `runtime_events.db` | Tool intent/result ordering plus versioned verification updates | Forced recursive redaction and omitted source/edit bodies are active; remaining turn/model/approval/policy events still need durable references |
| `verification.db` | Recognized test/build/lint/typecheck command result and edit-driven stale state | Forced command/output redaction is active; recognition remains regex-derived and candidate identity is not yet bound |
| LangGraph/session DB | Conversation/checkpoint state and resumability | Not a release evidence ledger |
| Completion gate | Required artifact and static/browser/native evidence before a success verdict | Reconstructs some facts from messages and textual receipt formats |
| Target/web receipts | Build/run/probe/assert/screenshot/crash evidence | Not unified with security, dependency, or clean-room checks |
| Call ledger | Per-model tokens, latency, cost, request anatomy, run verdict | Local JSONL; metering rather than correctness proof |
| StepTracker | Human-readable local timing/tool diagnostics | `ai` records proposed tools and `tools` records outcomes; naive aggregation can double-count |
| OTel | Turn/node/LLM/tool spans when enabled | Optional and fail-open; monitoring, not an enforcement gate |
| Live event bus | Responsive desktop projection | In-memory; durable tool transactions and versioned verification updates can be replayed from the event journal |

Read [Agent Core current state](docs/AGENT_CORE_CURRENT_STATE.md) before making
shipping-safety claims. The current system is a strong implementation substrate,
not yet a non-developer-grade release authority.

## 5. Setup

### Python

```bash
uv sync --group dev
cp .env.example .env
```

Configure one provider in `.env`. Keep provider credentials out of Git. Python
3.11+ is supported; `.python-version` currently records 3.14.

### Desktop

Node is pinned in `desktop/.nvmrc` (`24.18.0`). Follow
[`desktop/README.md`](desktop/README.md):

```bash
cd desktop/vscode
npm install
npm run typecheck-client
npm run valid-layers-check
npm run compile
node scripts/emit-crusorai-bundle.mjs
```

Then launch from the repository root:

```bash
./crusor.sh /absolute/path/to/project       # macOS/Linux
crusor.bat C:\absolute\path\to\project      # Windows
```

The launcher delegates to the Code OSS source launcher. The desktop starts the
bridge and preview proxy as sessions bind; no standalone webview server is
required.

## 6. Validation commands

### Agent Core

```bash
scripts/run_tests.sh
scripts/run_tests.sh src/tests/test_bridge.py -q
scripts/run_tests.sh -k verification
```

The wrapper removes live provider keys, creates a throwaway `HOME`, and pins
UTC/UTF-8. Only use its explicit unsafe integration opt-outs when a paid live
call is the purpose of the test.

### Target contracts

```bash
scripts/run_tests.sh \
  src/tests/test_ci_report_pytest.py \
  src/tests/test_crusor_shell_launcher.py \
  src/tests/test_target_environment.py \
  src/tests/test_target_pipeline.py \
  src/tests/test_preview_target_probe.py
python scripts/targets_doctor.py
```

This matches the intent of the active three-host workflow. Native runtime proof
still requires the relevant SDK, emulator/device, and host.

### Desktop overlay and panel

```bash
python scripts/refresh_selective_manifest.py
scripts/run_tests.sh src/tests/test_desktop_contrib_overlay.py -q
scripts/run_tests.sh src/tests/test_desktop_renderer_architecture.py -q
```

After source changes, run the canonical desktop compile and bundle-receipt steps
from `desktop/README.md`, then fully quit and reopen the app. Never hand-edit
compiled JavaScript, `SOURCES_HASH`, `SOURCES_MANIFEST.json`, or
`BUILD_INFO.json`.

### Telemetry and traces

```bash
python -m src.telemetry.call_ledger
CRUSORAI_OTEL=console ./crusor.sh /path/to/project
CRUSORAI_OTEL=file ./crusor.sh /path/to/project
```

Self-hosted Langfuse instructions are in `langfuse/README.md`.

## 7. Rules for safe changes

### Bridge/protocol

- Update `src/bridge/protocol_v2.json`, generated protocol constants, Python
  projection, TypeScript decoding, and tests together.
- Preserve session, turn, event, tool, and lineage IDs end to end.
- Keep ordinary diagnostics off protocol stdout.
- A terminal `turn_done`/`turn_failed` frame must not overtake pending tool
  events; keep event flushing bounded so a broken forwarder cannot hang forever.

### Tools/evidence

- Execute through `execute_tool_transaction`; never bypass intent/result
  durability for a new direct, parallel, or repaired-call path.
- Fail closed when evidence is unavailable or an exit status is not
  attributable to the command being graded.
- Invalidate verification after relevant edits.
- Prefer typed internal evidence to text-prefix parsing; preserve old formats
  until both producer and gate migrate.
- Redact or avoid persisting secrets before adding new journal payloads.

### Desktop

- Edit `desktop/vscode/src/...`, not `out/...`.
- Keep native renderer/service/model responsibilities separate.
- Do not reintroduce the deleted SPA/CopilotKit path to explain the orphaned
  generated payload.
- Respect the selective-overlay manifest and upstream-source invariants.

### Permissions

- `deny` never reaches an approval UI.
- `ask` must block before execution and be cancellable.
- **Allow always** is session-only and resource-scoped; secrets and ignored
  paths remain veto classes.
- Never use `CRUSORAI_SUBAGENT_AUTO_APPROVE=1` as evidence that child approval
  routing works.

## 8. Sequenced high-priority improvements

1. **Completed in this follow-up:** repair the two focused-suite contracts and
   add persistence-security coverage; the focused evidence selection is now
   98/98 (102/102 with the four new tests).
2. **Locally validated and activated on this branch:** the broad lane passes
   2,585/2,585 with 16 skips. Confirm the first GitHub run, then make its core
   lane required in branch protection.
3. Build on the new versioned verification envelope: adapt graph/target facts,
   add a Git worktree/lock/environment candidate manifest, and make a
   deterministic policy consume only typed evidence.
4. Add clean-room replay, dependency vulnerability, secret, license/SBOM, and
   deploy/rollback adapters before exposing a **Ready** verdict.
5. **Redaction completed; retention remains:** forced redaction now protects
   durable tool and verification writes and tool bodies are omitted. Add
   duration, size, export, and deletion controls next.
6. Resolve or remove the generated `crusorai-spa` payload and make build
   manifests prove source/output correspondence.
7. Close the child approval execution gap with a real end-to-end test.
8. Wire multi-trial reliability helpers into an actual evaluation/release gate;
   `src/runtime/reliability_metrics.py` is currently a library, not policy.
9. Either wire or retire `src/enterprise/monitor.py`; no production caller is
   present.

## 9. Documentation discipline

Follow [`docs/README.md`](docs/README.md):

- current-state docs name the commit/date they were checked against;
- plans say **proposed** until source and tests prove otherwise;
- historical evidence keeps its original claims and gains a supersession note
  instead of being rewritten;
- generated output alone never proves a feature exists;
- aggregate pass counts always include command, date, and scope.

When source, tests, generated desktop output, and prose disagree, stop and name
the disagreement. Do not silently choose the most optimistic artifact.
