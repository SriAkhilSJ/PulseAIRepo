# CrusorAI 2.1 Phase 2.1: Autonomous Recovery Strategy Execution & Runtime Integration

> **Document Type**: Authoritative Technical Architecture & Implementation Blueprint  
> **Target Subsystem**: Autonomous Reliability & Recovery Engine (ARRE) — Phase 2.1  
> **Status**: Approved & Ready for Execution  

---

## 1. Architectural Posture & Invariants

```
                                CRUSORAI 2.1 ARRE PHASE 2.1
  ┌────────────────────────────────────────────────────────────────────────────────────────┐
  │ 1. Detection (Phase 2 Classifier)       → 15-Class Taxonomy + Structured Provider Info │
  │ 2. Revision-Bound Evidence              → workspace_revision & verifier_identity audit  │
  │ 3. Safe Socket Fallback                 → Unknown port strictly FAILS CLOSED           │
  │ 4. Execution (Recovery Dispatcher)      → Relaunch, Warmup, Backoff, Log Drain, OOM GC  │
  │ 5. Session Governance (Budget Tracker)  → Atomic reservation + Checkpoint Persistence  │
  │ 6. Lifecycle Wiring (SafeToolNode)      → LangGraph interceptor & State reconciliation │
  └────────────────────────────────────────────────────────────────────────────────────────┘
```

### Invariant 1: Separation of Detection from Execution
* `FailureClassifier` remains a pure, deterministic diagnostic function mapping inputs (`error`, `exit_code`, `provider_info`, `evidence`, `supervisor`) to `FailureClassification`.
* `RecoveryStrategyDispatcher` is the active actuation engine that interprets approved strategies and performs safe, bounded mutations (e.g. relaunching owned dev servers, sleeping with jitter, truncating ephemeral logs, terminating owned workers).

### Invariant 2: Revision-Bound Acceptance Verification
* `RequirementEvidence` must record `workspace_revision: int` and `verifier_identity: str`.
* If `workspace_revision < current_workspace_revision`, the evidence is diagnosed as stale. Remediations targeting outdated revisions are suppressed.

### Invariant 3: Zero-Guess Socket Boundaries
* If `ECONNREFUSED` or `EADDRINUSE` occurs and a port cannot be parsed from the structured error or error text, the engine never assumes port 8000.
* It returns `unowned_service_collision` with `recommended_strategy="unknown_port_fail_closed"` and `is_retryable=False`.

### Invariant 4: Persistent Session Budgeting Across Resumptions
* `GlobalRecoveryBudgetTracker` supports lossless serialization (`to_dict()`) and reconstruction (`from_dict()`).
* In LangGraph, `AgentState` records `recovery_budget_state`. Resuming a session rehydrates the exact attempt count and elapsed wall-clock time, preventing malicious or accidental budget reset loops.

---

## 2. Component Specifications

### 2.1 Structured Provider Error & Classifier Refinements

```python
class ProviderErrorInfo(NamedTuple):
    status_code: int
    provider: str
    request_id: Optional[str] = None
    retry_after: Optional[str] = None
    error_type: Optional[str] = None
    message: Optional[str] = None

class RequirementEvidence(NamedTuple):
    requirement_id: str
    expected_behavior: str
    actual_behavior: str
    failed_acceptance_criterion: str
    required_correction: str
    workspace_revision: int = 0
    verifier_identity: str = "unknown"
```

#### Refined Classifier Rules:
1. **HTTP 401 vs 403**:
   - `HTTP 401`: `status_code=401`, `diagnostic_message="Provider authentication failed (HTTP 401). Halting to prevent credential lockout."`
   - `HTTP 403`: `status_code=403`, `diagnostic_message="Provider permission denied (HTTP 403). Access forbidden."`
2. **Port Extraction**:
   - Matches port regex `(?:port\s*[:=]?\s*|:::|:)(\d{3,5})\b`.
   - If not found $\to$ `metadata={"port": None, "is_owned": False}`, `recommended_strategy="unknown_port_fail_closed"`, `is_retryable=False`.

---

## 3. Recovery Strategy Dispatcher (`src/runtime/recovery_dispatcher.py`)

```python
class ProcessSupervisor(Protocol):
    def inspect_port_owner(self, port: int) -> tuple[bool, bool]:
        """Returns (is_alive, is_owned_by_crusorai)."""
        ...
    def relaunch_service(self, port: int) -> bool:
        """Controlled relaunch of CrusorAI-owned process."""
        ...
    def terminate_owned_processes(self) -> int:
        """Terminate all CrusorAI-owned child worker processes; return count."""
        ...

class RecoveryExecutionResult(NamedTuple):
    strategy: str
    success: bool
    action_taken: str
    next_instruction: Optional[str]
    metadata: Dict[str, Any]
```
