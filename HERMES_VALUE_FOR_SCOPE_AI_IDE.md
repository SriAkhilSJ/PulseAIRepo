# Hermes Architecture Value for Scope AI IDE Agent

**Date:** 2026-08-13  
**Purpose:** Capture the architectural value Hermes creates, then translate that value into a focused architecture for the Scope AI IDE Agent. This is not a proposal to copy Hermes wholesale.

## 1. Test correction: the README command

The PulseAI README specifies this Windows command:

```powershell
New-Item -ItemType Directory -Force -Path "D:\pytest-tmp" | Out-Null
$env:TMP="D:\pytest-tmp"; $env:TEMP="D:\pytest-tmp"
.venv\Scripts\python.exe -m pytest src\tests -q --no-header --ignore=src/tests/test_session_engines.py
```

This review environment is Linux, so PowerShell's `New-Item`, the `D:` drive and `.venv\Scripts\python.exe` cannot be executed literally. I ran the behaviorally equivalent command with:

- an external temporary directory, matching `D:\pytest-tmp` being outside the repo;
- `python -m pytest` from the project environment;
- `--no-header`;
- the exact `--ignore=src/tests/test_session_engines.py` selection.

```bash
mkdir -p /home/user/pytest-tmp
uv run python -m pytest src/tests -q --no-header \
  --ignore=src/tests/test_session_engines.py \
  --basetemp=/home/user/pytest-tmp
```

Baseline result before this task's fixes was 558 passed / 7 failed. The task fixed the portable syntax fallback, platform-coupled regressions, and stale fixed-count tests.

Current result:

- **569 tests collected**
- **589 passed**
- **1 dependency deprecation warning**
- Runtime about **1m 51s**

## 2. The right way to read Hermes

Hermes is a large product repository—roughly 9,000 tracked files in the inspected checkout. Its value is not any one large Python file. Its real contribution is a set of **runtime invariants and product boundaries** learned from long-running agent failures.

The useful question is not:

> “How do we copy Hermes?”

It is:

> “What conditions does Hermes enforce so an agent remains fast, correct, interruptible, durable and usable across different clients?”

That value can be captured in a much smaller Scope architecture.

## 3. The highest-value Hermes principles

### 3.1 The backend owns agent truth; the IDE owns presentation

Hermes Desktop uses three clear authorities:

1. **Electron/native host** owns machine lifecycle and native capabilities.
2. **Renderer** owns navigation and temporary UI state.
3. **Agent backend** owns sessions, model calls, tools and durable work.

This is the most important lesson for Scope. The IDE must not implement a second agent loop in TypeScript. It should render the agent's durable state and send commands through one protocol.

**Value to Scope:**

- one agent behavior across CLI, IDE and future clients;
- less duplicated logic;
- backend improvements reach every UI;
- UI crashes do not corrupt the agent's source of truth;
- easier testing because protocol and engine can be tested separately.

### 3.2 Every state object has one authority and an explicit scope

Hermes repeatedly distinguishes:

- profile identity;
- connection identity;
- stable session identity;
- live runtime identity;
- project/workspace identity;
- sub-agent identity;
- lineage identity after compression or forks.

It uses context-local state instead of process-global mutation when serving concurrent sessions.

**Value to Scope:** prevents the most damaging IDE-agent bugs:

- one project receiving another project's events;
- model/tool settings bleeding between sessions;
- stale async responses overwriting newer user intent;
- history disappearing after compression or restart;
- a tool running in the IDE installation directory instead of the selected workspace.

### 3.3 Persist before projecting or performing important side effects

Hermes treats durable session storage as canonical. Tool-call intent is appended before the tool runs, and tool results are persisted before UI completion events are projected. If persistence fails before a side effect, execution stops rather than creating work the transcript cannot explain.

This is stronger than “save at the end of the turn.”

**Value to Scope:**

- crash recovery that users can trust;
- no tool card claiming an operation that the session forgot;
- reconstructable tool timelines after IDE/backend restart;
- auditable actions;
- safer terminal and file operations.

### 3.4 Prompt caching is an architectural invariant

Hermes builds a stable system prompt once per session, persists it, restores it byte-for-byte, and places volatile context outside the reusable prefix. It avoids silently rebuilding the historical prefix on every turn.

**Value to Scope:**

- lower first-token latency after turn one;
- lower cached-provider cost;
- predictable context behavior;
- model/provider failover without unnecessarily discarding the stable prefix.

Scope should preserve PulseAI's task-aware retrieval, but retrieval should enter a volatile request tail instead of continuously rewriting the stable session identity and rules.

### 3.5 Narrow tool waist, capability at the edges

Hermes does not treat every available integration as a permanent core model tool. Toolsets are selected by surface and task posture. Session/client capabilities determine which UI-specific actions exist.

**Value to Scope:**

- fewer tool-schema tokens per model request;
- fewer hallucinated tool choices;
- clearer permission boundaries;
- IDE-only capabilities remain attached to IDE sessions rather than pretending to exist on every backend.

### 3.6 Coding posture is resolved once per session

Hermes has one `RuntimeMode` seam for coding vs general work. It detects the project, captures stable project facts, chooses coding guidance, optionally narrows toolsets, and freezes the decision for the session to protect caching.

It also detects real verify commands from manifests and lockfiles.

**Value to Scope:**

- the agent behaves like a coding agent automatically in a repository;
- no repeated project rediscovery every turn;
- exact package-manager and verification guidance;
- one source of truth shared by prompt, UI, model routing and verification.

### 3.7 Verification is evidence, not a sentence from the model

Hermes records terminal verification results in an evidence ledger with:

- command;
- workspace root;
- session;
- status;
- verification kind;
- full vs targeted scope;
- output summary;
- freshness relative to later edits.

When code changes after a passing test, the evidence becomes stale. The stop guard can continue the agent rather than accepting an unsupported “done.”

**Value to Scope:**

- IDE can show **Unverified / Stale / Passed / Failed** based on facts;
- users can inspect exactly what command passed;
- targeted tests are not misrepresented as the whole repository being green;
- false-success rate drops;
- verification survives UI refresh and process restart.

### 3.8 Approval is a pre-execution protocol with a real diff

Hermes ACP constructs an edit proposal before mutation, sends the client old and proposed text, waits for an explicit decision, and defaults to denial on timeout or requester failure. Approval policies are session-scoped and still protect sensitive paths.

**Value to Scope:**

- a denied edit cannot already have happened;
- native IDE diff review becomes part of execution, not decoration afterward;
- “allow once,” “accept workspace edits” and “don't ask” have clear policy meanings;
- approval cannot leak between concurrent sessions.

### 3.9 Interrupt, steer and queue are different operations

Hermes separates:

- **cancel** — stop current execution;
- **steer/redirect** — alter the active turn while preserving context;
- **queue** — run a separate prompt after the current turn.

It preserves provider message-role invariants while doing this.

**Value to Scope:** an IDE user can correct the agent immediately—“not that file,” “use the existing component,” “stop”—without waiting for a long run or losing the original task.

### 3.10 Tool execution is middleware, not direct function calling

Hermes has one execution pipeline for:

- scope checks;
- request rewrites;
- permission checks;
- safety guardrails;
- checkpoints;
- execution;
- result classification;
- persistence;
- UI/observability events.

Parallel batches are segmented so independent operations run concurrently while conflicting or interactive operations remain ordered.

**Value to Scope:** one place to enforce safety, telemetry, policy and durability across all tools. New tools cannot accidentally bypass approval or audit behavior.

### 3.11 Sub-agents have lifecycle contracts

Hermes models children as explicit handles with states such as pending, running, succeeded, failed, interrupted and cancelled. It supports status, wait, cancel and result retrieval with bounded metadata and permission narrowing.

**Value to Scope:** the IDE can render real parallel-agent jobs rather than blocking the parent tool call and returning a text blob. Users can monitor, stop and inspect each child independently.

### 3.12 The client/backend seam is a protocol

Hermes' ACP adapter supports:

- create/load/resume/fork/list sessions;
- prompt streaming;
- tool start/completion events;
- thought/reasoning events;
- permissions;
- model selection;
- modes;
- context usage;
- attachments;
- cancellation and steering;
- MCP registration.

**Value to Scope:** the agent is not trapped inside one custom panel. A protocol creates a durable product seam and makes compatibility testable.

## 4. Scope AI IDE Agent — recommended architecture

```text
┌──────────────────────── Scope AI IDE ─────────────────────────┐
│                                                              │
│  Renderer / Workbench                                         │
│  - chat transcript                                            │
│  - tool timeline                                              │
│  - native diff approvals                                      │
│  - verification status                                        │
│  - sub-agent jobs                                             │
│  - context/cost meter                                         │
│  - checkpoints                                                │
│                │ typed commands/events                        │
│                ▼                                              │
│  IDE Host Bridge                                              │
│  - starts/probes backend                                      │
│  - stdio/WebSocket transport                                  │
│  - workspace capability boundary                              │
│  - crash/reconnect policy                                     │
└────────────────┼─────────────────────────────────────────────┘
                 │ Scope Agent Protocol v1
                 ▼
┌──────────────────────── Agent Runtime ────────────────────────┐
│  Session Runtime                                              │
│  - turn lock, cancel, steer, queue                            │
│  - stable session identity + runtime lineage                  │
│  - iteration and retry budget                                 │
│                                                              │
│  Prompt Runtime                                               │
│  - stable session prefix                                      │
│  - volatile retrieved context                                 │
│  - provider/model adapter                                     │
│                                                              │
│  Tool Runtime                                                 │
│  - registry + task/session toolsets                           │
│  - middleware: scope → approval → checkpoint → execute        │
│  - parallel-safe segmentation                                 │
│                                                              │
│  Correctness Runtime                                          │
│  - mutation ledger                                            │
│  - verification evidence                                      │
│  - finish policy                                              │
│                                                              │
│  Coordination Runtime                                         │
│  - sub-agent launch/status/cancel/result                      │
└───────────────┬─────────────────────┬────────────────────────┘
                │                     │
                ▼                     ▼
        Durable State             Workspace Services
        - sessions.db             - files/search/index
        - evidence.db             - terminal/processes
        - checkpoints             - git/LSP/browser
        - memories/skills         - MCP integrations
```

## 5. Scope Agent Protocol v1

PulseAI's existing bridge is a useful start, but Scope should make the contract more stateful and IDE-native.

### Client → runtime commands

```text
initialize
session.create
session.load
session.resume
session.list
session.fork
turn.prompt
turn.cancel
turn.steer
turn.queue
permission.resolve
model.set
mode.set
checkpoint.restore
subagent.cancel
shutdown
```

### Runtime → client events

```text
session.info
turn.started
assistant.delta
reasoning.delta
plan.updated
tool.proposed
tool.started
tool.progress
tool.completed
permission.requested
workspace.changed
verification.updated
checkpoint.created
subagent.updated
usage.updated
turn.completed
turn.failed
runtime.degraded
```

Every event should carry at least:

```text
protocol_version
session_id
turn_id
event_id
timestamp
workspace_id
```

Tool events additionally need `tool_call_id`; sub-agent events need `subagent_id`; lineage changes need `runtime_session_id` and `lineage_root_id`.

## 6. What Scope should reuse from PulseAI

Do not throw away PulseAI. Keep the parts where it already creates strong value:

- LangGraph state and finish-gate logic;
- task-aware context engine;
- hybrid chunk retrieval;
- prompt-cache preservation concepts;
- request sanitizer;
- parallel-tool conflict detection;
- file-state guard;
- shadow checkpoints;
- model/provider abstraction;
- skill and persistent memory foundation;
- verification-oriented regression tests.

The correct move is to put these behind stronger runtime boundaries, not rebuild them inside the IDE.

## 7. What should change before Scope IDE integration

### P0 — Protocol and authority

1. Make the Python runtime the single source of session/tool state.
2. Replace the Flask/global-event-bus integration with a session-scoped protocol adapter.
3. Give every command/event stable IDs and replay semantics.
4. Persist events/tool intent before projecting them to the IDE.

### P0 — Real permission flow

1. Convert write/edit into edit proposals before mutation.
2. Send a native diff payload to the IDE.
3. Await `permission.resolve` with timeout and deny by default.
4. Keep approval policy scoped to the session/workspace.

### P0 — Verification evidence

1. Record actual terminal/build/test evidence.
2. Invalidate evidence after later edits.
3. Distinguish targeted from full verification.
4. Expose evidence to the IDE as structured state.

### P1 — Session control

1. Add hard cancel.
2. Add active-turn steer.
3. Add explicit next-turn queue.
4. Make session load/replay reconstruct the full tool timeline.

### P1 — Runtime simplification

1. Split `chat_graph.py` into runtime services/nodes.
2. Move graph/checkpointer creation into a runtime factory.
3. Replace process-global dashboard state with per-session/context-local state.
4. Keep a narrow tool middleware chokepoint.

### P2 — Managed sub-agents

1. Return a sub-agent handle immediately.
2. Stream lifecycle/status events.
3. Support cancellation.
4. Restrict children to a subset of parent capabilities.
5. Return structured results and usage.

## 8. The user-facing value of adding Scope AI IDE Agent

### Trust

Users see proposed edits before they land, know exactly what commands ran, and can distinguish verified work from model claims.

### Control

Users can stop, redirect or queue instructions while the agent works instead of waiting for a black-box turn to finish.

### Continuity

Sessions, tool history, plans, verification and checkpoints survive IDE and backend restarts.

### Speed

Stable prompt prefixes, narrower tool schemas, parallel reads and persisted project facts reduce repeated model and filesystem work.

### Correctness

Fresh evidence, post-edit invalidation, delivery gates and runtime checks reduce false “done” responses.

### Transparency

The IDE can show a structured execution timeline: plan → proposed action → approval → tool result → verification → completion.

### Extensibility

A protocol and middleware waist allow future MCP tools, providers, remote runtimes and clients without rewriting the core agent.

### Differentiation

The moat is not another chat sidebar. It is a **durable engineering agent inside the IDE** that users can supervise, interrupt, verify and resume.

## 9. Avoid copying these Hermes costs

Hermes also demonstrates the cost of success: its conversation and tool-executor modules are extremely large. Scope should capture the invariants without recreating that scale.

Do not copy:

- every provider-specific workaround on day one;
- every messaging platform;
- voice, cron, cloud and general-assistant surfaces;
- giant single-file loops;
- broad plugin infrastructure without two real consumers;
- unrelated desktop capabilities.

Use Hermes as a **failure-knowledge source**, not as a code template.

## 10. The best first milestone

Build one vertical slice:

> In Scope IDE, ask the agent to modify one existing code file; show the proposed native diff; approve it; persist the edit and tool timeline; run the detected project verification command; display fresh evidence; restart the backend; reload the session with the complete transcript and verification state.

This slice proves the architecture's most valuable properties:

- IDE/backend boundary;
- durable state;
- real approval;
- workspace correctness;
- verification evidence;
- restart recovery.

Do this before broadening the UI or adding more tools.

## Final conclusion

Hermes' main value is not “more agent features.” It is the set of invariants that turn model output into a dependable product:

- one authority per state;
- durable intent before side effects;
- stable prompt prefixes;
- narrow tool surfaces;
- pre-execution approval;
- evidence-based completion;
- explicit session and sub-agent lifecycles;
- interruptible work;
- a protocol between agent and client.

Adding these ideas to the Scope AI IDE Agent changes the product from **an AI chat panel that can edit files** into **a supervised, recoverable and verifiable software-engineering runtime embedded in an IDE**.
