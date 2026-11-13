# Crusor AI IDE — Phase 12.0.1
# SUBSYSTEM INTEGRATION MATRIX

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Audit Date:** November 6, 2026  
**Methodology:** Direct AST & Code Execution Inspection  

---

## 1. Classification Definitions

- **`VERIFIED_INTEGRATED`**: Invoked in production execution paths, output consumed downstream, security controls actively enforced, failures propagated, progress visible in desktop UI.
- **`PARTIALLY_INTEGRATED`**: Invoked in some execution paths (e.g. `EngineeringExecutionOrchestrator`), but disconnected from desktop UI/bridge or bypassed by legacy alternatives.
- **`DISCONNECTED`**: Module exists and has passing unit tests, but is never invoked by any orchestrator, bridge handler, or tool execution node in the system.
- **`BROKEN`**: Invoked in runtime paths, but throws unhandled exceptions, causes deadlock, or fails core contract assertions.
- **`NOT_TESTED`**: Present in codebase without executable unit or integration test coverage.

---

## 2. Comprehensive Subsystem Audit Matrix

| # | Subsystem | Classification | Invoking Component | Downstream Consumers | Security Controls Enforced? | Failure Propagation | Bypassable Paths? | Desktop UI Visibility |
|---|---|---|---|---|---|---|---|---|
| **1** | **Project Intelligence** (Phase 11.0) | `PARTIALLY_INTEGRATED` | `EngineeringExecutionOrchestrator` (`src/orchestration/orchestrator.py:85`) | `EngineeringTaskPlanner`, `ChangeImpactAnalysisEngine` | Yes (Path traversal, sensitive file exclusion) | Yes (Logs and falls back to blank scan) | Yes (Desktop `chat_graph` path uses `ConventionLearner` instead) | ❌ No (Desktop receives no project intelligence cards) |
| **2** | **Requirement Intelligence** (Phase 11.1) | `PARTIALLY_INTEGRATED` | `EngineeringExecutionOrchestrator` (`src/orchestration/orchestrator.py:87`) | `EngineeringTaskPlanner`, `ChangeImpactAnalysisEngine`, `IndependentVerificationEngine` | Yes (Input sanitization, priority validation) | Yes (Returns blocking clarification questions) | Yes (Desktop `chat_graph` uses legacy `clarify_tool.py` and `planner.py`) | ❌ No (No requirement extraction cards in desktop UI) |
| **3** | **Architecture Intelligence** (Phase 11.2) | `PARTIALLY_INTEGRATED` | `EngineeringExecutionOrchestrator` (`src/orchestration/orchestrator.py:88`) | `EngineeringTaskPlanner`, `IndependentVerificationEngine` | Yes (ADR lifecycle & immutability checks) | Yes (Returns error if architecture synthesis fails) | Yes (Desktop `chat_graph` has no architecture synthesis step) | ❌ No (No ADR or blueprint panels rendered) |
| **4** | **Workspace Discipline & Mutation Broker** (Phase 11.3) | `PARTIALLY_INTEGRATED` | `ControlledImplementationEngine` (`src/orchestration/implementation_engine.py:46`) | `ChangeChangeLedger`, `RegressionPreventionEngine` | Yes (Path safety, user file overwrite protection, rollback) | Yes (`MutationAuthorizationError`, `ConcurrencyConflictError`) | ⚠️ **CRITICAL BYPASS:** `src/tools/file_tools.py` in `chat_graph` writes directly to disk without broker | ❌ No (Broker ledger events not forwarded to desktop UI) |
| **5** | **Change Impact Analysis** (Phase 11.4) | `PARTIALLY_INTEGRATED` | `EngineeringExecutionOrchestrator` (`src/orchestration/orchestrator.py:90`) | `RegressionPreventionEngine`, `IndependentVerificationEngine` | Yes (Read-only dependency graph traversal) | Yes (Raises on syntax failure, falls back safely) | Yes (Desktop `chat_graph` executes tools with no blast-radius check) | ❌ No (No blast-radius visualization in desktop UI) |
| **6** | **Regression Prevention Engine** (Phase 11.5) | `PARTIALLY_INTEGRATED` | `EngineeringExecutionOrchestrator` (`src/orchestration/orchestrator.py:91`) | `TaskStateMachine`, `IndependentVerificationEngine` | Yes (Baseline isolation, test execution timeout) | Yes (`RegressionDetected` triggers Stage 12/13 correction) | Yes (Desktop `chat_graph` uses legacy `gates.py` regex heuristics) | ❌ No (Only generic test failure strings, no regression reports) |
| **7** | **Autonomous Engineering Execution** (Phase 11.6) | `PARTIALLY_INTEGRATED` | Only invoked by unit test fixtures (`test_phase_11_6_*.py`) | `IndependentVerificationEngine`, `DeliveryContract` | Yes (Execution limits, timeout guards, supervision gates) | Yes (Halts on unresolvable node failure) | Yes (Desktop users cannot trigger this orchestrator) | ❌ No (`DesktopVisibilityReporter` views are not wired to IPC) |
| **8** | **Independent Verification Authority** (Phase 11.7) | `PARTIALLY_INTEGRATED` | `EngineeringExecutionOrchestrator` (`src/orchestration/orchestrator.py:98`) | `DeliveryContract` (`run_task` finalization) | Yes (Authority separation, taint detection, invalidation) | Yes (Returns `REJECTED`, marks `TaskVerdict.FAILED`) | Yes (Desktop `chat_graph` uses legacy 4-state receipt from `gates.py`) | ❌ No (Independent audit digests not displayed in UI) |
| **9** | **Production Readiness Engine** (Phase 11.8) | `DISCONNECTED` | **NONE** (Only in `test_phase_11_8_production_readiness.py`) | None | N/A (Never executed in live pipeline) | N/A | Yes (Completely uninvoked) | ❌ No |
| **10** | **Identity and Tool RBAC** (Phase 10.0) | `DISCONNECTED` | **NONE** (Only in `test_phase_10_0_enterprise_identity_rbac.py`) | None | N/A (Not hooked into tool nodes) | N/A | Yes (All tool execution paths bypass `IdentityAwareToolAuthorizer`) | ❌ No |
| **11** | **FinOps Cost & Token Governance** (Phase 9.7) | `PARTIALLY_INTEGRATED` | `src/finops/` package is DISCONNECTED. `chat_graph` uses `cost_governance.py`; `orchestrator` uses `finops_governor.py` | `AdaptiveContextManager`, `DeliveryContract` | Partial (Local hard budget gate in `finops_governor.py`) | Yes (`BudgetExhaustedError`) | Yes (`src/finops` pricing registry not used in live orchestrator) | Partial (Desktop displays token count and dollar cost via `telemetry` frames) |
| **12** | **MCP and Browser Agent Integration** (Phase 9.5) | `PARTIALLY_INTEGRATED` | `src/graphs/chat_graph.py` (`tool_node`) | `chat_graph` message state | Yes (`MCPContentGuard`, `SecurityGuard`) | Yes (Wrapped in `ToolMessage` with status="error") | Yes (`EngineeringExecutionOrchestrator` does NOT bind MCP/Browser tools) | Partial (Tool progress and browser screenshots rendered) |
| **13** | **Desktop Visibility & Progress Reporting** | `PARTIALLY_INTEGRATED` | `src/orchestration/visibility.py` (Local unit tests); `src/bridge/__main__.py` (Chat events) | Desktop renderer | Yes (Sensitive tokens redacted) | Partial | Yes (`DesktopVisibilityReporter` is not wired to bridge) | Partial (Chat frames work, but Phase 11 engineering progress views do not) |

---

## 3. Subsystem Detailed Findings

### 3.1 Project Intelligence (`src/intelligence/discovery.py`)
- **Invocation Evidence:** `EngineeringExecutionOrchestrator.run_task()` calls `self.discovery_mgr.get_project_knowledge()` at Stage 3 (`TaskLifecycleStage.PROJECT_DISCOVERY`).
- **Data Flow:** Returns `ProjectKnowledge` containing language breakdown, frameworks, database types, architecture patterns, and entrypoints. Passed to `planner.build_plan` and `impact_engine.analyze_proposed_changes`.
- **Integration Gap:** `src/bridge/__main__.py` and `chat_graph.py` do not call this engine. When a user chats in the IDE, context is scanned via `ConventionLearner` and `ContextEngine` instead.

### 3.2 Requirement Intelligence (`src/intelligence/requirement_integration.py`)
- **Invocation Evidence:** Invoked at Stage 2 (`REQUEST_UNDERSTANDING`) via `self.req_system.analyze_request(task_prompt, ...)` in `orchestrator.py:153`.
- **Data Flow:** Generates `ProjectSpecification` containing structured functional requirements, non-functional requirements, and potential decisions. Passed to DAG planner, impact engine, and verification engine.
- **Integration Gap:** Missing connection to the desktop UI clarification dialog (`crusorAIHubDialog.ts`). If critical ambiguities are detected, `orchestrator.py:175` auto-resolves with default options rather than halting for an interactive user reply over IPC.

### 3.3 Architecture Intelligence (`src/intelligence/architecture_integration.py`)
- **Invocation Evidence:** Invoked at Stage 5 (`ARCHITECTURE_VALIDATION`) via `self.arch_system.synthesize_architecture(...)` in `orchestrator.py:197`.
- **Data Flow:** Produces `ArchitectureBlueprint` with ADRs, technology stack selection, and component architecture map. Consumed by DAG planner and verification engine.
- **Integration Gap:** Disconnected from the desktop UI. Users cannot review alternative architectures or approve ADRs from the desktop panel.

### 3.4 Workspace Discipline (`src/workspace/mutation_broker.py`)
- **Invocation Evidence:** `ControlledImplementationEngine` in `orchestrator.py:95` wraps `WorkspaceMutationBroker`.
- **Data Flow:** Validates file targets, verifies permissions, records SHA256 before/after hashes in `WorkspaceChangeLedger`, and appends events to `WorkspaceJournal`.
- **CRITICAL GAP:** `src/tools/file_tools.py` (`write_file`, `edit_file`) is the tool module bound to `chat_graph.py`. `write_file` and `edit_file` perform direct `open()` and `Path.write_text()` operations, completely bypassing `WorkspaceMutationBroker`. Any interactive agent action in the IDE operates unbrokered!

### 3.5 Change Impact Analysis (`src/impact/engine.py`)
- **Invocation Evidence:** Invoked at Stage 7 (`CHANGE_IMPACT_ANALYSIS`) via `self.impact_engine.analyze_proposed_changes(...)` in `orchestrator.py:227`.
- **Data Flow:** Traverses the multi-level dependency graph to compute blast radius, impacted components, and risk classification (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`). Passed to `RegressionPreventionEngine` and `IndependentVerificationEngine`.
- **Integration Gap:** Unused in interactive chat execution.

### 3.6 Regression Prevention Engine (`src/regression/engine.py`)
- **Invocation Evidence:** Invoked at Stage 8 (`TEST_BASELINE`) to capture initial test baseline, and Stage 11 (`BUILD_AND_TEST_EXECUTION`) to evaluate post-change tests against baseline.
- **Data Flow:** Outputs `RegressionReport` categorizing regressions into `NEW_REGRESSION`, `PRE_EXISTING_FAILURE`, and `FLAKY`. Triggers Stage 12/13 correction loop if regressions exist.
- **Integration Gap:** `chat_graph.py` does not run baseline testing before mutations; it only runs verification nudges after mutations have already landed.

### 3.7 Autonomous Execution (`src/orchestration/orchestrator.py`)
- **Invocation Evidence:** Runs all 15 stages in `test_phase_11_6_autonomous_execution.py`.
- **Integration Gap:** Never imported or instantiated in `src/bridge/` or `src/graphs/`.

### 3.8 Independent Verification (`src/verification/engine.py`)
- **Invocation Evidence:** Invoked at Stage 14 via `self.verification_engine.verify_task(...)` in `orchestrator.py:363`.
- **Data Flow:** Independent authority evaluates requirement satisfaction, architectural conformance, test integrity (detecting empty/tautological tests), and regression reports. Returns `VerificationReport`.
- **Integration Gap:** Completely absent from `src/graphs/chat_graph.py`, which relies on regex pattern checks in `src/graphs/gates.py`.

### 3.9 Production Readiness Engine (`src/production/engine.py`)
- **Invocation Evidence:** **ZERO RUNTIME INVOCATIONS.**
- **Integration Gap:** `EngineeringExecutionOrchestrator.run_task()` does NOT include Production Readiness as a lifecycle stage. The engine lives as dead/isolated code outside the 70 unit tests in `test_phase_11_8_production_readiness.py`.

### 3.10 Identity and Tool RBAC (`src/identity/tool_authorizer.py`)
- **Invocation Evidence:** **ZERO RUNTIME INVOCATIONS.**
- **Integration Gap:** `IdentityAwareToolAuthorizer` has methods `authorize_tool_call()` and `validate_session_access()`, but neither `SafeToolNode` nor `ControlledImplementationEngine` registers or queries this authorizer.

### 3.11 FinOps Governance (`src/finops/` vs `src/orchestration/finops_governor.py`)
- **Invocation Evidence:** `OrchestrationFinOpsGovernor` is invoked in `orchestrator.py`.
- **Integration Gap:** `OrchestrationFinOpsGovernor` does not import or use the enterprise `src/finops` engine (`TokenAccountingEngine`, `ModelPricingRegistry`, `BudgetGovernor`). It uses a standalone local dataclass.

### 3.12 MCP and Browser Agent (`src/tools/mcp_tool.py`, `src/tools/browser_tools.py`)
- **Invocation Evidence:** Registered in `chat_graph.py` tool catalog.
- **Integration Gap:** Not integrated into `EngineeringExecutionOrchestrator`.

### 3.13 Desktop Visibility (`src/orchestration/visibility.py`)
- **Invocation Evidence:** `DesktopVisibilityReporter.compute_view()` is called in `orchestrator.py:130`.
- **Integration Gap:** Callback emissions are consumed only by test assertions; no bridge handler translates `DesktopTaskProgressView` into desktop JSON-RPC frames.

---

## 4. Integration Summary

- **Total Subsystems Audited:** 13
- **VERIFIED_INTEGRATED:** 0 (0%)
- **PARTIALLY_INTEGRATED:** 11 (84.6%)
- **DISCONNECTED:** 2 (15.4%)
- **BROKEN:** 0 (0%)
- **NOT_TESTED:** 0 (0%)

**Conclusion:** The engineering intelligence subsystems are internally cohesive and function properly in test harnesses, but are disconnected from the primary desktop execution path.

