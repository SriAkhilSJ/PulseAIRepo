# PHASE 12.1 DESKTOP EXECUTION ARCHITECTURE
## Unified Entry Point & Desktop-to-Orchestrator Execution Bridge

**Date:** 2026-11-06  
**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Status:** COMPLETE & VERIFIED

---

### 1. Executive Summary

In Phase 12.0.1, the audit identified that the desktop application had an architectural bifurcation:
- **Desktop Chat / Prompt Path:** Dispatched from the desktop UI to `src/bridge/__main__.py`, which unconditionally delegated to `chat_graph.py:stream_agent` and legacy LangGraph tools.
- **Engineering Intelligence System (Phases 11.0–11.8):** Encompassed 15 lifecycle stages in `EngineeringExecutionOrchestrator`, but was only exercised through unit and synthetic tests in isolation.

Phase 12.1 Part 2 unified this execution path. The Crusor Python bridge now houses a single authoritative execution router that distinguishes conversational exploration (`ask` mode) from autonomous engineering execution (`agent` and `plan` modes), dispatching engineering tasks directly into `EngineeringExecutionOrchestrator`.

---

### 2. Unified Execution Flow

```
+-------------------------------------------------------------+
|                 Desktop UI (VSCode / Webview)               |
+-------------------------------------------------------------+
                              | JSON-RPC Prompt Frame ("mode": "agent" | "ask")
                              v
+-------------------------------------------------------------+
|             Bridge Worker Process (src/bridge/__main__.py)  |
+-------------------------------------------------------------+
                              |
               +--------------+--------------+
               | Mode Dispatch               |
               v                             v
       [ mode == "ask" ]             [ mode in ("agent", "plan") ]
               |                             |
      Conversational Q&A             Autonomous Engineering
               |                             |
    stream_agent(chat_graph)                 v
                               +-------------------------------------+
                               |   EngineeringExecutionOrchestrator  |
                               +-------------------------------------+
                                                 |
         +---------------------------------------+---------------------------------------+
         |                                       |                                       |
         v                                       v                                       v
[1. Request Intelligence]             [2. Repo Intelligence]                  [3. Architecture Blueprint]
  • RequirementSystem                   • ProjectIntelligence                   • ArchitectureSystem
         |                                       |                                       |
         +---------------------------------------+---------------------------------------+
                                                 |
                                                 v
                               +-------------------------------------+
                               |   4. Task Planning DAG & Blast Radius|
                               |      EngineeringTaskPlanner & Impact |
                               +-------------------------------------+
                                                 |
                                                 v
                               +-------------------------------------+
                               |   5. Pre-Change Test Baseline       |
                               |      RegressionPreventionEngine     |
                               +-------------------------------------+
                                                 |
                                                 v
                               +-------------------------------------+
                               |   6. Controlled Model Implementation|
                               |      ModelExecutionAdapter & FinOps |
                               +-------------------------------------+
                                                 |
                                                 v
                               +-------------------------------------+
                               |   7. Workspace Discipline Broker    |
                               |      WorkspaceMutationBroker        |
                               +-------------------------------------+
                                                 |
                                                 v
                               +-------------------------------------+
                               |   8. Post-Change Test & Diagnostics |
                               |      FailureDiagnosis & Recovery    |
                               +-------------------------------------+
                                                 |
                                                 v
                               +-------------------------------------+
                               |   9. Independent Verification       |
                               |      IndependentVerificationEngine  |
                               +-------------------------------------+
                                                 |
                                                 v
                               +-------------------------------------+
                               |  10. Production Readiness Assessment|
                               |      ProductionReadinessEngine      |
                               +-------------------------------------+
                                                 |
                                                 v
                               +-------------------------------------+
                               |  11. Truthful Delivery Contract     |
                               |      turn_lifecycle, token, done    |
                               +-------------------------------------+
                                                 |
                                                 v
                              +--------------------------------------+
                              |   Desktop UI Display & Ledger Review |
                              +--------------------------------------+
```

---

### 3. Implementation Details in `src/bridge/__main__.py`

In `_run_turn(sid, text, workspace, mode, reasoning_effort)`:
1. **Mode Routing:**
   ```python
   use_orchestrator = (
       mode in ("agent", "plan")
       and os.environ.get("CRUSORAI_ORCHESTRATOR_ENGINE", "orchestrator").lower() != "legacy"
   )
   ```
2. **Orchestrator Execution:**
   - Instantiates `EngineeringExecutionOrchestrator(workspace_root=workspace, tenant_id=...)`.
   - Binds `on_orch_progress` callback translating `DesktopVisibilityReporter` state snapshots into desktop protocol frames (`turn_lifecycle`, `plan_updated`).
   - Forwards cancellation signal `lambda: turn_controls.cancelled(sid)` down through each wave of execution.
3. **Truthful Outcome Delivery:**
   - Extracts the authoritative `DeliveryContract`.
   - Emits an engineering report token block detailing files changed, tests passed/failed, independent verification status, and production readiness verdict.
   - Dispatches `verification_updated` frame with cryptographic evidence digest.
   - Emits `turn_done` reflecting actual task success (`completed = delivery.verdict == TaskVerdict.COMPLETED`).

---

### 4. Cancellation & State Synchronization

- If the user presses "Stop" in the desktop UI, `kind == "cancel"` invokes `turn_controls.cancel(sid)`.
- During execution, the cancellation check is evaluated:
  - At turn initialization.
  - Prior to each lifecycle stage.
  - Inside `ModelExecutionAdapter` before model calls.
  - In `DependencyAwareScheduler` between waves.
- When cancelled, the state machine transitions to `TaskExecutionState.CANCELLED`, the event journal logs `TASK_CANCELLED`, and a cancellation delivery contract is emitted without leaving orphan files or dirty uncommitted mutations.

---

### 5. Architectural Verification

The unified architecture was verified using automated regression tests:
- `test_bridge.py`: 48 tests passed (protocol handshake, frame encoding, echo runner, session isolation).
- `test_run_bridge_turn.py`: 9 tests passed (turn execution, lifecycle tracking, terminal receipts).
- `test_phase_12_1_end_to_end_acceptance.py`: Tests A, B, C, D, and E all passed.

