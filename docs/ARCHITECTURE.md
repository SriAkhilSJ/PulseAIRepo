# CrusorAI - Architecture

**Snapshot:** `604605b2a02b3b1b6960f7959f4c122aeeed8bd4` (2026-11-09)
**Method:** source inspection. Paths are relative to the repository root.
**Scope note:** this describes the committed architecture. Uncommitted
working-tree changes are called out separately in
`docs/BUGS_AND_LIMITATIONS.md`.

**Agent runtime consolidation decision:** section 14 (2026-11-09).

---

## 1. System shape

```text
+-----------------------------------------------------------------------+
| CrusorAI.exe  (Code OSS fork, Electron 42.8.1, product 1.134.0)       |
|                                                                       |
|  workbench (TypeScript)                                               |
|    + contrib/crusorai                                                 |
|        - view pane, renderer, session controller, cards, plan         |
|        - manager window, preview window, skills hub, account          |
|        - inline completions, next-edit suggestions                    |
|        - common protocol types (generated from protocol_v2.json)      |
|        - electron-browser engine service                              |
|        - node worker main (utility process)                           |
+----------------------------------+------------------------------------+
                                   | spawn + stdio
                                   | newline-delimited JSON, protocol v2
+----------------------------------v------------------------------------+
| Python engine (src/)                                                  |
|                                                                       |
|  bridge (src/bridge)                                                  |
|    sessions, turns, queue, steer, cancel, replay, approvals           |
|    orchestrator route (default) or legacy chat graph                  |
|                                                                       |
|  orchestration (src/orchestration)                                    |
|    EngineeringExecutionOrchestrator: plan -> dispatch -> verify       |
|    FinOps governor, lifecycle, state machine, journal, supervision    |
|                                                                       |
|  graph (src/graphs/chat_graph.py)                                     |
|    task_manager -> planner/ai -> tools -> progress -> finish_gate     |
|    recovery_limit, tool_cycle_limit, pivot, plan_* nodes, finalize    |
|                                                                       |
|  context (src/context)  |  tools (src/tools)  |  targets (src/targets)|
|  llm (src/llm)         |  security (src/security)  |  verification    |
+----------------------------------+------------------------------------+
                                   |
        +--------------------------+--------------------------+
        |                          |                          |
  workspace/.crusorai/       ~/.crusorai/              local preview
  submissions, finops,       sessions.db, traces,     127.0.0.1
  journals, evidence,        memories, auth
  target-evidence
```

## 2. Desktop frontend

| Component | Path | Responsibility |
|---|---|---|
| Vendored upstream | `desktop/vscode/` | Code OSS at pinned commit `6c27443ce6fdf6ac798c64025d45175e2e23c4b4`. |
| Fork metadata | `desktop/UPSTREAM_PIN`, `desktop/SELECTIVE_MANIFEST.json` | Pin and per-file upstream/overlay hashes. |
| Branding | `desktop/vscode/product.json`, `resources/*`, `extensions/theme-*` | CrusorAI identity, icons, default theme. |
| Workbench contribution | `desktop/vscode/src/vs/workbench/contrib/crusorai/` | All Crusor UI and host integration. |
| Renderer | `browser/crusorAIRenderer.ts`, `browser/crusorAIRendererService.ts` | Chat timeline, tool cards, reasoning, plan, status. |
| Session state | `common/crusorAISessionStore.ts`, `common/crusorAISessionProjection.ts` | Session list/projection and resume. |
| Protocol types | `common/crusorAIProtocol.ts`, `common/crusorAIProtocol.generated.ts` | TypeScript mirror of the bridge schema. |
| Engine host | `electron-browser/crusorAIEngineService.ts`, `node/crusorAIWorkerProcessService.ts` | Spawns the Python bridge in a utility process. |
| Preview | `browser/crusorAIPreviewService.ts`, `browser/media/crusor-preview/` | Preview window and inspect overlay. |
| Manager | `browser/crusorAIManagerEditor.ts`, `browser/crusorAIManagerInput.ts` | Separate manager window. |
| Skills/one-shot | `browser/crusorAISkillsHub.ts`, `browser/crusorAIOneShot.ts`, `browser/crusorAIHubDialog.ts` | Marketplace, connectors, skills, quick jobs. |
| Account | `browser/crusorAIAccount.ts` | Title-bar account menu. |
| Completions | `browser/crusorAIInlineCompletionProvider.ts`, `browser/crusorAINextEditProvider.ts` | Inline and next-edit AI. |

Design rules recorded by the fork:

- Crusor never lives under `extensions/`.
- Only five upstream source files are modified (product branding, two
  registration files, two desktop bundle entry files); platform icons are
  recorded separately in the manifest.
- Built `out/vs/workbench/contrib/crusorai/**` is intentionally tracked so a
  fresh checkout boots a working panel.
- Copilot source is retained as a reference and is not deleted.

See `desktop/README.md` for the full invariant list and the manifest workflow.

## 3. Bridge and protocol

- Implementation: `src/bridge/__main__.py`, `src/bridge/protocol.py`,
  `src/bridge/turn_watchdog.py`.
- Transport: child-process stdio, one JSON object per line, max frame 1 MiB.
- Versions: protocol 2 (`PROTOCOL_VERSION = 2`), negotiated with support for 1.
- Client methods include session CRUD/fork/pin/archive, prompt/cancel/steer/
  queue, approvals, checkpoints, subagents, skills hub, one-shot, replay, host
  capabilities, inline completion, next edit, voice, shutdown.
- Server events include token/reasoning streams, plan/tool/todo/verification,
  subagent, telemetry, turn lifecycle, runtime degradation, context status,
  workspace binding, LLM request/response, host tool requests.
- Every frame carries identity fields (run/session/turn/workspace) for
  correlation.
- Workspace contract: sessions bind to a real project folder; the bridge
  refuses `.`/engine-root/bundled-app runs.

The TypeScript protocol surface is generated from `src/bridge/protocol_v2.json`
by `scripts/generate_bridge_protocol.py`. Drift is caught by tests, not by a
runtime schema validator on both ends.

## 4. Agent runtime and graph

Primary graph: `src/graphs/chat_graph.py`.

**Current routing (verified at HEAD):** the bridge sends `agent`/`plan` to
`EngineeringExecutionOrchestrator.run_task` (`src/bridge/__main__.py:1374,1467`)
and `ask`/`debug` (or `CRUSORAI_ORCHESTRATOR_ENGINE=legacy`) to
`stream_agent` (`:1539`). This is the competing-owner state that section 14
resolves: the target has one canonical turn lifecycle in LangGraph with the
orchestrator delegated as an engineering engine.

Registered nodes (verified at `builder.add_node`):

```text
task_manager
finalize
planner
ai
tools            (SafeToolNode)
progress
recovery_limit
tool_cycle_limit
pivot
plan_preview
plan_reviser
plan_cancelled
approval_without_plan
finish_gate
```

Supporting modules:

- `src/graphs/state.py` - `AgentState`.
- `src/graphs/gates.py`, `budget.py`, `loop_guards.py`, `progress_guard.py`,
  `task_validation.py`, `parallel_tools.py`, `verification_helpers.py`.
- `src/orchestration/orchestrator.py` - `EngineeringExecutionOrchestrator`,
  selected by the bridge for `agent`/`plan` modes unless
  `CRUSORAI_ORCHESTRATOR_ENGINE=legacy`.

Streaming entry points: `stream_agent`, `get_agent_status`,
`fork_conversation`, `export_session_analytics`.

## 5. Context engine

- Abstract base: `src/context/engine.py` (`ContextEngine(ABC)`) plus sanitizer
  and threshold helpers.
- Facade: `src/context/context_engine.py` (`ContextEngine(CoreContextEngine)`),
  with a layer registry split into `_build_context_layers_inner` so the shared
  budget wrapper applies uniformly.
- Named layers include repo map, relevant chunks, git context, task, plan,
  progress, recovery, replan, attempt history, long-term memory, tool memory,
  ambiguity, tone, quality, conventions, memory validation, reflections, and
  skills.
- Supporting modules: token budget/calibration/tracker, compaction and
  micro-compaction, history shaper, summarizer, cache preservation and prompt
  cache plan/audit, vector memory, persistent memory, feedback memory,
  safety guard, file safety, workspace integrity.

Token economics are enforced in the graph and context layers, and surfaced
through `TokenUsage` and status contracts.

## 6. AI / LLM integration

- Factory: `src/llm/factory.py`; settings: `src/config/settings.py`.
- Providers: Groq, OpenAI-compatible (including custom gateways such as
  Velona), Google Gemini, NVIDIA, plus a `cheap` route for auxiliary work.
- Model/provider are selected by `LLM_PROVIDER` and `LLM_MODEL`; auxiliary
  calls use `AUX_LLM_PROVIDER`/`AUX_LLM_MODEL` (default `cheap`).
- Provider SDKs are imported lazily so a missing optional SDK does not break an
  unrelated provider configuration.
- Guards: conservative token limits, output caps derived from the provider,
  repetition/degenerate-output detection, retry/backoff with cancellation,
  request sanitization, acceptance-mode budget gates, prompt-cache audit.
- Tracing: `src/runtime/otel_tracing.py`, opt-in `CRUSORAI_OTEL`, OTLP export
  to a self-hosted Langfuse; fail-closed so tracing cannot break a turn.

## 7. Tools, agents, skills

- Tool waist: `src/tools/toolsets.py` maps immutable runtime capabilities to
  tool names. Core always-on tools: `todo_list`, `clarify` (plus `think`/
  `verify` only when explicitly enabled).
- Categories: workspace read/write, execution/terminal, verification, UI
  verification, multi-platform targets and devices, research/web, media,
  skills, MCP, delegation, browser.
- Subagents: `delegate_to_subagent` and `delegate_to_subagent_batch` in
  `chat_graph.py`; lifecycle/registry/permissions/store modules in
  `src/agents/` and `src/runtime/subagent_store.py`; depth guard
  `CRUSORAI_SUBAGENT_DEPTH`.
- Skills: bundled under `skills/`, managed by `src/agents/skill_manager.py`,
  `skills_hub.py`, and exposed through `src/tools/skill_tools.py` and
  `skill_hub_tools.py`.

## 8. Security architecture

| Layer | Path | Role |
|---|---|---|
| Safety guard and approvals | `src/context/safety_guard.py`, graph permission logic | Classifies risky actions, requests approval, fails closed on timeout/cross-session resolve. |
| Mutation broker | `src/workspace/mutation_broker.py` | Ownership, snapshots, hashes, rollback for workspace writes. |
| Execution broker | `src/security/execution_broker.py`, `contracts.py` | Single chokepoint for process creation; approval token, workspace jail, env allowlist, output caps, receipt hash. |
| OS sandboxes | `src/security/sandbox/{windows,linux,macos,manager}.py` | Windows AppContainer/Job Objects, Linux namespaces/cgroups, macOS sandbox-exec, fail-closed stub. |
| MCP/browser security | `src/security/mcp/`, `src/security/browser/` | Tool authorization and browser boundary rules. |
| Identity/RBAC | `src/identity/` | Roles, authorization, tenancy, audit, resource guard, tool authorizer. Implemented; not wired into the live tool path. |
| Static/import guards | `scripts/agent_core_checkup.py`, `src/tests/test_security_containment.py` | Blocks import-time process spawn, writes outside the repo, security API payloads; exact grant body and sync/async ownership, bindings, structures, imports, module declarations, helper body and manager manifests. |
| Windows runtime harness | `src/tests/test_windows_sandbox_runtime.py`, `src/tests/native/net_probe.c` | Windows-only Job Object/AppContainer runtime evidence; 1 MiB output pipes; native network isolation proof; opt-in AppContainer tests never write machine ACLs. |
| CI gate | `.github/workflows/security-guard.yml` | Runs the security containment suite on Ubuntu, Windows, macOS. |

## 9. Persistence and storage

| Store | Location | Contents |
|---|---|---|
| Session checkpoints | `~/.crusorai/sessions.db` (SQLite) | LangGraph checkpoints, session state. |
| Financial store | same `sessions.db` or `CRUSORAI_FINANCIAL_DB` | Reservations, invocations, settlements, ledger. |
| Workspace runtime | `<workspace>/.crusorai/` | `submissions/`, `finops/`, `journals/`, `test_reports/`, `target-evidence/`, project intelligence/baseline. |
| Event/journal | JSONL under workspace/home | Turn events, run state, submission event stream. |
| Memory | `~/.crusorai/memories.json`, vector index | Persistent memory and embeddings (local by default). |
| Evidence | `diagnostics/`, `bench-results/`, `benchmarks/` | Immutable run packages and reports. |

SQLite is the canonical durable store. Financial records also exist in JSONL
ledgers; they are reconciled but are not one transactional store.

## 10. APIs and local services

| Service | Path | Bind | Purpose |
|---|---|---|---|
| AG-UI agent | `src/server.py` | loopback by default, `src/agui/bind.py` | FastAPI + `ag-ui-langgraph`, CopilotKit agent `crusor_agent`. |
| Dashboard | `src/dashboard_server.py` | local Flask | Sessions, status, checkpoints, usage. |
| Preview proxy | `src/preview/` | `127.0.0.1:8931` (or free port) | Web/device preview, inspect, device mirror. |
| Bridge | `src/bridge/__main__.py` | stdio | Desktop-engine RPC. |

A non-loopback bind without `CRUSORAI_DASHBOARD_TOKEN` is refused by the AG-UI
bind guard.

## 11. Testing and CI

- Pytest config: `pytest.ini`, `testpaths = src/tests`, `pythonpath = .`.
- 334 `test_*.py` modules under `src/tests/`; additional suites under
  `tests/e2e/`, `apps/personal_finance/tests/`, and desktop/webview projects.
- Workflows:
  - `agent-core-checkup.yml` - keyless body checkup on every `src/**` push.
  - `security-guard.yml` - cross-platform security suite (Python 3.14).
  - `host-compatibility.yml` - target contracts on Windows/macOS/Linux.
  - `diagnosability.yml` - termination/token contracts.
  - `e2e-core.yml` - real GLM 5.3 turn through the real graph.
  - `long-session.yml` - multi-turn stamina under token/cost caps.
  - `verify-provider-key.yml` - secret shape and live provider calls.

## 12. Deployment and build

- Python: `uv`-managed (`pyproject.toml`, `uv.lock`); Python >= 3.11.
- Desktop: build inside `desktop/vscode` with npm/TypeScript/gulp; packaging
  scripts under `scripts/` (for example `reproduce_desktop_build.mjs`,
  `transpile_crusorai.mjs`).
- No cloud deployment topology is verified in this repository. Treat startup
  scripts and local services as developer/desktop tooling, not a hosted
  production deployment.

## 13. Architectural risks

1. Two agent paths exist today (graph vs orchestrator); behaviour can diverge.
   Section 14 selects LangGraph as the single turn lifecycle and the
   orchestrator as a delegated engineering engine; the migration is not yet
   implemented.
2. Desktop protocol lacks frames for several intelligence artifacts.
3. Identity/RBAC is implemented but not enforced in the live tool path.
4. Financial state spans SQLite and JSONL with reconciliation, not a single
   transaction.
5. Long-turn token cost remains the dominant economic risk.
6. The desktop fork carries 18k vendored files; upstream drift and build
   reproducibility require the manifest checks.

Details and status: `docs/BUGS_AND_LIMITATIONS.md`.

## 14. Agent runtime consolidation decision (2026-11-09)

**Status:** FROZEN / QUALIFIED (2026-11-11). Increments 1–3 are closed. The
canonical LangGraph lifecycle, engineering delegation, checkpoint replay,
provider-boundary fixture, Windows path identity and fresh bridge-process
recovery are qualified in `bench-results/phase-3.3-canonical-runtime/`.
Remaining product limitations are recorded in `FINAL_CLOSURE_REPORT.md`; no new
runtime or migration phase is authorized.

**Baseline:** `604605b2a02b3b1b6960f7959f4c122aeeed8bd4`,
`feat/prompt-cache-stabilization`.

**Decision in one sentence:** LangGraph (`src/graphs/chat_graph.py`) is the one
canonical interactive turn lifecycle; `EngineeringExecutionOrchestrator`
(`src/orchestration/orchestrator.py`) is retained as the delegated engineering
execution engine for contract-first work, invoked from inside the graph, not as
a second top-level owner.

### 14.1 Method and evidence base

Sources read: `docs/CURRENT_STATE.md`, `docs/handoffs/LATEST_HANDOFF.md`,
`docs/DECISIONS.md` (ADR-003, ADR-024, ADR-025), the seven Phase 12.0.1 audit
documents, and the implementation. The Phase 12.0.1 documents are dated
2026-11-06 and predate Phase 3.1/3.2; their central "orchestrator is not the
desktop path" finding is no longer true and the running code below is the
evidence of record.

Runtime evidence used: Phase 3.1 approval probes and desktop smoke
(`bench-results/phase-3-approval-integration/`), Phase 3.2 planner closure
(`bench-results/phase-3.2-planner-contract-closure/`), and the Phase 2 probes
showing orchestrator turns leave `session_messages` empty
(`bench-results/phase-2-desktop-qualification-r2/logs/probe-orchestrator-default.out.txt`).

### 14.2 Actual state today

#### 14.2.1 Desktop to bridge

`crusorAIRendererService.submitPrompt` builds a typed Protocol v2 `prompt`
frame and sends it; `CrusorAIEngineService` spawns the Python bridge through a
utility process (`node/crusorAIWorkerProcessService.ts`). The bridge's
`BridgeServer._run_turn` (`src/bridge/__main__.py:1083`) owns one worker thread
per session turn and routes by mode.

#### 14.2.2 Current routing (the competing owners)

`src/bridge/__main__.py:1374`:

```python
use_orchestrator = (
    mode in ("agent", "plan")
    and os.environ.get("CRUSORAI_ORCHESTRATOR_ENGINE", "orchestrator").lower() != "legacy"
)
```

- `agent` / `plan` → `EngineeringExecutionOrchestrator.run_task(...)`
  (`src/bridge/__main__.py:1467`).
- `ask` / `debug` and `CRUSORAI_ORCHESTRATOR_ENGINE=legacy` → `stream_agent(...)`
  (`src/bridge/__main__.py:1539`).

So today the desktop has two top-level owners selected by mode/env, not one.
ADR-003 ("Use LangGraph for the turn lifecycle") is still the recorded decision
but is contradicted by the default route.

#### 14.2.3 Path A — EngineeringExecutionOrchestrator

Entry: `EngineeringExecutionOrchestrator.run_task` (`orchestrator.py:385`).

Lifecycle and components actually invoked:

| Stage | Implementation | Evidence |
|---|---|---|
| Project discovery | `PersistentProjectIntelligenceManager`, `RepositoryDiscoveryEngine` | `orchestrator.py` constructor + stage 3 |
| Requirement analysis | `RequirementIntelligenceSystem.analyze_request` | `orchestrator.py:474` |
| Architecture | `ArchitectureIntelligenceSystem.synthesize_architecture` | stage 5 |
| Contract + assignment | `extract_contract`, `validate_contract_plan` | `contract.py`; ADR-025 |
| Plan | `EngineeringTaskPlanner.build_plan` (contract components) | `planner.py:_build_contract_plan` |
| Impact / baseline | `ChangeImpactAnalysisEngine`, `RegressionPreventionEngine` | stages 7-8 |
| Approval | `OrchestratorApprovalGateway` → shared `ApprovalQueue` | `approval_gateway.py`; ADR-024 |
| Implementation | `ModelExecutionAdapter.execute_node` → `ControlledImplementationEngine.execute_node_mutation` → `WorkspaceMutationBroker` | `model_adapter.py:727`, `implementation_engine.py:49`, `mutation_broker.py` |
| Verification / repair | `IndependentVerificationEngine.verify_task`, bounded repair loop | `orchestrator.py:1223` |
| Production readiness | `ProductionReadinessEngine` | stage 14.5 |
| Completion | `DeliveryContract` verdict | `orchestrator.py:1341` |
| FinOps | `OrchestrationFinOpsGovernor` + per-invocation ledger | `model_adapter.py:1269` |

What it bypasses:

- **ContextEngine and history compaction.** `model_adapter.py` calls
  `get_llm(...)` (`:1298`) and `llm.invoke(prompt)` (`:1342`) with its own
  prompts; no `ContextEngine` import exists in `src/orchestration/`.
- **Conversation memory and repository memory.** There is no memory retrieval in
  the orchestrator path.
- **Tools.** It does not dispatch the graph's tool registry; code generation is
  direct prompt→text→file.
- **Subagents / clarify / streaming tokens.** No `subagent` or `clarify`
  references in `src/orchestration/`.
- **Durable conversation transcript.** It writes its own journal and evidence,
  but not LangGraph checkpoints; the bridge transcript reader
  (`_transcript_messages`, `bridge/__main__.py:216`) reads checkpoints, so
  orchestrator turns persist a session row with an empty transcript (observed:
  Phase 2 probe `"messages": []`).

It does own the strongest safety/mutation and verification chain: approval →
`APPV-` token → `verify_and_consume_approval_token` → broker write.

#### 14.2.4 Path B — LangGraph stream_agent

Entry: `stream_agent` (`chat_graph.py:7803`). The compiled graph is
`builder.compile(checkpointer=SqliteSaver(...))` at `chat_graph.py:7688`, with
the checkpointer in `~/.crusorai/sessions.db` (`:7664-7685`).

Registered nodes (`builder.add_node`, `chat_graph.py:7331-7390`):
`task_manager`, `finalize`, `planner`, `ai`, `tools` (`SafeToolNode`,
`:6295`), `progress`, `recovery_limit`, `tool_cycle_limit`, `pivot`,
`plan_preview`, `plan_reviser`, `plan_cancelled`, `approval_without_plan`,
`finish_gate`.

What it owns:

- **Context assembly**: `get_context_engine(config).build_ai_messages(...)`
  (`chat_graph.py:2310`), `ContextEngine` creation at `:7651`.
- **History compaction / memory**: `HistoryShaper`, context layers, long-term
  memory policy, convention learning.
- **Model streaming and tool iteration**: `ai_node`, tool calls, `SafeToolNode`.
- **Approvals for tools**: `approval_queue.request(...)` +
  `event_bus.emit("tool.approval.request", ...)` (`chat_graph.py:7040`), with a
  cancellation-aware wait.
- **Checkpoints, replay, transcript**: the SqliteSaver state is what
  `_transcript_messages` returns to the desktop.
- **Subagents, clarify, plan preview, finish gate.**

What it lacks / blocks:

- **It currently cannot run at all**: `src/context/history_shaper.py` imports
  `compact_assistant_tool_call_arguments` and
  `transform_completed_tool_receipts` from `src/context/compaction.py`, neither
  of which exists (B-DESK-001). This is an import defect, not a design gap.
- **Contract-first planning, impact/regression engines, production readiness,
  mutation broker** are not in its path. `src/tools/file_tools.py` writes
  directly at HEAD (B-001).
- It does not read the orchestrator's journal/evidence.

#### 14.2.5 Integration classification (actual, not aspirational)

| Capability | Orchestrator path | Graph path | Status |
|---|---|---|---|
| Turn lifecycle | yes (own) | yes (own) | **competing** |
| Context assembly | no | yes | graph only |
| History compaction | no | import-blocked | blocked |
| Long-term memory | no | yes (policy-gated) | graph only |
| Contract/plan validation | yes | no | orchestrator only |
| Impact/regression | yes | no | orchestrator only |
| Tool registry execution | no | yes | graph only |
| Mutation broker | yes | no (B-001) | orchestrator only |
| Approval queue | yes (gateway) | yes (SafeToolNode) | shared queue, two askers |
| Verification/repair | yes (engines) | finalize/finish_gate | divergent |
| Durable transcript | no | yes | graph only |
| Subagents/clarify | no | yes | graph only |
| FinOps ledger | yes (engineering ledger) | graph/governor | two ledgers |
| Evidence receipt | yes | partial | two formats |

### 14.3 Decision and rejected alternatives

**Selected: Option 3, with the orchestrator retained as a delegated engine.**

LangGraph owns the canonical turn lifecycle and is the only top-level execution
owner for interactive turns. `EngineeringExecutionOrchestrator` becomes an
engineering engine invoked from a graph node (for `agent`/`plan` work), returning
a `DeliveryContract`, with the graph owning context, tools, approvals, checkpoints
and final completion.

Why this and not the alternatives:

1. **Not Option 1 (orchestrator owns everything).** It would require rebuilding
   context assembly, history compaction, memory, subagents, clarify, streaming
   and checkpointed replay inside the orchestrator. ADR-003 and the desktop's
   replay/transcript contract (SqliteSaver) already depend on the graph. It also
   throws away the only fully integrated conversation surface.
2. **Not Option 2 (orchestrator outer, graph inner loop).** It preserves today's
   inversion and keeps the durable transcript, context and replay outside the
   lifecycle owner. Fixing those means re-implementing graph facilities at the
   outer layer, and `ask` mode would still need a second owner. Two lifecycles
   for one product remain.
3. **Selected Option 3** keeps ADR-003, keeps the desktop's durable transcript
   and streaming, keeps the orchestrator's contract/verification/broker
   investment, and gives exactly one lifecycle owner. The migration is
   integration work (one node and one interface), not a rewrite.

The bridge stays the transport and mode router, but it no longer owns an
alternative lifecycle: it always calls `stream_agent`. The graph decides whether
the turn is conversational (`ai`/tools/finalize) or engineering (delegates to the
orchestrator node).

### 14.4 Component ownership

| Capability | Owner (target) | Interface |
|---|---|---|
| Turn lifecycle, cancellation, checkpoints | LangGraph `stream_agent` | `TurnRequest` → `TurnResult` |
| Mode classification (chat vs engineering) | Graph `task_manager` | `AgentState.execution_mode`, task intent |
| Engineering task lifecycle (contract → delivery) | `EngineeringExecutionOrchestrator` | `EngineeringTaskRequest` → `DeliveryContract` |
| Requirement → contract → plan | `RequirementIntelligenceSystem`, `extract_contract`, `EngineeringTaskPlanner` | `EngineeringContract`, `EngineeringPlanDAG` |
| Context assembly / history | `ContextEngine`, `HistoryShaper` | `build_ai_messages()`, compaction helpers |
| Conversation + repository memory | context/memory layer under graph | memory policy + retrieval |
| Model routing/provider calls | `src/llm/factory.get_llm` + `RetryLLMProxy` behind one gateway | `ModelRequest` |
| Tool registration/execution (reads, search, etc.) | Graph tool registry + `SafeToolNode` | tool schema + `ToolCall` |
| Human approval | one `ApprovalQueue` + `RiskApprovalGate` | `ApprovalRequest` / `SafetyReply` |
| Workspace mutation/security | `WorkspaceMutationBroker` (all writes) | `MutationRequest` + `APPV-` token |
| Verification / repair | `IndependentVerificationEngine` + bounded repair (via engine), graph `finish_gate` for turn completion | `DeliveryContract` + `finish_gate` |
| Completion/evidence | Graph `finalize` + `TurnEvidenceRecorder` | `TurnResult` + `EvidenceReceipt` |
| Session persistence | `session_store` + SqliteSaver checkpoints | session/message rows |
| Observability / FinOps | `event_bus`, journal, invocation ledger | events + invocation records |

The one deliberate exception: `ask`/chat turns never construct a contract or
plan; they use graph context/tools/finalize directly. That is a conversational
surface, not a second task-lifecycle owner.

### 14.5 Target runtime sequence

```text
Desktop prompt (Protocol v2)
  -> BridgeServer._run_turn
      -> stream_agent (always; no orchestrator branch)
          -> task_manager classifies: CHAT or ENGINEERING
          -> ContextEngine builds messages (history compaction + memory)
          -> CHAT: ai -> tools* -> progress -> finish_gate -> finalize
          -> ENGINEERING:
               engineering_task node
                 -> EngineeringExecutionOrchestrator.run_task(EngineeringTaskRequest)
                      discovery -> requirements -> architecture -> contract -> plan
                      -> impact/baseline -> approval gateway -> implementation
                      -> mutation broker (APPV- token) -> verification -> repair
                      -> DeliveryContract (evidence + verdict + files + cost)
                 -> graph accepts only a verified DeliveryContract
          -> finish_gate (turn completion) -> finalize
          -> checkpoint + session messages + events + evidence receipt
      -> bridge streams frames to desktop
```

### 14.6 Interfaces and data contracts

- `TurnRequest` (existing bridge `prompt` frame): `session_id`, `workspace`,
  `text`, `mode`, `reasoning_effort`, `submission_id`.
- `EngineeringTaskRequest` (new adapter object, built from `AgentState`):
  `task_id`/`turn_id`, `session_id`, `workspace`, `prompt`, `contract_context`
  (context summary + explicit constraints), `approval_policy`,
  `approval_callback`, `cancellation_checker`, `budget` (`max_cost_inr`,
  `max_dispatches`, per-node output ceiling).
- `DeliveryContract` (existing `src/orchestration/models.py`): verdict, files
  changed, tests, verification, evidence references, cost/token usage,
  limitations. The graph treats `COMPLETED`/`PARTIALLY_COMPLETED` as the only
  valid non-failure outcomes.
- `ApprovalRequest` (existing `tool.approval.request`): `tool_id` (unique),
  `session_id`, `task_id`, `workspace`, `path`/resource, `operation`, `reason`,
  `diff` (file diff when available), `warning`.
- `SafetyReply` (existing `safety_reply`): `session_id`, `tool_id`, `approved`,
  `always_allow`; resolved by the shared `ApprovalQueue`; duplicate/stale replies
  return `False` (`event_bus.py:165`).
- `MutationRequest` (existing broker API): `path`, `content`/`new_content`,
  `task_id`, `approval_token`; the broker verifies the token is bound to exact
  task/workspace/path/operation and single-use
  (`mutation_broker.py:133/219/291/412`).
- `EvidenceReceipt` (existing `src/runtime/evidence_capture.py`): status,
  evidence id, manifest hash, missing artifacts, lifecycle flags. Orchestrator
  and graph turns must produce the same shape; orchestrator currently produces
  its own `EvidenceReceipt` via `TurnEvidenceRecorder`.
- `ToolCall`/`ToolResult` (existing graph tools): one schema registry; the
  engineering executor must not invent a parallel tool surface.

### 14.7 Failure, cancellation, retry, recovery

- **Cancellation:** `turn_controls` is the single token. The graph checks it in
  `ai`/tools and resolves pending approvals with `should_stop`
  (`event_bus.wait_for_decision(should_stop=...)`); the orchestrator receives
  `cancellation_checker` and its gateway wakes on the same predicate. The graph
  must pass its cancellation predicate into `EngineeringTaskRequest`.
- **Approval denial/timeout/shutdown:** `ApprovalDenied` is terminal for the
  node; the graph maps it to a cancelled turn with no mutation (Phase 3.1). No
  retry may auto-approve. A denied operation is not retried without a new ask.
- **Model/provider retry:** one owner, `RetryLLMProxy` (bounded attempts) with
  the orchestrator's per-dispatch reservation. The engineering node must use the
  same gateway; the current orchestrator adapter already sets `_max_attempts=1`
  for metered dispatches (`model_adapter.py:1310-1320`).
- **Test/repair retry:** bounded by `ExecutionLimits.max_correction_attempts`;
  the graph does not duplicate it.
- **Worker recovery:** bridge restarts the sidecar (Phase 2 evidence). Turn
  recovery uses checkpoints for the graph; orchestrator journal/evidence is
  reconciled on shutdown. The graph owns the turn terminal so a crashed engine
  produces one failed/cancelled receipt, not two.
- **Crash/replay:** checkpointed graph state is the source of truth for the
  transcript; orchestrator events must be projected into the same turn/event
  stream, not a private journal that the desktop cannot read.

### 14.8 Persistence and observability

```text
Prompt/turn
  -> event_bus events (token/tool/approval/verification) -> bridge frames
  -> LangGraph checkpoint (~/.crusorai/sessions.db) -> session_messages/replay
  -> TurnEvidenceRecorder manifest (workspace/home evidence)
  -> orchestration journal (task lifecycle) + invocation ledger (cost)
Desktop Manager/Agent read the same session store and event projection.
```

Target rule: a turn is "persisted" only when (a) the checkpoint contains the
user/assistant messages, (b) the evidence receipt is `persisted` (or explicitly
`not_applicable` for a cancelled-before-execution turn), and (c) the journal
terminal is recorded. The orchestrator's private journal is an implementation
detail, not a second transcript.

### 14.9 FinOps and model routing

- One routing decision per call via `src/llm/factory.get_llm` (cheap/balanced/
  strong tiers already exist as provider/model config; `AUX_LLM_*` for auxiliary
  work). The engineering node must receive the same routed client and record the
  same invocation.
- One ledger key: `turn_id`/`task_id` + `session_id` + `workspace_id`. The
  orchestrator's `record_invocation` (`model_adapter.py:1269`) and the graph's
  cost governor must write the same schema; `CRUSORAI_TURN_ID` is already set by
  the bridge.
- Budgets: task `max_cost_inr`, `max_dispatch_budget`, per-node output ceiling,
  and per-session cap. A dispatch without a reservation is refused (current
  orchestrator behavior).
- Attribution: per task (orchestrator), per turn (graph), per session (bridge),
  per tenant (FinOps). Cost per successful task = settled spend / verified
  `DeliveryContract` count.

### 14.10 Blocker classification

| Blocker | Decision | Reason |
|---|---|---|
| **B-DESK-001** missing compaction exports | **FIX in Increment 1** | stream_agent is the selected canonical lifecycle; the graph cannot run without it. This is an import/implementation repair of two documented functions, not an architecture change. |
| **B-DESK-005** approval before a useful diff | **REWORK in Increment 2** | Move/duplicate the ask to mutation time inside the engineering node so the dock carries the generated diff; until then keep the stage-9 ask (resource/operation/reason) as a documented limitation. |
| **B-DESK-006** denied operation counted as “1 landed” | **FIX in Increment 3** | Display-only accounting in `stampInterrupt`; correct it when the unified completion/receipt work lands. |
| **B-DESK-007** historical repair-lifecycle test | **RETAIN as known limitation** | Fails identically at HEAD with the Phase 3.2 files restored; independent of the ownership decision. Fix only if the repair lifecycle is prioritized. |

Do not spend time on any other retired path: the bridge's direct orchestrator
branch is retired by Increment 1, and with it the second approval/persistence
surface.

### 14.11 Migration plan (three increments, no new phases)

#### Increment 1 — Single turn owner and engineering delegation

**Components:** `src/bridge/__main__.py` (`_run_turn` route), `src/graphs/chat_graph.py`
(`task_manager` intent + a new `engineering_task` node or an existing tool
adapter), `src/orchestration/orchestrator.py` (accept `EngineeringTaskRequest`),
`src/context/history_shaper.py` + `src/context/compaction.py` (B-DESK-001).

**Outcome:** every interactive turn enters `stream_agent`; the bridge has no
direct orchestrator branch; `agent`/`plan` turns delegate to the orchestrator
node, which returns a `DeliveryContract`; `ask`/chat stays conversational.

**Dependencies:** none beyond the current tree.

**Tests:** `test_bridge_orchestrator_protocol.py` (routing),
`test_eager_history_compaction.py` (B-DESK-001), a new
`test_graph_delegates_engineering_task.py` (node contract + cancellation), the
Phase 3.1 approval suite (11), Phase 3.2 contract suite (14), Phase 11.6 (44).

**Acceptance / proof:** `CRUSORAI_ORCHESTRATOR_ENGINE` no longer selects an
owner; a graph run shows the `engineering_task` node in events; a completed
engineering turn leaves non-empty `session_messages` and survives a full
Electron restart; B-DESK-001 test passes.

#### Increment 2 — One context/tool/approval/mutation boundary

**Components:** `ContextEngine`/`HistoryShaper` feeding the engineering node
prompt; `src/orchestration/model_adapter.py` backed by the shared model gateway;
`src/orchestration/approval_gateway.py` + `src/dashboard/event_bus.py` (one ask,
diff at mutation time, B-DESK-005); `src/orchestration/implementation_engine.py`
+ `src/workspace/mutation_broker.py` (all writes); `src/tools/file_tools.py`
(B-001 closure); `src/graphs/chat_graph.py` `SafeToolNode` (no double ask).

**Outcome:** one approval queue and one mutation boundary; the engineering node
uses assembled context and the graph's read/search tools; every write carries an
`APPV-` token bound to path/operation; no tool path writes directly.

**Tests:** approval integration (allow/deny/timeout/cancel/wrong-session/stale),
broker authorization, context budget/history, `file_tools` broker regression,
single-ask assertion (one `safety_request` per mutation with diff), no duplicate
dispatch.

**Acceptance / proof:** network trace/event log shows one ask per mutation with a
diff; denied mutation leaves file bytes unchanged; context token budget appears
in the turn receipt; B-001 regression test fails closed without a token.

#### Increment 3 — Unified completion, evidence, persistence, FinOps, retirement

**Components:** `src/graphs/chat_graph.py:finalize`/`finish_gate` consuming
`DeliveryContract`; `src/runtime/evidence_capture.py`; `src/runtime/session_store.py`;
`src/orchestration/model_adapter.py` ledger + graph cost governor; renderer
receipt accounting (`crusorAIRendererService.stampInterrupt`, B-DESK-006); bridge
turn routing cleanup (remove the orchestrator branch/env).

**Outcome:** one terminal verdict, one evidence manifest, durable cold replay,
one per-turn cost attribution, truthful cancelled/denied receipts.

**Tests:** Phase 11.6 end-to-end through the graph; cold Electron replay; cancel
and deny; evidence receipt; cost attribution; receipt count regression.

**Acceptance / proof:** a completed task replays after a full app restart with
user+assistant messages and the same evidence hash; cost per task reported from
one ledger; no `1 landed` on a denial; the bridge has one execution path.

### 14.12 Benchmark and performance architecture (future, not executed here)

No provider calls or tournaments in this task. The measurement plan for the
cloud/API deployment:

| Metric | Definition | Source |
|---|---|---|
| Successful coding tasks | `DeliveryContract.verdict == COMPLETED` and verification passed | orchestrator delivery, `finish_gate` |
| Cost per successful task | settled INR / successful tasks | invocation ledger |
| Total provider tokens | input+output+cached tokens | usage receipts / ledger |
| Provider/API cost | settled cost, not estimates | `record_invocation` |
| Time to first response | prompt accepted → first token/status frame | event timestamps |
| Total task latency | prompt → terminal frame | bridge turn timing |
| Retries | provider retries + repair attempts, separated | ledger + journal |
| Recovery success | turns completed after worker/restart | session events/evidence |
| Verification pass rate | verified / executed | `DeliveryContract` + evidence |
| Memory/context accuracy | grounded recall/precision on a fixed task set | memory tests |
| Safety violations | unauthorized mutations, approval bypasses | broker denials + audit |
| Repeated-run reliability | pass rate over N identical runs | benchmark harness |

Cloud target: one API model gateway (cheap/balanced/strong), per-tenant quotas,
budget ceilings per task/session, 24-hour availability with a queue/worker
topology, and evidence retained per run. Deterministic mock runs are the
regression lane; live runs are a separate, budget-capped lane.

### 14.13 Unresolved decisions and risks

1. **Conversational vs engineering split:** `ask` stays graph-only; confirm
   whether a future "chat that edits" should enter the engineering node.
2. **Context ownership:** does the engineering node receive the full assembled
   context or a bounded summary? Token budget ownership must be explicit.
3. **Tool surface:** whether the orchestrator calls graph tools for reads/search
   or only accepts generated artifacts. The current adapter does neither.
4. **Double model calls:** graph `ai` and orchestrator implementation both call
   models; the target must ensure one plan, one implementation dispatch set.
5. **Subagents:** graph-only today; engineering tasks cannot delegate yet.
6. **FinOps:** two ledgers must become one schema before cost-per-task is
   trustworthy.
7. **B-DESK-007** remains a pre-existing test failure; it does not block the
   architecture but weakens the "repair" evidence until fixed.
8. **No production cloud topology is verified** in this repository; the target
   above is a design, not an implemented deployment.
