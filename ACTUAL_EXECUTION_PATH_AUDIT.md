# Crusor AI IDE — Phase 12.0.1
# ACTUAL EXECUTION PATH AUDIT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Audit Date:** November 6, 2026  
**Scope:** Stage-by-Stage Verification of the 15-Stage Engineering Pipeline Against Real Executable Code  

---

## 1. Overview of Execution Paths

The audit traced the complete execution path from initial user prompt submission to final result presentation. Two distinct execution paths were analyzed:

1. **Path A (The Shipped Desktop Path):** The path actually executed when a user enters a prompt into the Crusor Desktop IDE.
2. **Path B (The Engineering Orchestrator Path):** The path implemented in `src/orchestration/orchestrator.py:run_task()`.

---

## 2. Stage-by-Stage Executable Code Verification

### Stage 1: User Submits a Task Through the Desktop UI
- **Path A (Desktop Path):**
  - **Component:** `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRenderer.ts`
  - **Action:** User enters prompt in chat box -> calls `crusorAIWorkbenchService.sendPrompt(text, mode, effort)`.
  - **Transport:** Emits JSON-RPC frame over stdin to child process: `{"type": "prompt", "text": "...", "mode": "agent"}`.
  - **Handler:** `src/bridge/__main__.py:1914` receives frame -> spawns worker thread running `_run_turn()`.
- **Path B (Orchestrator Path):**
  - **Method:** `EngineeringExecutionOrchestrator.run_task(task_prompt, task_id, explicit_constraints)`.
  - **Action:** Calls `lifecycle.begin_stage(TaskLifecycleStage.USER_REQUEST)`. Records event in `DurableOrchestrationJournal`.
- **Stage 1 Finding:** **DISCONNECT DETECTED.** Path A delegates to `chat_graph.stream_agent()` and never invokes Path B's orchestrator.

---

### Stage 2: Requirement Understanding Begins
- **Path A (Desktop Path):**
  - **Component:** `src/graphs/chat_graph.py` -> `task_manager` node.
  - **Behavior:** Reads prompt as string in `HumanMessage`. Checks if clarification tool was previously called.
  - **Limitation:** Does NOT parse functional/non-functional requirements or produce a formal specification.
- **Path B (Orchestrator Path):**
  - **Component:** `src/intelligence/requirement_integration.py:RequirementIntelligenceSystem`.
  - **Code:** `orchestrator.py:153`:
    ```python
    analysis_result = self.req_system.analyze_request(
        task_prompt=task_prompt, workspace_root=str(self.workspace_root), task_id=tid, tenant_id=self.tenant_id
    )
    ```
  - **Output:** Returns `ProjectSpecification` containing `requirements`, `scope`, `target_deliverables`.
- **Stage 2 Finding:** **PARTIALLY INTEGRATED.** Executable in Orchestrator, but absent from Desktop.

---

### Stage 3: Ambiguities Are Identified and Resolved
- **Path A (Desktop Path):**
  - **Component:** `src/tools/clarify_tool.py:clarify()` called by LLM if model decides to ask.
  - **Event:** Emits `clarify_request` frame over bridge to UI -> displays question card.
- **Path B (Orchestrator Path):**
  - **Component:** `src/intelligence/clarification.py:ClarificationEngine`.
  - **Code:** `orchestrator.py:167-177`:
    ```python
    if analysis_result.clarification_questions:
        blocking_q = [q for q in analysis_result.clarification_questions if getattr(q, "priority", "STANDARD") == "CRITICAL"]
        if blocking_q:
            state_machine.transition_to(TaskExecutionState.CLARIFICATION_REQUIRED, ...)
            for q in blocking_q:
                ans = q.recommended_option or "Standard default"
                context_mgr.record_clarification(q.question, ans)
    ```
- **Stage 3 Finding:** **PARTIALLY INTEGRATED.** Path B automatically resolves questions with recommended options for non-interactive test runs. It lacks an async IPC wait for human input when run interactively.

---

### Stage 4: Repository Intelligence Is Retrieved
- **Path A (Desktop Path):**
  - **Component:** `src/context/convention_learner.py:ConventionLearner` + `src/context/context_engine.py`.
  - **Behavior:** Scans file tree for top-level conventions (`package.json`, `requirements.txt`).
- **Path B (Orchestrator Path):**
  - **Component:** `src/intelligence/discovery.py:RepositoryDiscoveryEngine` + `PersistentProjectIntelligenceManager`.
  - **Code:** `orchestrator.py:183`:
    ```python
    knowledge = self.discovery_mgr.get_project_knowledge()
    ```
  - **Output:** Produces `ProjectKnowledge` with full AST indexing, framework identification, DB schemas, and entrypoint maps.
- **Stage 4 Finding:** **PARTIALLY INTEGRATED.** Deep AST repository intelligence is only retrieved in Path B.

---

### Stage 5: Architecture Decisions Are Generated
- **Path A (Desktop Path):**
  - **Component:** NONE. The LLM generates code directly without explicit architectural synthesis.
- **Path B (Orchestrator Path):**
  - **Component:** `src/intelligence/architecture_integration.py:ArchitectureIntelligenceSystem`.
  - **Code:** `orchestrator.py:197`:
    ```python
    arch_result = self.arch_system.synthesize_architecture(
        task_id=tid, workspace_root=str(self.workspace_root), tenant_id=self.tenant_id
    )
    ```
  - **Output:** Produces `ArchitectureBlueprint` with ADRs, technical drivers, and component relationship diagrams.
- **Stage 5 Finding:** **PARTIALLY INTEGRATED.**

---

### Stage 6: Change Impact Analysis Executes
- **Path A (Desktop Path):**
  - **Component:** NONE. The LLM calls edit tools directly without pre-computing blast radius.
- **Path B (Orchestrator Path):**
  - **Component:** `src/impact/engine.py:ChangeImpactAnalysisEngine`.
  - **Code:** `orchestrator.py:227`:
    ```python
    impact_report = self.impact_engine.analyze_proposed_changes(
        task_id=tid, proposed_change_summary=task_prompt, changed_files=all_targets,
        project_knowledge=knowledge, project_spec=analysis_result.specification,
        architecture_blueprint=arch_result.blueprint,
    )
    ```
  - **Output:** Produces `ChangeImpactReport` evaluating dependency propagation, affected tests, and risk classification.
- **Stage 6 Finding:** **PARTIALLY INTEGRATED.**

---

### Stage 7: Engineering Tasks Are Planned
- **Path A (Desktop Path):**
  - **Component:** `src/agents/planner.py` -> `src/tools/plan_tool.py:plan_update()`.
  - **Output:** Flat list of steps (`[{"title": "...", "status": "pending"}]`). Emits `plan_updated` to desktop.
- **Path B (Orchestrator Path):**
  - **Component:** `src/orchestration/planner.py:EngineeringTaskPlanner`.
  - **Code:** `orchestrator.py:212`:
    ```python
    plan_dag = self.planner.build_plan(
        task_id=tid, specification=analysis_result.specification,
        blueprint=arch_result.blueprint, knowledge=knowledge
    )
    ```
  - **Output:** Generates a structured DAG `EngineeringPlanDAG` with dependency tracking, concurrency wave ordering, and circular dependency detection.
- **Stage 7 Finding:** **DUPLICATE IMPLEMENTATION DETECTED.** Flat list planning in Path A vs. Dependency DAG planning in Path B.

---

### Stage 8: Workspace Baseline Is Captured
- **Path A (Desktop Path):**
  - **Component:** NONE. No pre-change test baseline is executed before code edits.
- **Path B (Orchestrator Path):**
  - **Component:** `src/regression/baseline.py:TestBaselineManager`.
  - **Code:** `orchestrator.py:244`:
    ```python
    baseline = self.regression_engine.baseline_mgr.capture_baseline(task_id=tid)
    ```
  - **Output:** Captures passing/failing test cases and performance metrics prior to introducing mutations.
- **Stage 8 Finding:** **PARTIALLY INTEGRATED.**

---

### Stage 9: Implementation Begins Through the Authorized Mutation Broker
- **Path A (Desktop Path):**
  - **Component:** `src/tools/file_tools.py` (`write_file`, `edit_file`).
  - **Code:**
    ```python
    safe_path = resolve_workspace_path(workspace, path)
    _atomic_write(safe_path, content)
    ```
  - **VULNERABILITY:** **Completely bypasses `WorkspaceMutationBroker`.** No authorization token required, no tenant isolation check, no before/after hash recorded in `WorkspaceChangeLedger`.
- **Path B (Orchestrator Path):**
  - **Component:** `src/orchestration/implementation_engine.py:ControlledImplementationEngine` wrapping `src/workspace/mutation_broker.py:WorkspaceMutationBroker`.
  - **Code:** `orchestrator.py:278`:
    ```python
    self.impl_engine.execute_node_mutation(task_id=tid, node=node, rel_path=target_file, content=code_content)
    ```
  - **Enforcement:** Verifies target path belongs to authorized DAG node, checks user file overwrite protection, creates ledger entry with SHA256 hashes.
- **Stage 9 Finding:** **CRITICAL SECURITY BYPASS IN DESKTOP PATH.**

---

### Stage 10: Build Verification Executes
- **Path A (Desktop Path):**
  - **Component:** `src/tools/file_tools.py:typecheck_workspace()` or LLM invokes `terminal` tool.
- **Path B (Orchestrator Path):**
  - **Component:** `orchestrator.py:302` transitions state machine to `TaskExecutionState.BUILDING`.
- **Stage 10 Finding:** **VERIFIED INTEGRATED IN BOTH PATHS.**

---

### Stage 11: Regression Prevention Executes
- **Path A (Desktop Path):**
  - **Component:** `src/graphs/gates.py:_verification_receipt_status()`.
  - **Behavior:** Simple string matching checks on terminal output (e.g. looking for `pytest` and `exit code 0`). Cannot distinguish between pre-existing test failures and newly introduced regressions.
- **Path B (Orchestrator Path):**
  - **Component:** `src/regression/engine.py:RegressionPreventionEngine`.
  - **Code:** `orchestrator.py:309`:
    ```python
    reg_report = self.regression_engine.evaluate_and_enforce_regression_gates(
        task_id=tid, workspace_id=str(self.workspace_root),
        changed_files=list(self.impl_engine.mutated_files),
        changed_symbols=[], pre_change_baseline=baseline,
        post_change_results=post_baseline.test_cases,
        change_impact_report=impact_report,
    )
    ```
  - **Output:** Categorizes each failed test into `NEW_REGRESSION`, `PRE_EXISTING_FAILURE`, or `FLAKY`.
- **Stage 11 Finding:** **PARTIALLY INTEGRATED.** True regression gate only runs in Path B.

---

### Stage 12: Failure Diagnosis and Recovery Execute When Necessary
- **Path A (Desktop Path):**
  - **Component:** `src/runtime/recovery_dispatcher.py` (ARRE runtime recovery). Intercepts failed tool calls and injects recovery advice into message state.
- **Path B (Orchestrator Path):**
  - **Component:** `orchestrator.py:322-348`:
    ```python
    if reg_report.final_status == RegressionStatus.REGRESSION_DETECTED:
        state_machine.transition_to(TaskExecutionState.FAILURE_DIAGNOSIS, ...)
        diag_str = str(reg_report.root_cause_findings[0].explanation ...)
        reasoning_loop.record_correction_attempt(diag_str)
        # Re-verify after correction
    ```
- **Stage 12 Finding:** **PARTIALLY INTEGRATED.**

---

### Stage 13: Independent Verification Evaluates the Actual Result
- **Path A (Desktop Path):**
  - **Component:** `src/graphs/gates.py:derive_4state_verification_receipt()` synthesizes a 4-state receipt (`not_applicable`, `unverified`, `failed`, `verified`).
  - **Limitation:** Tainted self-verification — the same agent and tools that wrote the code verify themselves without an independent authority.
- **Path B (Orchestrator Path):**
  - **Component:** `src/verification/engine.py:IndependentVerificationEngine`.
  - **Code:** `orchestrator.py:363`:
    ```python
    verification_report = self.verification_engine.verify_task(
        task_id=tid, original_request=task_prompt,
        mutated_files=sorted(list(self.impl_engine.mutated_files)),
        specification=analysis_result.specification,
        blueprint=arch_result.blueprint, impact_report=impact_report,
        regression_report=reg_report, test_execution_results=test_exec_map,
    )
    ```
  - **Verification Authority:** Evaluates requirement acceptance criteria, verifies test integrity (flags tautological assertions or empty tests), and checks evidence freshness.
- **Stage 13 Finding:** **PARTIALLY INTEGRATED.**

---

### Stage 14: Production Readiness Assessment Executes When Appropriate
- **Path A (Desktop Path):**
  - **Component:** NONE. Completely absent.
- **Path B (Orchestrator Path):**
  - **Component:** **ABSENT FROM `orchestrator.py:run_task()`.**
  - **Finding:** `ProductionReadinessEngine` (`src/production/engine.py`) exists and has 70 passing unit tests, but is NEVER called by `EngineeringExecutionOrchestrator`. The 15 lifecycle stages jump from Independent Verification directly to Final Delivery!
- **Stage 14 Finding:** **DISCONNECTED.** Stage 14 is missing from both paths.

---

### Stage 15: Final Delivery Is Presented to the User
- **Path A (Desktop Path):**
  - **Component:** `src/bridge/__main__.py:1215` emits terminal frame `turn_done` with `run_outcome`, `status_contract`, and `evidence`.
  - **Desktop UI:** `crusorAIRendererService.ts` displays turn finished card.
- **Path B (Orchestrator Path):**
  - **Component:** `orchestrator.py:395` instantiates `DeliveryContract` with `verdict`, `what_was_requested`, `what_was_implemented`, `files_changed`, `tests_executed`, `independently_verified`, `duration_seconds`.
  - **Limitation:** The `DeliveryContract` object is returned to the Python caller (test runner); it is not serialized or transmitted to the desktop UI.
- **Stage 15 Finding:** **DUPLICATE CONTRACTS.** `StatusContract` (Desktop) vs. `DeliveryContract` (Orchestrator).

---

## 3. Summary Comparison Table

| Stage | Expected Subsystem | Path A (Desktop) Executable Code | Path B (Orchestrator) Executable Code | Audit Verdict |
|---|---|---|---|---|
| **1. Request Submit** | Desktop UI / Stdio Bridge | `crusorAIRenderer.ts` -> `src/bridge/__main__.py:1914` | `orchestrator.py:101` | `PARTIALLY_INTEGRATED` |
| **2. Understanding** | Requirement Intelligence | `chat_graph.py:task_manager` (prose only) | `requirement_integration.py:analyze_request` | `PARTIALLY_INTEGRATED` |
| **3. Ambiguity Resolution** | Clarification Engine | `clarify_tool.py:clarify()` | `clarification.py:ClarificationEngine` | `PARTIALLY_INTEGRATED` |
| **4. Discovery** | Project Intelligence | `convention_learner.py` (shallow) | `discovery.py:RepositoryDiscoveryEngine` | `PARTIALLY_INTEGRATED` |
| **5. Architecture** | Architecture Intelligence | None | `architecture_integration.py:synthesize_architecture` | `PARTIALLY_INTEGRATED` |
| **6. Impact Analysis** | Change Impact Analysis | None | `impact/engine.py:analyze_proposed_changes` | `PARTIALLY_INTEGRATED` |
| **7. Task Planning** | DAG Planner | `agents/planner.py` (flat list) | `orchestration/planner.py:build_plan` (DAG) | `PARTIALLY_INTEGRATED` |
| **8. Baseline Capture** | Workspace / Regression | None | `regression/baseline.py:capture_baseline` | `PARTIALLY_INTEGRATED` |
| **9. Implementation** | Workspace Mutation Broker | `file_tools.py` (**BYPASSES BROKER**) | `implementation_engine.py` -> `mutation_broker.py` | `PARTIALLY_INTEGRATED` (Bypass) |
| **10. Build Verification** | Target / File Tools | `typecheck_workspace`, `terminal` | `TaskExecutionState.BUILDING` | `VERIFIED_INTEGRATED` |
| **11. Regression Check** | Regression Prevention | `gates.py:_verification_receipt_status` | `regression/engine.py:evaluate_and_enforce_regression_gates` | `PARTIALLY_INTEGRATED` |
| **12. Diagnosis/Recovery** | Recovery Dispatcher | `recovery_dispatcher.py` | `orchestrator.py:322` (bounded loop) | `PARTIALLY_INTEGRATED` |
| **13. Independent Verif** | Independent Authority | `gates.py:derive_4state_verification_receipt` | `verification/engine.py:verify_task` | `PARTIALLY_INTEGRATED` |
| **14. Production Readiness**| Production Readiness Engine | None | **None** (Omitted from `run_task`) | **`DISCONNECTED`** |
| **15. Final Delivery** | Delivery Contract | `turn_done` frame -> `StatusContract` | `DeliveryContract` | `PARTIALLY_INTEGRATED` |

