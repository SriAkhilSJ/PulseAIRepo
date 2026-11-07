# CRUSOR AI — PHASE 12 RECONCILIATION AND RELIABILITY AUDIT
**Comprehensive Technical Audit of Phase 12 Desktop Integration, Live Acceptance Claims, and Architecture Reliability**

- **Repository:** `SriAkhilSJ/PulseAIRepo`
- **Branch:** `feat/prompt-cache-stabilization`
- **Baseline Git Commit:** `7e8279919b9fde39a09f9a8b92267188f8138500`
- **Audit Date:** November 6, 2026
- **Auditor:** Antigravity (Google DeepMind Advanced Agentic Coding Team)
- **Operating Mode:** Read-Only Audit & Forensic Reconciliation (Zero paid API calls, Zero credentials exposed, Zero test weakening)

---

## 1. Executive Summary & Authoritative Reconciled Verdict

### Reconciled Verdict: **`PARTIALLY_INTEGRATED_WITH_LOCAL_PROTOTYPES`**

A rigorous, line-by-line reconciliation of the Phase 12 documentation claims against the local git working tree, the uncommitted file modifications, and the underlying Code OSS fork reveals an important divergence between **documented claims** and **production software engineering reality**:

1. **Substantial Engineering Achievements Exist:**
   - The Phase 11.0–11.8 Engineering Intelligence subsystems (Project Discovery, Requirement Engineering, Architecture Blueprints, Workspace Discipline, Regression Prevention, Independent Verification, and Production Readiness) are algorithmically sound and pass all 395 unit and integration tests.
   - The Code OSS fork (`desktop/vscode/`) strictly preserves Upstream Invariant 7 (only 5 manifest-tracked source files modified, zero tracked git drift in `desktop/`).
   - The local working tree contains real, functional implementations of the `WorkspaceMutationBroker` interception in `file_tools.py`, the `ProductionReadinessEngine` hook in `orchestrator.py`, and a new `ModelExecutionAdapter`.

2. **Critical Gaps & Contradictions Uncovered:**
   - **The Desktop Wire Protocol is Broken:** The uncommitted modifications in `src/bridge/__main__.py` attempting to wire `EngineeringExecutionOrchestrator` into desktop turns emit JSON-RPC payloads that directly violate the frontend schema in `desktop/vscode/.../common/crusorAIProtocol.ts`. Specifically, emitting `{"type": "plan_updated", "plan": [...]}` instead of `{"type": "plan_updated", "steps": [...]}` causes an unhandled `TypeError: Cannot read properties of undefined (reading 'map')` in the Electron renderer (`crusorAIRendererService.ts:2247`).
   - **The Phase 12 Live Engineering Demo Was Heavily Staged:** `FINAL_CRUSOR_DESKTOP_ENGINEERING_DEMO.md` claimed an end-to-end autonomous creation of `apps/personal_finance` driven by Electron CDP and the live Velona provider. Forensic audit of `scripts/demonstrate_ui_to_ai.py` and the git log confirms:
     - CDP submission was simulated entirely with console `print()` statements; no Chrome DevTools Protocol session interacted with the Electron input textarea.
     - The target application `apps/personal_finance` was **pre-authored and already committed** in git commit `cd800b5f`; it was not created by the model during the run.
     - The live Velona provider was invoked for a single high-level architectural text prompt (125 input tokens), not for code generation.
     - The orchestrator run in `demonstrate_ui_to_ai.py` executed against deterministic test stubs generating template classes (`class {class_name}Service:`), while the 7 passing tests were run against pre-existing test files.
   - **FinOps Accounting Is Hardcoded to Zero in Model Execution:** `ModelExecutionAdapter` hardcodes `cost_inr=0.0` and `estimated_cost_inr=0.0` on every execution, rendering monetary budget ceilings in the orchestrator path completely inoperative.
   - **Three Disconnected Architecture Islands:** The legacy LangGraph pipeline (`src/graphs/chat_graph.py`), the autonomous orchestrator (`src/orchestration/orchestrator.py`), and the desktop contribution (`desktop/vscode/`) operate with three separate cost systems, two different shell execution pathways, and incompatible progress event streams.

---

## 2. Current Architecture Overview

```
                                  +------------------------------------+
                                  |   Crusor AI Electron Desktop IDE   |
                                  |      (desktop/vscode - Code OSS)    |
                                  +-----------------+------------------+
                                                    |
                                    Stdio JSON-RPC (Versioned Wire)
                                                    |
                                                    v
                                  +-----------------+------------------+
                                  |       Python Headless Bridge       |
                                  |       (src/bridge/__main__.py)     |
                                  +--------+------------------+--------+
                                           |                  |
                   Uncommitted Router Fork |                  | Legacy Route
           (mode in ['agent', 'plan']      |                  | (mode in ['debug', 'ask']
            CRUSORAI_ORCHESTRATOR_ENGINE   |                  |  or engine='legacy')
            != 'legacy')                   |                  |
                                           v                  v
    +----------------------------------------------+   +------------------------------------+
    |      Autonomous Engineering Orchestrator     |   |         Legacy Chat Graph          |
    |      (src/orchestration/orchestrator.py)     |   |      (src/graphs/chat_graph.py)    |
    |  - 15 Lifecycle Stages                       |   |  - 8,280 lines LangGraph           |
    |  - TaskStateMachine & Planner DAG            |   |  - ProgressGuard & Gates           |
    |  - Stage 14.5: Production Readiness          |   |  - ContextEngine (32 layers)       |
    |  - Stage 14: Independent Verification        |   |  - CostRouter (keyword-based)      |
    +----------------------+-----------------------+   +-----------------+------------------+
                           |                                             |
                           v                                             v
    +----------------------------------------------+   +------------------------------------+
    |           ModelExecutionAdapter              |   |           RetryLLMProxy            |
    |     (src/orchestration/model_adapter.py)     |   |       (src/llm/factory.py)         |
    |  - Generates stubs if mock/test mode         |   |  - 5 retries on same provider      |
    |  - Invokes get_llm() if API key present      |   |  - Fails closed on HTTP 402        |
    |  - HARDCODED: cost_inr = 0.0                 |   |  - No cross-provider failover      |
    +----------------------+-----------------------+   +-----------------+------------------+
                           |                                             |
                           +-----------------------+---------------------+
                                                   |
                                                   v
                                  +----------------+-------------------+
                                  |      Workspace Mutation Broker     |
                                  |    (src/workspace/mutation_broker) |
                                  |  - Path safety & Confinement       |
                                  |  - SHA-256 Mutation Ledger         |
                                  |  - User file overwrite prevention  |
                                  +----------------+-------------------+
                                                   |
                                                   v
                                  +----------------+-------------------+
                                  |      Target Workspace File Tree    |
                                  +------------------------------------+
```

### Core Architecture Components:
1. **Desktop Shell (`desktop/vscode/`):** Pinned fork of Code OSS. Houses `crusorAIWorkerProcessService.ts` (utility-process spawner), `crusorAIEngineService.ts` (IPC broker), and `crusorAIRendererService.ts` (native UI projection).
2. **Bridge Subsystem (`src/bridge/`):** Manages session lifecycle, stdin/stdout buffering, event forwarding, watchdog liveness, and turn execution dispatch.
3. **Autonomous Engineering Stack (`src/orchestration/`):** 15-stage state machine driving `ProjectDiscovery` -> `RequirementIntegration` -> `ArchitectureIntegration` -> `TaskPlanner` -> `DependencyScheduler` -> `ModelExecutionAdapter` -> `RegressionPreventionEngine` -> `IndependentVerificationEngine` -> `ProductionReadinessEngine`.
4. **Legacy LangGraph Subsystem (`src/graphs/chat_graph.py`):** Monolithic 8,280-line state graph controlling interactive chat, tool execution loops, context pruning, and manual gates.

---

## 3. Actual Desktop Active Execution Path

A forensic trace of a user prompt submitted from the desktop UI establishes the actual active execution path:

```
[1. User Action]
     User types prompt in textarea.crusorai-composer-input and clicks Send (or Ctrl+Enter).
     │
     ▼
[2. Desktop Contribution]
     desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRendererService.ts
     Calls this._engineService.prompt(sessionId, promptText, mode, reasoningEffort)
     │
     ▼
[3. Worker Process IPC]
     desktop/vscode/src/vs/workbench/contrib/crusorai/node/crusorAIWorkerProcessService.ts
     Emits JSON-lines frame to child process stdin:
     {"type": "prompt", "session_id": "...", "text": "...", "mode": "agent", "reasoning_effort": "medium"}
     │
     ▼
[4. Python Bridge Ingress]
     src/bridge/__main__.py (BridgeServer._handle_line -> _run_turn)
     Validates workspace contract (rejects empty or unbound workspaces).
     Spawns background event forwarding thread.
     │
     ▼
[5. Execution Routing Decision (Line 1166)]
     use_orchestrator = (
         mode in ("agent", "plan")
         and os.environ.get("CRUSORAI_ORCHESTRATOR_ENGINE", "orchestrator").lower() != "legacy"
     )
     ├───────────────────────────────────────────────┬───────────────────────────────────────────────┐
     │ IF TRUE (Uncommitted Working Tree Branch)    │ IF FALSE (Committed feat/prompt-cache-stab)   │
     ▼                                               ▼                                               ▼
[6A. Orchestrator Path]                         [6B. Legacy LangGraph Path]
     EngineeringExecutionOrchestrator                stream_agent(text, thread_id=sid, ...)
     (src/orchestration/orchestrator.py)             (src/graphs/chat_graph.py)
     │                                               │
     ├─ Stage 1-9: Discovery, Specs, Blueprints      ├─ ContextEngine: 32-layer context assembly
     ├─ Stage 10: ModelExecutionAdapter              ├─ CostRouter: classify(task) -> cheap/standard
     │   Calls get_llm() or generates stubs          ├─ ai_node: RetryLLMProxy -> HTTP Provider
     ├─ Stage 11-13: Regression Baseline & Check     ├─ tools_node: terminal, file_tools, etc.
     ├─ Stage 14: Independent Verification          ├─ progress_guard & safety_gates
     ├─ Stage 14.5: Production Readiness             └─ Emits tokens, tool_calls, turn_done
     └─ Stage 15: DeliveryContract created
     │
     ▼
[7. Progress Event Serialization (FATAL PROTOCOL DEFECT)]
     Bridge emits progress events via on_orch_progress callback:
     - Emits: {"type": "plan_updated", "plan": [{"id": ..., "status": ...}]}
       DESKTOP ERROR: crusorAIRendererService.ts:2247 executes:
       `this.plan = frame.steps.map(planStepView);`
       Because frame.steps is undefined, Electron throws:
       TypeError: Cannot read properties of undefined (reading 'map')
     - Emits: {"type": "verification_updated", "verified": true, "verdict": "COMPLETED"}
       DESKTOP ERROR: crusorAIRendererService.ts:2459 executes:
       `this.verification = frame.status;`
       frame.status is undefined, so the desktop status badge remains blank.
     │
     ▼
[8. File Mutation Chokepoint]
     ControlledImplementationEngine -> WorkspaceMutationBroker
     Validates path containment, checks user ownership, logs SHA-256 before/after hashes.
     │
     ▼
[9. Terminal Execution]
     src/tools/terminal_tools.py:
     - If CRUSOR_SANDBOX_TERMINAL=1: ExecutionBroker -> Windows AppContainer (cmd.exe /c).
     - Default: Raw host subprocess.Popen via select_shell() (git-bash or cmd.exe).
```

### Critical Findings on Execution Path Reachability:
- **Is `EngineeringExecutionOrchestrator` invoked by the production desktop path?**  
  **CONDITIONALLY YES, BUT ONLY IN THE UNCOMMITTED LOCAL WORKING TREE.**  
  In the committed git branch (`7e827991`), `src/bridge/__main__.py` has zero references to `EngineeringExecutionOrchestrator` and calls `stream_agent` exclusively. In the modified local working tree, it is invoked when `mode in ("agent", "plan")`, but immediately triggers runtime JavaScript exceptions in Electron due to frame payload schema mismatches.
- **Does `ModelExecutionAdapter` exist and is it reachable?**  
  **YES, IT EXISTS AS AN UNTRACKED FILE (`src/orchestration/model_adapter.py`) AND IS CALLED BY `orchestrator.py:300`.**  
  However, it is completely disconnected from `chat_graph.py` and hardcodes `cost_inr=0.0`.

---

## 4. Phase 12 Claim-by-Claim Reconciliation

| Report / Artifact | Documented Claim | Verified Source State | Reconciliation Category | Forensic Evidence & Details |
| :--- | :--- | :--- | :---: | :--- |
| **Phase 12.0.1 Final Verdict** | Orchestrator completely disconnected from Bridge. | Bridge in `7e827991` called only `stream_agent`. | **SUPPORTED BY COMMITTED CODE** | Accurately reported the baseline gap before local edits were applied. |
| **Phase 12.0.1 Final Verdict** | File tools bypass `WorkspaceMutationBroker`. | `file_tools.py` in `7e827991` used raw `safe_path.write_text()`. | **SUPPORTED BY COMMITTED CODE** | Verified bypass in baseline commit. |
| **Phase 12.0.1 Final Verdict** | Synthetic stubs in production orchestrator code. | `orchestrator.py:274` wrote `def {node_id}_handler(): return 'OK'`. | **SUPPORTED BY COMMITTED CODE** | The synthetic 4-line handler was physically present in the repository. |
| **Phase 12.1 Final Verdict** | Bridge routes `agent` & `plan` tasks to Orchestrator. | `src/bridge/__main__.py:1166-1243` modified locally (uncommitted). | **SUPPORTED ONLY BY LOCAL UNCOMMITTED CODE** | Code exists in working tree, but wire protocol mismatch breaks Electron UI rendering. |
| **Phase 12.1 Final Verdict** | All file tools route through `WorkspaceMutationBroker`. | `file_tools.py` modified locally to call `broker.create_file`, `modify_file`. | **SUPPORTED ONLY BY LOCAL UNCOMMITTED CODE** | Uncommitted changes correctly wrap mutations in broker calls. |
| **Phase 12.1 Final Verdict** | `ModelExecutionAdapter` replaces synthetic stubs with real LLM. | `model_adapter.py` exists; still has `_generate_deterministic_implementation`. | **CONTRADICTED BY CURRENT SOURCE** | Offline/test mode still generates static template classes (`Class...Service`); real calls record ₹0.0 cost. |
| **Phase 12.1 Final Verdict** | ProductionReadinessEngine integrated into Stage 14.5. | `orchestrator.py:436` calls `evaluate_readiness()`. | **SUPPORTED ONLY BY LOCAL UNCOMMITTED CODE** | Code is present in working tree; reports findings attached to `DeliveryContract`. |
| **Phase 12.1.1 Qualification** | 7/7 workspace mutation attacks blocked fail-closed. | `test_phase_12_1_1_security_qualification.py` passes 7/7. | **SUPPORTED BY EXECUTION EVIDENCE** | Path traversal, user file protection, symlinks, and tokens verified. |
| **Phase 12.1.1 Qualification** | 12-point Expense Tracker autonomously built & delivered. | `test_phase_12_1_1_expense_tracker_task.py` passes. | **CONTRADICTED BY CURRENT SOURCE** | Test executed with `mock_mode=True`. Created dummy template stubs in temp folder; no real app was built. |
| **Phase 12.1.2 Qualification** | AppContainer terminal isolation qualified on `terminal_tools.py`. | AppContainer code added behind `CRUSOR_SANDBOX_TERMINAL=1`. | **SUPPORTED BY LOCAL EXECUTION EVIDENCE** | Integration passes tests, but is disabled by default in production (`CRUSOR_SANDBOX_TERMINAL="0"`). |
| **Phase 12.1.2 Qualification** | 10/10 failure modes recovered. | `test_phase_12_1_2_failure_recovery.py` passes 10/10. | **SUPPORTED BY EXECUTION EVIDENCE** | Timeouts, budget halts, DACL rejections, and cancellations pass. |
| **Phase 12.1.3 Qualification** | Reproducible Electron fix without Invariant 7 drift. | `scripts/reproduce_desktop_build.mjs` transpiles cleanly. | **SUPPORTED BY CURRENT CODE** | Invariant 7 strictly maintained (0 tracked changes in `desktop/`). |
| **Phase 12.1.3 Qualification** | Model execution certified as `DETERMINISTIC_PROVIDER_ONLY`. | Transparently noted commercial endpoints were not invoked. | **SUPPORTED BY CURRENT CODE** | Truthfully reported deterministic offline qualification. |
| **Live Acceptance Final** | Authenticated commercial Velona model generated 12,531 bytes of valid code. | `PHASE_LIVE_VELONA_PROVIDER_EVIDENCE.md` documents `expense_validator.py`. | **SUPPORTED ONLY BY LOCAL EXECUTION EVIDENCE** | Isolated offline script execution; not integrated into end-to-end desktop run. |
| **Final Desktop Demo** | "Full desktop UI-to-AI engineering demo verified". | `scripts/demonstrate_ui_to_ai.py` inspected. | **CONTRADICTED BY CURRENT SOURCE** | CDP was simulated via `print()`; `apps/personal_finance` was pre-committed; model called once for text assessment. |

---

## 5. Subsystem Integration Matrix: Implemented vs. Disconnected

| Subsystem | Underlying Implementation | Integration Status in Desktop Path | Connection Point | Architectural Deficiencies & Breakages |
| :--- | :--- | :---: | :--- | :--- |
| **WorkspaceMutationBroker** | `src/workspace/mutation_broker.py` | **CONNECTED (UNCOMMITTED)** | `src/tools/file_tools.py` | Fully functional in working tree; uncommitted. Bypassed if changes restored. |
| **EngineeringExecutionOrchestrator** | `src/orchestration/orchestrator.py` | **BLOCKED BY PROTOCOL BUG** | `src/bridge/__main__.py:1171` | Emits `plan` instead of `steps`, crashing Electron renderer `frame.steps.map`. |
| **ModelExecutionAdapter** | `src/orchestration/model_adapter.py` | **CONNECTED (UNTRACKED)** | `src/orchestration/orchestrator.py:300` | Hardcodes `cost_inr=0.0`. Generates template classes in test/mock mode. Disconnected from `chat_graph`. |
| **ProductionReadinessEngine** | `src/production/engine.py` | **CONNECTED (UNCOMMITTED)** | `src/orchestration/orchestrator.py:436` | Fully operational in working tree. Evaluates 10 vulnerability & posture checks. |
| **Identity & Tool RBAC** | `src/identity/tool_authorizer.py` | **PARTIALLY CONNECTED** | `model_adapter.py:94` | Enforced in `model_adapter.py`. DISCONNECTED in `file_tools.py` and `chat_graph.py`. |
| **FinOps Cost Governor** | `src/finops/`, `src/agents/cost_governance.py` | **DISCONNECTED / FRAGMENTED** | Three separate files | Three conflicting governors. Orchestrator governor bypassed by `cost_inr=0.0`. |
| **Cost-Aware Model Router** | `src/agents/cost_router.py` | **DISCONNECTED FROM ORCHESTRATOR** | `src/graphs/chat_graph.py` | Only invoked by legacy LangGraph. Uses naive keyword matching; zero plan awareness. |
| **Terminal Safety Broker** | `src/workspace/terminal_discipline.py` | **CONNECTED (UNCOMMITTED)** | `src/tools/terminal_tools.py:984` | Pre-screens dangerous commands (`rm -rf`, `format`, pipe masking). Operational. |
| **Windows AppContainer Sandbox** | `src/security/execution_broker.py` | **DISABLED BY DEFAULT** | `src/tools/terminal_tools.py:1094` | Requires `CRUSOR_SANDBOX_TERMINAL=1`. Default runs raw host `subprocess.Popen`. |
| **Multilingual Intelligence** | `src/intelligence/discovery.py` | **DISCONNECTED / MISSING** | None | Only parses Python AST. TS/JS/TSX/JSX files get no AST or symbol extraction. |
| **Milestone Governor** | Non-existent | **MISSING** | None | No sequencing of Backend -> Frontend -> Integration -> Verification. |

---

## 6. Audit of the Six Reliability Weaknesses

### 1. Multilingual Repository Intelligence (JS, TS, TSX, JSX)
- **Implementation Status:** **CRITICALLY DEFICIENT / PRIMITIVE**.
- **Source Inspection:** `src/intelligence/discovery.py` lines 52–56 maps file extensions (`.ts`, `.tsx`, `.js`, `.jsx`), and lines 451–459 performs simple regex scanning for `process.env.[A-Z0-9_]+`.
- **Finding:** There is **zero AST parsing, zero symbol table extraction, zero call-graph construction, and zero type resolution** for JavaScript, TypeScript, TSX, or JSX. In `src/orchestration/orchestrator.py:364` and `:393`, `changed_symbols=[]` is literally hardcoded as an empty list. In `model_adapter.py:151`, AST parsing is explicitly restricted to `if target_file.endswith(".py"): ast.parse(...)`.
- **Consequence:** The orchestrator is blind to TypeScript/React architectures, cannot detect broken exports/imports across TSX components, and cannot calculate impact blast radius for web applications.

### 2. Milestone Governor (Backend → Frontend → Integration → Verification)
- **Implementation Status:** **NOT IMPLEMENTED**.
- **Source Inspection:** `src/orchestration/planner.py` lines 74–105 loops over extracted requirements (`REQ-001`, `REQ-002`) and creates independent task nodes with `dependencies=[]`.
- **Finding:** All task nodes are dumped into the DAG with empty dependency lists. `src/orchestration/scheduler.py` schedules them into a single parallel Wave 1. There is no architectural concept of a Backend milestone preceding a Frontend milestone, no gating requiring backend API health checks before frontend UI generation, and no integration verification gate before final delivery.
- **Consequence:** During autonomous runs on full-stack prompts, the agent attempts to write frontend components against non-existent backend APIs, resulting in the high failure rates observed in the e-commerce benchmarks.

### 3. USD-Denominated Hard Cost Ceiling
- **Implementation Status:** **FRAGMENTED & UNENFORCEABLE IN ACTIVE ORCHESTRATOR**.
- **Source Inspection:**
  - `src/agents/cost_governance.py`: Implements `CostGovernanceConfig` with `target_simple_task_cost_inr = Decimal("5.00")` and `per_session_cost_budget_inr = Decimal("86.00")` (~$1.00 USD).
  - `src/finops/budget_governor.py`: Enterprise budget governor tracking USD and INR.
  - `src/orchestration/finops_governor.py`: Local `OrchestrationFinOpsGovernor` tracking `budget_inr`.
  - `src/orchestration/model_adapter.py:284`: Calls `finops.record_usage(input_tokens=in_tok, output_tokens=out_tok, cost_inr=0.0)`.
- **Finding:** Because `ModelExecutionAdapter` records `cost_inr=0.0`, `self.accounting.spent_inr` remains `0.00` regardless of how many tokens are consumed. A hard USD or INR budget ceiling **cannot be enforced** in the orchestrator pipeline.

### 4. Plan/Toolset-Based Model Routing
- **Implementation Status:** **NAIVE & DISCONNECTED FROM ORCHESTRATOR**.
- **Source Inspection:** `src/agents/cost_router.py:101-155`:
  ```python
  if any(s in task_lower for s in premium_signals): return "premium"
  if any(s in task_lower for s in cheap_signals) and len(task) < 120: return "cheap"
  if len(task) < 35: return "cheap"
  if current_plan and len(current_plan) > 5: return "premium"
  return "standard"
  ```
- **Finding:** Classification relies entirely on crude substring matching (`"what is"`, `"architecture"`, `"how do i"`). It does not analyze the required toolset (e.g. bash execution vs read-only vs file editing) or inspect task node complexity. Crucially, **`CostRouter` is never called by `EngineeringExecutionOrchestrator`**; the orchestrator reads static `LLM_PROVIDER` and `LLM_MODEL` from `settings.py`.

### 5. Evidence-Driven Model Escalation After Repeated Failures
- **Implementation Status:** **NOT IMPLEMENTED IN ORCHESTRATOR / LIMITED IN CHAT GRAPH**.
- **Source Inspection:**
  - In `src/orchestration/scheduler.py:123-125`:
    ```python
    if failed_nodes:
        log.warning(f"Wave {wave_idx + 1} experienced failures: {failed_nodes}. Halting pipeline.")
        break
    ```
    When a task node fails, the scheduler immediately aborts the entire pipeline. There is no retry with an escalated model.
  - In `src/context/complexity.py:182`, `escalate_complexity()` dynamically escalates the *context window tier* (Tier 1 -> Tier 4) for prompt packing, but does **not** escalate the underlying model from cheap to frontier.
- **Finding:** Neither pipeline possesses an evidence-driven model escalation governor that automatically upgrades a failing task from a fast/cheap model (e.g. GLM-flash) to a high-reasoning frontier model (e.g. Claude 3.5 Sonnet or GPT-4o) upon repeated test or verification failures.

### 6. Provider Fallback for HTTP 402, 429, and 5xx
- **Implementation Status:** **PARTIAL RETRY, ZERO PROVIDER FAILOVER ON 402/AUTH**.
- **Source Inspection:** `src/llm/factory.py:972-978` (`RetryLLMProxy._is_retryable`):
  ```python
  c = classify_api_error(error)
  if c.reason in (FailoverReason.auth, FailoverReason.auth_permanent, FailoverReason.billing):
      return False
  return c.retryable
  ```
- **Finding:**
  - For HTTP 402 (billing/wallet exhaustion) and HTTP 401 (auth failure), the error is marked `retryable=False`. `RetryLLMProxy:828` immediately re-raises the exception and crashes the turn. **There is zero failover to an alternative provider.**
  - For HTTP 429 (rate limit) and HTTP 5xx (server error), the proxy retries up to 5 times with exponential backoff on the **same failing provider**. It does not switch to a healthy backup gateway.

### 7. Windows Shell Command Handling & Terminal Wiring
- **Implementation Status:** **BRITTLE COMMAND PARSING & MISCONFIGURED APPCONTAINER ARGUMENTS**.
- **Source Inspection:** `src/tools/terminal_tools.py:1113-1121`:
  ```python
  if command.startswith('"') and "python" in command.lower():
      ac_argv = shlex.split(command, posix=True)
  else:
      ac_argv = ["cmd.exe", "/c", command]
  ```
- **Finding:**
  - In AppContainer mode, commands are wrapped in `["cmd.exe", "/c", command]`. If the command contains PowerShell cmdlets, Unix-style subshells, or pipes, `cmd.exe` fails with syntax errors.
  - In raw host mode, `src/runtime/windows_shell.py:select_shell()` probes for `git-bash`. If `git-bash` is missing, it falls back to `cmd.exe`. However, models frequently emit PowerShell commands (e.g. `Get-ChildItem`), which fail on `cmd.exe` with exit code 255.

---

## 7. Reconciled Benchmark Evidence Audit

To eliminate historical distortions where disparate test types were aggregated into misleading success percentages, benchmark results are strictly segregated by test category:

```
====================================================================================================
                                 BENCHMARK RECONCILIATION MATRIX
====================================================================================================
```

### A. GatePulse Three-Model Benchmark (Standardized Fixed Gateway Specification)
*Evaluation of `z-ai/glm-5.3-flash`, `deepseek/deepseek-v4.1-flash`, and `openai/gpt-4o-mini` against 16 backend checks and 9 Playwright browser checks:*

| Model & Run | Backend Unit Tests (Deterministic) | Playwright Browser E2E Tests | Total Calls | Total Tokens | Cost (USD) | Wall Clock Time | Outcome & Forensic Audit |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **GLM-5.3-Flash (Run 1)** | 16 / 16 (100%) | 9 / 9 (100%) | 22 calls | 400,849 | $0.0472 | 928.91s | **PASSED**. High latency due to 11,504 reasoning tokens. |
| **DeepSeek-V4.1-Flash (Run 1)** | 16 / 16 (100%) | 9 / 9 (100%) | 39 calls | 787,121 | $0.2669 | 478.54s | **PASSED**. Lean reasoning, fast execution (2x faster than GLM). |
| **GPT-4o-mini (Run 1)** | 0 / 16 (0%) | 2 / 9 (22%)* | 16 calls | 143,856 | $0.0215 | 171.25s | **FAILED**. Budget clamped at 121k tokens; syntax crash in server. |
| **GPT-4o-mini (Run 2)** | 0 / 16 (0%) | 2 / 9 (22%)* | 11 calls | ~95,000 | $0.0145 | 158.87s | **FAILED**. Hallucinated tool args (`old_text=`); SQL syntax error. |
| **GPT-4o-mini (Run 3)** | 6 / 16 (38%) | 7 / 9 (78%) | 13 calls | ~105,000 | $0.0160 | 163.50s | **FAILED**. Pre-flight AST gate fixed syntax; died on SQLite thread lock. |
| **GPT-4o-mini (Run 4)** | 16 / 16 (100%) | 9 / 9 (100%) | 13 calls | ~112,000 | $0.0170 | 163.05s | **PASSED**. Guidance on SQLite WAL mode enabled 100% pass rate. |

*\*Note: Runs 1 & 2 trivially passed browser checks 8 & 9 because the server never booted.*

### B. E-Commerce Open-Ended Amazon Clone Benchmark
*Evaluation of autonomous full-stack generation from scratch without templates:*

| Run Identifier | Model | Tool Calls Succeeded / Total | Total Tokens | Wall Clock Time | Run Outcome | Verification Status | Forensic Root Cause |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Unlimited Headless** | `deepseek/deepseek-v4.1-flash` | 46 / 51 (90.2%) | 2,026,180 | 251.53s | `completed` | `VERIFIED (web)` | **PASSED**. Clean modular architecture (`db.py`, `server.py`, `app.js`). |
| **Live Test Run 4 (v4)** | `z-ai/glm-5.3-flash` | 29 / 58 (50.0%) | 987,476 | 299.07s | `budget_exhausted` | `failed` | **FAILED**. 29 tool failures from exact string mismatch in `edit_file`. |
| **Hardened Run 7** | `z-ai/glm-5.3-flash` | 18 / 36 (50.0%) | ~650,000 | 341.16s | `failed` | `failed` | **FAILED**. Assertion error in `verify_api.py`: `assert any("b" in p["title"])`. |
| **Hardened Run 8 (Showcase)** | `z-ai/glm-5.3-flash` | Monolithic file write | ~750,000 | ~420.00s | `completed` | `VERIFIED` | **PASSED SHOWCASE**. 36.3 KB monolithic `server.py` and 15.7 KB `index.html`. |

### C. SprintBoard Full-Stack Live Benchmark
*Automated verification against `.acceptance/test_sprintboard.py`:*
- **Run ID:** `40576857348`
- **Unit & File Completeness:** 4 / 5 tests passed (Files: `server.py`, `index.html`, `styles.css`, `app.js`, `README.md` created).
- **Failure Mode:** Test 5 failed with `sqlite3.OperationalError: no such table: tasks`.
- **Authoritative Status:** **FAIL / REJECTED** (Documented in `README.md:89` as immutable failed run).

### D. Phase 12 Personal Finance & Expense Tracker Demonstration
*Segregation of Mock, Unit, Provider, and UI claims:*

| Evaluation Layer | Claimed Status | Verified Test Type | Pass / Fail Count | Forensic Finding |
| :--- | :--- | :--- | :---: | :--- |
| **Backend Service Unit Tests** | 100% Passed | Deterministic Unit Tests | 7 / 7 Passed (0.51s) | Tests pass against pre-existing code in `apps/personal_finance/backend`. |
| **Orchestrator Pipeline Lifecycle** | 100% Passed | Provider-Free Integration Test | 1 / 1 Passed (4.41s) | Ran in mock mode (`ModelExecutionAdapter(mock_mode=True)`). Created dummy stubs. |
| **Live Model Code Authoring** | Fully Authored by AI | Live Provider-Backed Test | 0 Files Generated | Velona called once for architectural text assessment; no code files generated. |
| **Electron UI Desktop Automation** | CDP Verified on UI Target | Desktop UI Interaction Test | 0 Real CDP Actions | Simulated with console `print()`; no automated CDP actions against `textarea`. |

---

## 8. Financial and FinOps Audit

### 1. Model Cost & Token Accounting Analysis
- **Fixed Context Overhead per Cycle:**
  - Standard CrusorAI Prompt Overhead: **13,660 tokens per cycle**.
  - Tool Schemas Alone: **7,509 tokens** across 36 tools.
  - Comparison: Aider fixed cost is 2,289 tokens; OpenCode is 2,816 tokens; Void is 1,897 tokens.
  - CrusorAI pays **4.8x–7.2x higher fixed token overhead** on every single LLM call before user context is considered.
- **Input/Output Consumption on Benchmark Deliverables:**
  - GatePulse GPT-4o-mini Run 4: 112,000 total tokens ($0.0170 / ~₹1.46).
  - GatePulse DeepSeek V4.1: 787,121 total tokens ($0.2669 / ~₹22.95).
  - E-Commerce DeepSeek Run: 2,026,180 total tokens ($0.6868 / ~₹59.06).
  - E-Commerce GLM Run 4: 987,476 total tokens (~₹29.62) — **Died with zero deliverable**.

### 2. Retry Expenditure & Waste
- On GLM Run 4, 29 failed `edit_file` tool operations burned **~450,000 tokens** (approx ₹13.50) purely retrying failed string replacements.
- In `RetryLLMProxy`, 5 retries on failing endpoints (HTTP 429/5xx) multiply token transmission with zero outcome.

### 3. Can a Hard ₹5 Budget Be Enforced?
- **Finding:** **NO, NOT UNDER THE CURRENT ARCHITECTURE.**
  - At 13,660 tokens of fixed prompt/tool overhead per call:
    - On a model priced at ₹0.05 per 1,000 tokens (e.g. standard frontier), 1 call costs ₹0.68. A 10-turn task costs ₹6.80 in fixed overhead alone.
    - If `ModelExecutionAdapter` is active, it reports `cost_inr=0.0`, so the budget governor never trips.
    - If real pricing is enabled, any non-trivial multi-turn coding task (> 5 turns) immediately blows past ₹5.00.
  - To enforce a hard ₹5.00 ceiling, the engine must:
    1. Prune the tool schema catalog from 36 tools (7,509 tokens) down to the 5 tools needed for the task (< 1,000 tokens).
    2. Route exclusively to micro-cost models (e.g. DeepSeek-flash at ₹0.01/1k tokens).
    3. Cap execution turns strictly at ≤ 8 iterations.

---

## 9. Missing Implementation & Root Deficiencies

1. **Desktop Wire Protocol Conformance:**  
   `src/bridge/__main__.py` must serialize progress events matching `CrusorAIProtocol.ts`:
   - `plan_updated` must emit `"steps": [...]`, not `"plan": [...]`.
   - `turn_lifecycle` must emit `"lifecycle_status": "started" | "completed" | "failed"`.
   - `verification_updated` must emit `"status": string`.
2. **Multilingual AST & Symbol Extraction:**  
   `src/intelligence/discovery.py` lacks a parser for JavaScript/TypeScript. Need tree-sitter or regex-based symbol and import extraction for `.js`, `.ts`, `.tsx`, `.jsx`.
3. **Milestone Governor in Orchestrator:**  
   `src/orchestration/planner.py` lacks stage grouping. Must implement an explicit milestone sequencer: `Backend (APIs & DB)` -> `Frontend (UI & State)` -> `Integration (E2E & CORS)` -> `Verification`.
4. **Active Path Token & Cost Metering:**  
   `src/orchestration/model_adapter.py` must calculate actual token usage from response receipts and lookup rates in `src/finops/pricing_registry.py` instead of hardcoding `0.0`.
5. **Cross-Provider Failover:**  
   `src/llm/factory.py` (`RetryLLMProxy`) must maintain a secondary provider fallback pool for HTTP 402, 401, and exhausted retries.
6. **Windows Terminal Subprocess Isolation:**  
   `src/tools/terminal_tools.py` must construct valid execution vectors for PowerShell commands inside Windows AppContainers rather than wrapping everything in `cmd.exe /c`.

---

## 10. Prioritized Engineering Action Plan (P0 / P1 / P2)

### Priority P0: Critical Path & Protocol Integrity (Immediate)
1. **P0.1: Repair Bridge JSON-RPC Frame Schemas (`src/bridge/__main__.py`):**
   - Align `plan_updated`, `turn_lifecycle`, and `verification_updated` frames with `desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAIProtocol.ts`.
   - Prevent Electron unhandled exceptions during agent turns.
2. **P0.2: Fix FinOps Cost Accounting in `ModelExecutionAdapter` (`src/orchestration/model_adapter.py`):**
   - Connect `model_adapter.py` to `PricingRegistry` and `OrchestrationFinOpsGovernor`.
   - Replace hardcoded `cost_inr=0.0` with real token-based cost calculations.
3. **P0.3: Formalize Working Tree Modifications into Tested Commits:**
   - Commit the verified `file_tools.py` broker wrapping, `orchestrator.py` stage 14.5 hook, and `model_adapter.py` adapter.

### Priority P1: Reliability & Execution Weaknesses
1. **P1.1: Implement Milestone Governor (`src/orchestration/milestone_governor.py`):**
   - Enforce sequential wave dependencies: Database/Backend -> Frontend -> Integration -> Verification.
   - Prevent frontend generation before backend API endpoints pass health checks.
2. **P1.2: Implement Multilingual AST & Symbol Extractor (`src/intelligence/multilingual_parser.py`):**
   - Add TypeScript/JavaScript symbol resolution, import/export graph mapping, and JSX component dependency analysis.
3. **P1.3: Add Multi-Provider Failover to `RetryLLMProxy` (`src/llm/factory.py`):**
   - On HTTP 402 (quota exhausted) or HTTP 429 (rate limited), fail over to configured secondary provider.
4. **P1.4: Refactor Windows Terminal Shell Selection (`src/tools/terminal_tools.py`):**
   - Correctly detect and route PowerShell cmdlets vs bash vs cmd.exe commands in both AppContainer and host execution.

### Priority P2: Intelligence & Optimization
1. **P2.1: Plan-Based Routing in `CostRouter` (`src/agents/cost_router.py`):**
   - Connect router to the Orchestrator DAG to dynamically route high-complexity nodes to reasoning models and simple nodes to cheap models.
2. **P2.2: Tool Catalog Dynamic Pruning:**
   - Reduce the 7,509-token fixed schema payload by dynamically binding only the tools required for the active milestone.
3. **P2.3: Evidence-Driven Model Escalation:**
   - Automatically escalate model tier after 2 consecutive test verification failures on the same task node.

---

## 11. Exact Files Requiring Changes

| File Path | Lines | Nature of Required Changes |
| :--- | :--- | :--- |
| `src/bridge/__main__.py` | 1182–1206, 1234–1241 | Change `"plan"` to `"steps"`, map `"stage"`/`"state"` to valid `lifecycle_status`, emit `"status"` in `verification_updated`. |
| `src/orchestration/model_adapter.py` | 84–86, 120–140, 281–285 | Replace `cost_inr=0.0` with pricing lookup from `PricingRegistry`. Connect real token counts. |
| `src/orchestration/planner.py` | 74–105 | Implement milestone grouping (Backend, Frontend, Integration) with explicit inter-node dependencies. |
| `src/orchestration/scheduler.py` | 113–126 | Add retry and model escalation logic instead of immediately halting on node failure. |
| `src/intelligence/discovery.py` | 451–461 | Integrate multilingual symbol parsing for `.ts`, `.tsx`, `.js`, `.jsx`. Populate `changed_symbols`. |
| `src/llm/factory.py` | 820–830, 972–980 | Add provider failover pool on HTTP 402/429 instead of immediate `raise`. |
| `src/tools/terminal_tools.py` | 1113–1122 | Fix AppContainer argument formatting to support PowerShell commands without cmd.exe syntax errors. |
| `src/agents/cost_router.py` | 101–155 | Expose routing API for DAG task nodes; replace keyword matching with task node metadata classification. |

---

## 12. Required Regression Test Battery

Before any further phase sign-off, the following test battery must be executed cleanly:

```bash
# 1. Phase 12.1.1 & 12.1.2 Integration & Security Qualification
pytest src/tests/test_model_adapter_qualification.py -v
pytest src/tests/test_phase_12_1_1_security_qualification.py -v
pytest src/tests/test_phase_12_1_1_identity_finops_production.py -v
pytest src/tests/test_phase_12_1_2_appcontainer_terminal.py -v
pytest src/tests/test_phase_12_1_2_failure_recovery.py -v

# 2. Phase 11 Core Engineering Intelligence Suites
pytest src/tests/test_phase_11_3_workspace_discipline.py -v
pytest src/tests/test_phase_11_6_autonomous_execution.py -v
pytest src/tests/test_phase_11_8_production_readiness.py -v

# 3. Bridge Protocol Wire Serialization Tests
pytest src/tests/test_bridge_runtime_protocol.py -v
pytest src/tests/test_run_bridge_turn.py -v

# 4. Target Application Suite
pytest apps/personal_finance/tests -v
```

---

## 13. Acceptance Criteria for Next Live Test

The next live provider-backed test (e.g. against Velona or OpenAI) may only be marked **ACCEPTED** if all of the following verifiable conditions are met without simulation:

1. **Authentic Electron UI Interaction:** Prompt submission must be executed via actual Electron CDP commands targeting `textarea.crusorai-composer-input` on an active, running `CrusorAI.exe` process (no console print simulation).
2. **Zero Renderer Protocol Exceptions:** The Electron console log must show 0 unhandled `TypeError` exceptions during `plan_updated`, `turn_lifecycle`, and `verification_updated` events.
3. **Genuine Model Code Generation:** All target application source files must be generated dynamically by the live LLM provider during the run (no pre-authored files committed in Git).
4. **Verifiable FinOps Receipt:** The run must produce a verifiable billing receipt showing actual tokens and non-zero INR/USD expenditure strictly within the pre-authorized budget cap.
5. **Clean Verification on Generated Code:** Automated tests must execute against the newly generated code and pass 100% in a clean, isolated workspace.
6. **Code OSS Invariant 7 Maintained:** Exactly 0 unexpected files modified in `desktop/vscode/` (`git status desktop/` remains completely clean).

