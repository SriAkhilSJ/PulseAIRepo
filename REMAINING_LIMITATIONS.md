# Crusor AI IDE — Phase 12.0.1
# REMAINING LIMITATIONS REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Audit Date:** November 6, 2026  
**Status:** Comprehensive Catalog of Technical Debt, Architectural Bifurcation, and Gaps  

---

## 1. Executive Summary

This document details the complete inventory of remaining limitations, technical debt, and architectural bottlenecks identified during the Phase 12.0.1 Engineering Intelligence Integration Audit. 

These limitations must be systematically addressed in Phase 12.1 before Crusor AI can be certified as a unified autonomous engineering product.

---

## 2. Inventory of Remaining Limitations

### Limitation 1: Complete Desktop Disconnection of Phase 11 Stack
- **Impact:** `CRITICAL`
- **Description:** The primary desktop user interface communicates exclusively with `src/graphs/chat_graph.py` via `src/bridge/__main__.py`. The entire Phase 11 Engineering Intelligence stack (`EngineeringExecutionOrchestrator`, `RequirementIntelligenceSystem`, `ArchitectureIntelligenceSystem`, `ChangeImpactAnalysisEngine`, `RegressionPreventionEngine`, `IndependentVerificationEngine`) is completely uncallable from the desktop.
- **Root Cause:** `src/bridge/__main__.py:1126` directly imports and executes `chat_graph.stream_agent` without an option or routing layer to invoke `EngineeringExecutionOrchestrator`.

---

### Limitation 2: Mutation Broker Bypass in Interactive File Tools
- **Impact:** `CRITICAL`
- **Description:** When an agent modifies or creates files during a desktop session, it invokes `src/tools/file_tools.py` (`write_file`, `edit_file`). These tools perform direct filesystem mutations, completely bypassing `src/workspace/mutation_broker.py:WorkspaceMutationBroker`.
- **Consequences:**
  - File ownership rules are not enforced.
  - User-owned files can be silently overwritten without approval tokens.
  - No cryptographic SHA256 hashes are recorded in `WorkspaceChangeLedger`.
  - No automatic rollback snapshots are created.

---

### Limitation 3: Orphaned Phase 11.8 Production Readiness Engine
- **Impact:** `HIGH`
- **Description:** `ProductionReadinessEngine` (`src/production/engine.py`) is fully implemented with 70 unit tests, but is not integrated into `EngineeringExecutionOrchestrator.run_task()`.
- **Consequences:** Stage 14 is absent from the active orchestrator. Tasks finalize and deliver without performing security readiness scanning, reliability assessment, rollback script generation, or dependency supply chain analysis.

---

### Limitation 4: Unenforced Identity & Tool RBAC
- **Impact:** `HIGH`
- **Description:** `IdentityAwareToolAuthorizer` (`src/identity/tool_authorizer.py`) implements role hierarchies and tool gating, but is not connected to `SafeToolNode` (`chat_graph.py`) or `ControlledImplementationEngine` (`orchestrator.py`).
- **Consequences:** All tool executions run with ambient process permissions. Role-based restrictions (e.g. preventing guests from modifying build configurations or executing shell scripts) are completely inactive.

---

### Limitation 5: Synthetic Stubs in Default Orchestration Executor
- **Impact:** `HIGH`
- **Description:** In `EngineeringExecutionOrchestrator.run_task()`, `default_executor()` writes hardcoded python functions (`def {node_id}_handler(): return 'OK'`) instead of invoking an LLM model provider to write real code.
- **Consequences:** While the orchestrator passes DAG scheduling and broker mutation tests, it cannot autonomously generate functional production software without an external caller injecting a custom LLM executor callback.

---

### Limitation 6: Desktop Protocol Version 2 Semantic Inadequacy
- **Impact:** `MEDIUM`
- **Description:** The IPC protocol between the desktop and the Python engine (`src/bridge/protocol.py` and `crusorAIProtocol.ts`) lacks event schemas for Phase 11 intelligence artifacts:
  - No event for `ArchitectureBlueprint` or ADR records.
  - No event for `ChangeImpactReport` (blast radius).
  - No event for `RegressionReport` (baseline vs post-change diff).
  - No event for `VerificationReport` (independent audit digest).
  - No event for `DeliveryContract`.
- **Consequences:** Even if the orchestrator were wired to the bridge, the desktop UI has no cards or panels to render these engineering intelligence results.

---

### Limitation 7: FinOps Engine Triplication
- **Impact:** `MEDIUM`
- **Description:** Three disconnected financial governance systems exist in parallel:
  1. `src/finops/` (Enterprise pricing, credit ledgers, multi-model router).
  2. `src/agents/cost_governance.py` (Context token tracking in `chat_graph`).
  3. `src/orchestration/finops_governor.py` (Ad-hoc local struct in `orchestrator.py`).
- **Consequences:** Model pricing updates, cached token discount rules, and enterprise credit allocations must be duplicated across three separate codebases.

---

### Limitation 8: Stale Shipped Workbench Transpilation Bundle
- **Impact:** `MEDIUM`
- **Description:** `src/bridge/__main__.py` detects that the tracked transpiled bundle under `desktop/vscode/out/vs/workbench/contrib/crusorai/**` has drifted from the committed TypeScript source files.
- **Consequences:** The desktop Agent pane renders older UI component layouts until `node scripts/emit-crusorai-bundle.mjs` is executed.

---

## 3. Prioritized Remediation Roadmap (Phase 12.1)

| Priority | Task ID | Remediation Objective | Target Files |
|---|---|---|---|
| **P0** | `REM-01` | Intercept all desktop file mutations through `WorkspaceMutationBroker` | `src/tools/file_tools.py`, `src/workspace/mutation_broker.py` |
| **P0** | `REM-02` | Wire `EngineeringExecutionOrchestrator` into bridge turn worker | `src/bridge/__main__.py`, `src/orchestration/orchestrator.py` |
| **P1** | `REM-03` | Add Stage 14 `PRODUCTION_READINESS` to `orchestrator.py:run_task()` | `src/orchestration/orchestrator.py`, `src/production/engine.py` |
| **P1** | `REM-04` | Hook `IdentityAwareToolAuthorizer` into tool execution | `src/graphs/chat_graph.py`, `src/orchestration/implementation_engine.py` |
| **P2** | `REM-05` | Replace synthetic `default_executor` stub with LLM factory generation | `src/orchestration/orchestrator.py`, `src/llm/factory.py` |
| **P2** | `REM-06` | Extend Protocol v2 with engineering intelligence frame types | `src/bridge/protocol.py`, `crusorAIProtocol.ts` |
| **P3** | `REM-07` | Unify FinOps tracking to consume `src/finops/pricing_registry.py` | `src/orchestration/finops_governor.py`, `src/finops/` |
| **P3** | `REM-08` | Re-emit fresh desktop workbench bundle | `desktop/vscode/` |

