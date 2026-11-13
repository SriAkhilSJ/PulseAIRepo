# Crusor AI IDE — Phase 12.0.1
# DESKTOP TO AGENT INTEGRATION REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Audit Date:** November 6, 2026  
**Focus Area:** Frontend Desktop Shell, IPC Bridge, and Protocol Synchronization  

---

## 1. Desktop Shell Architecture

Crusor AI is built as a canonical in-place fork of Code OSS (`desktop/vscode/`). The AI assistant is integrated into the core editor chrome rather than being an extension:

- **Core Contribution Entry:** `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAI.contribution.ts`.
- **Workbench Service:** `ICrusorAIWorkbenchService` registered as a singleton managing active sessions, message queues, and engine lifecycles.
- **Worker Process Sidecar:** `CrusorAIWorkerProcessService` (`node/crusorAIWorkerProcessService.ts`) runs in the Node utility process. It discovers the Python environment, resolves the engine repository root, and spawns `python -m src.bridge` with stdio readline streams.
- **Renderer UI:** `crusorAIRenderer.ts` and `crusorAIRendererService.ts` render the chat pane, cards, tool call progress bars, code diff previews, and approval prompts.

```
+-----------------------------------------------------------------------------------------+
|                                    CRUSOR DESKTOP IDE                                   |
|                                                                                         |
|  +------------------------+  +-------------------------------------------------------+  |
|  |     CRUSOR AI PANE     |  |                    EDITOR WORKBENCH                   |  |
|  |                        |  |                                                       |  |
|  | [ Prompt Input Area ]  |  |  +-------------------------------------------------+  |  |
|  | [ Activity Dot / State]|  |  | file.py                                         |  |  |
|  | [ Clarification Cards ]|  |  |                                                 |  |  |
|  | [ Tool Progress Cards ]|  |  |                                                 |  |  |
|  | [ Diff Preview Card ]  |  |  +-------------------------------------------------+  |  |
|  +------------------------+  +-------------------------------------------------------+  |
|               |                                          ^                              |
|               v                                          |                              |
|     crusorAIWorkbenchService                             |                              |
|               |                                          |                              |
|               v                                          |                              |
|    CrusorAIWorkerProcessService (Node utility process)   |                              |
+---------------+------------------------------------------+------------------------------+
                |
                | stdio JSON-RPC (newline-delimited frames)
                v
+-----------------------------------------------------------------------------------------+
|                                  PYTHON ENGINE SIDECAR                                  |
|                                                                                         |
|  src/bridge/__main__.py (Main Thread: Frame Loop; Worker Thread: _run_turn)             |
|        |                                                                                |
|        +---> stream_agent() (src/graphs/chat_graph.py)                                  |
|                 |                                                                       |
|                 +---> SafeToolNode (write_file, edit_file, terminal)                    |
|                 +---> LangGraph Checkpointer (SqliteSaver ~/.crusorai/sessions.db)       |
+-----------------------------------------------------------------------------------------+
```

---

## 2. IPC Protocol Analysis (`src/bridge/protocol.py` vs `crusorAIProtocol.ts`)

The IPC communication between the TypeScript desktop client and Python engine is governed by Protocol Version 2:

### Client -> Engine Methods (`CrusorClientMethod`)
- `hello`: Handshake verifying protocol version (Version 2).
- `session_create`, `session_load`, `session_resume`, `session_list`, `session_fork`, `session_delete`.
- `prompt`: Submits user instruction (`text`, `mode` in `["agent", "plan", "debug", "ask"]`, `reasoning_effort`).
- `cancel`: User aborts the turn.
- `steer`, `queue`: Nudges or queues instructions while turn is active.
- `safety_reply`: User confirms or denies dangerous tool execution (`tool_id`, `approved`, `always_allow`).
- `clarify_reply`: Answers ambiguity clarification questions (`request_id`, `answers`).
- `subagent_launch`, `subagent_status`, `subagent_cancel`.

### Engine -> Client Events (`CrusorServerEvent`)
- `hello`, `session_info`, `session_messages`.
- `turn_started`, `turn_done`, `turn_failed`, `turn_lifecycle`.
- `token`, `token_retract`, `reasoning` (streaming LLM thoughts).
- `tool_call_start`, `tool_call_args`, `tool_call_progress`, `tool_call_end`, `tool_output`.
- `plan_updated`, `todo_updated`.
- `safety_request`, `clarify_request`.
- `verification_updated` (carrying legacy 4-state verification strings).
- `telemetry` (token count and estimated cost).

---

## 3. The Desktop-to-Agent Gap

### Gap 1: Bridge Exclusively Targets Legacy `chat_graph`
In `src/bridge/__main__.py:1126-1169`, prompt dispatch is hardcoded to:
```python
from src.graphs.chat_graph import stream_agent
result = stream_agent(
    text, thread_id=sid, workspace=workspace,
    approval_channel=True,
    approval_policy=approval_policy,
    turn_id=identity.turn_id,
    execution_mode=mode,
    reasoning_effort=reasoning_effort,
)
```
There is no branch or execution flag to route requests to `EngineeringExecutionOrchestrator`. As a result, the entire Phase 11 stack is uncallable from the desktop UI.

### Gap 2: Desktop Protocol Cannot Represent Phase 11 Intelligence Artifacts
Even if the bridge were to invoke `EngineeringExecutionOrchestrator`, the desktop IPC protocol lacks the message types required to transmit:
- Architectural Decision Records (`ADR`).
- Architecture Blueprints (`ArchitectureBlueprint`).
- Blast Radius and Dependency Graphs (`ChangeImpactReport`).
- Pre-change vs. Post-change Test Baselines (`TestBaseline`).
- Regression Classification Reports (`RegressionReport`).
- Independent Verification Authority Audit Digests (`VerificationReport`).
- Production Readiness Gates and Remediation Plans (`ProductionReadinessReport`).
- Delivery Contracts (`DeliveryContract`).

The desktop currently only knows how to display flat `plan_updated` checklists, `todo_updated` items, and single-string `verification_updated` status.

### Gap 3: Stale Compiled Workbench Warning
When `src/bridge/__main__.py` starts, it performs a manifest check between the committed source files and the transpiled desktop bundle:
```
[bridge] DESKTOP WORKBENCH STALE: the shipped panel was emitted from DIFFERENT crusorai sources than this checkout (sha256 e7f9f650588c… != 6d3594d3ab3c…) — the Agent pane will render OLD cards no matter what the engine runs.
[bridge] STALE diagnosis: every manifest file matches — the drift is in tree membership or the emitter itself; re-run `node scripts/emit-crusorai-bundle.mjs` in desktop/vscode and reopen.
```
This indicates that the tracked transpiled bundle under `desktop/vscode/out/vs/workbench/contrib/crusorai/**` has drifted from the TypeScript source files and must be recompiled.

---

## 4. Verification of Desktop Human-in-the-Loop Controls

| Control | Protocol Frame | Desktop UI Behavior | Python Engine Handler | Audit Finding |
|---|---|---|---|---|
| **Clarification** | `clarify_request` / `clarify_reply` | Shows interactive radio/checkbox card in chat | `clarify_queue.resolve()` in `src/dashboard/event_bus.py` | Works in `chat_graph`, but `EngineeringExecutionOrchestrator` auto-resolves with defaults |
| **Tool Approval** | `safety_request` / `safety_reply` | Displays diff card with "Approve" / "Deny" buttons | `approval_queue.resolve()` in `src/dashboard/event_bus.py` | Works in `chat_graph`, but `EngineeringExecutionOrchestrator` uses `HumanSupervisionGate` |
| **Turn Cancellation** | `cancel` | "Stop" button in chat input | `turn_controls.cancel(sid)` sets threading Event | Verified working in bridge |
| **Instruction Steer** | `steer` | Injects prompt into active turn | `turn_controls.steer()` appends to queue | Verified working in bridge |

---

## 5. Summary

The desktop interface and its IPC bridge represent an advanced, highly responsive UI capable of streaming tokens, reasoning blocks, diff cards, and interactive human approvals. However, **it is wired exclusively to the legacy conversational `chat_graph` pipeline**. To achieve the Phase 12 vision of a unified autonomous software engineering product, the bridge protocol must be extended to support Phase 11 engineering events, and the turn worker must route tasks to `EngineeringExecutionOrchestrator`.

