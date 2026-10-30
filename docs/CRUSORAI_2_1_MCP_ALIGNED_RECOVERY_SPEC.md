# CrusorAI 2.1: Production-Grade MCP-Aligned Recovery Architecture & Restructured Phase Plan

> **Document Type**: Authoritative Technical Specification & Execution Roadmap  
> **Target Subsystem**: Autonomous Reliability & Recovery Engine (ARRE) — Phase 2.1  
> **Design Influences**: Staff Architect Peer Review + Open-Source MCP Distributed Agent Standards (At-Least-Once Delivery, Idempotency Ledgers, Two-Phase Actions, Process Supervision)  
> **Status**: Approved Blueprint for Phased Execution

---

## 1. Executive Summary & Timeline Estimate ("Bro How Long?")

To execute this properly without cutting corners, regressions, or unsafe hacks, the complete delivery of Phase 2.1 is structured into **5 distinct, sequential, independently verifiable milestones**:

```
                       PHASE 2.1 DELIVERY TIMELINE & ESTIMATES
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │ Phase 2.1-A: Pure Classifier & Evidence Provenance           ⏱️  45 mins    │
  │ Phase 2.1-B: Recovery Dispatcher & Session Process Safety    ⏱️  60 mins    │
  │ Phase 2.1-C: Authoritative Persistent Budget Registry        ⏱️  45 mins    │
  │ Phase 2.1-D: LangGraph SafeToolNode 3-Tier Lifecycle Hook    ⏱️  60 mins    │
  │ Phase 2.1-E: 12-Criterion Failure-Path Verification          ⏱️  45 mins    │
  ├─────────────────────────────────────────────────────────────────────────────┤
  │ TOTAL ESTIMATED ENGINEERING EFFORT                           ⏱️  ~4.25 hrs  │
  └─────────────────────────────────────────────────────────────────────────────┘
```

Each sub-phase produces its own clean git commit on `main`, verifiable unit/integration tests, and zero regressions against the 149-test baseline.

---

## 2. Production-Grade MCP Agent Architectural Foundations

Modern agentic protocols like the **Model Context Protocol (MCP)** treat tool calls as stateless, distributed RPC requests. When an agent tool fails or times out, treating tool execution as a naive single-shot retry causes severe real-world failure modes: duplicate side effects (e.g. double file writes, orphan zombie processes, port exhaustion), race conditions between parallel workers, and budget exhaustion.

We incorporate three foundational MCP agentic design patterns into CrusorAI 2.1:

```
                      MCP-ALIGNED ARRE ARCHITECTURE
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │ 1. Pure Classification & Input Isolation                                   │
  │    No I/O or supervisor mutation in FailureClassifier; takes immutable     │
  │    PortOwnership snapshot and ProviderErrorInfo.                           │
  ├─────────────────────────────────────────────────────────────────────────────┤
  │ 2. Three-Tier Governance Decision Matrix                                    │
  │    Decouples: Execution Allowed vs Consumes Budget vs Can Retry Original    │
  ├─────────────────────────────────────────────────────────────────────────────┤
  │ 3. Session-Scoped Process Supervision & Idempotency Ledger                 │
  │    Tracks PID, session_id, run_id. Strict boundary: Never touch another    │
  │    session's workers. Idempotency keys prevent double execution.           │
  ├─────────────────────────────────────────────────────────────────────────────┤
  │ 4. Two-Tier Budget Authority                                                │
  │    RuntimeServices is authoritative; AgentState stores UTC-anchored        │
  │    continuity checkpoints with monotonic re-baselining.                    │
  └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Restructured Phase List (Detailed Breakdown)

### Phase 2.1-A: Pure Classifier Refinement & Evidence Provenance
**Goal**: Transform `FailureClassifier` into a strictly pure diagnostic function with zero side effects or external I/O.
* **Pure Port Ownership Snapshot**:
  ```python
  class PortOwnership(NamedTuple):
      port: Optional[int]
      is_alive: bool
      is_owned: bool
      owner_session_id: Optional[str] = None
      owner_run_id: Optional[str] = None
      owner_pid: Optional[int] = None
      service_name: Optional[str] = None
  ```
* **Strict Socket Decision Logic**:
  - `EADDRINUSE`: Requires explicit `port` from metadata or URL. If port missing $\to$ `unknown_port_fail_closed`. If owned by current session $\to$ inspect/recover; if foreign or unknown session $\to$ strict **fail-closed**.
  - `ECONNREFUSED`: Known current session process starting $\to$ bounded warmup polling. Known current session dead $\to$ single supervised relaunch. Foreign or unknown session $\to$ strict **fail-closed**.
* **HTTP Provider Refinement**:
  - Distinguish HTTP 401 (`status_code=401`, fail-fast) vs HTTP 403 (`status_code=403`, fail-fast).
  - Explicit retryable set for 5xx: `{500, 502, 503, 504}`. HTTP 501 (`Not Implemented`) is explicitly **non-retryable**.
  - Structured `ProviderErrorInfo` takes authoritative precedence over ambiguous raw output strings.
* **Trusted Requirement Evidence Provenance**:
  ```python
  class RequirementEvidence(NamedTuple):
      requirement_id: str
      expected_behavior: str
      actual_behavior: str
      failed_acceptance_criterion: str
      required_correction: str
      workspace_id: str
      verification_receipt_id: str
      workspace_revision: int
      verifier_identity: str  # Must be allowlisted (e.g. gatepulse, pytest_verifier)
  ```
  - Staleness evaluation: If `workspace_revision < current_workspace_revision`, classify as `stale_evidence_suppressed` with `execution_allowed=False`.

---

### Phase 2.1-B: Recovery Strategy Dispatcher & Session Process Safety
**Goal**: Implement safe, bounded actuation with session-scoped process isolation.
* **Allowlisted `RecoveryStrategy` Enum**:
  ```python
  class RecoveryStrategy(str, Enum):
      RELAUNCH_OWNED_DEV_SERVICE = "relaunch_owned_service"
      BOUNDED_WARMUP_POLL = "bounded_warmup_poll"
      EXPONENTIAL_BACKOFF_JITTER = "exponential_backoff_jitter"
      RESPECT_RETRY_AFTER = "respect_retry_after_or_backoff"
      DRAIN_ELIGIBLE_LOGS = "drain_eligible_logs"
      TERMINATE_SESSION_WORKERS = "terminate_owned_subprocesses_and_release"
      AST_DIAGNOSTIC_FEEDBACK = "ast_diagnostic_feedback"
      SCHEMA_FEEDBACK_PROMPT = "schema_feedback_prompt"
      ALTERNATING_MUTATION_LOCK = "alternating_mutation_lock"
      REQUIREMENT_DELTA_REMEDIATION = "requirement_delta_remediation"
      FAIL_CLOSED_HALT = "fail_closed_halt"
  ```
* **Session-Scoped `ProcessSupervisor` Protocol**:
  ```python
  class ProcessSupervisor(Protocol):
      def inspect_port_owner(self, port: int) -> PortOwnership: ...
      def relaunch_service(self, port: int, session_id: str, run_id: str) -> bool: ...
      def terminate_session_processes(self, session_id: str, run_id: Optional[str] = None) -> int: ...
  ```
  - Immediate pre-actuation validation: Revalidate port ownership and session ID immediately before issuing relaunch or terminate.
  - Cross-Session Isolation Invariant: Session A **can never** kill or restart processes belonging to Session B.
* **Safe Log Drainage**:
  - Strict path allowlist: `.crusorai/logs/`, `tmp/`.
  - Rejection of symlinks, path traversals (`..`), and any target outside the designated log root.

---

### Phase 2.1-C: Authoritative Persistent Budget Registry
**Goal**: Implement dual-tier budget authority preventing race conditions and budget reset exploits.
* **RuntimeServices Authority**:
  - `RuntimeServices.recovery_budgets` holds the in-memory, thread-safe, mutex-governed tracker per session.
  - Multi-worker safety: Concurrent tool dispatches in the same session contend on a single mutex, guaranteeing the 8-attempt ceiling is never exceeded.
* **UTC-Anchored Checkpoint Serialization**:
  ```python
  class BudgetCheckpoint(TypedDict):
      session_id: str
      total_attempts: int
      failure_history: list[str]
      elapsed_seconds_at_checkpoint: float
      checkpointed_at_utc: str
      policy_version: str
  ```
* **Monotonic Re-baselining on Restoration**:
  - On restart/checkpoint load, calculate elapsed duration from `checkpointed_at_utc` + `elapsed_seconds_at_checkpoint`.
  - Re-anchor `_start_time = time.monotonic() - accumulated_elapsed`.
  - Integrity validation: Mismatched session IDs, negative elapsed time, or tampered limits trigger **fail-closed** rather than granting a fresh budget.

---

### Phase 2.1-D: LangGraph SafeToolNode 3-Tier Lifecycle Integration
**Goal**: Wire ARRE into LangGraph's tool execution boundary with explicit retry/action semantics.
* **Three-Tier Governance Decision Matrix**:
  ```python
  class RecoveryGovernanceDecision(NamedTuple):
      execution_allowed: bool        # Can the recovery strategy actuate?
      consumes_recovery_budget: bool # Does this action count against the 8-attempt limit?
      can_retry_original_call: bool  # Can the original tool call be repeated?
  ```
* **Strict Non-Idempotent Invariant**:
  - Even if a timeout error is recovered (e.g. socket re-established), `can_retry_original_call` is strictly `False` for non-idempotent tools (`write_file`, payment, destructive mutations).
  - Ambiguous timeouts fail closed to prevent duplicate real-world effects.
* **Alternating Mutation Lock**:
  - Enforced directly at the tool dispatch boundary: if `mutation_lock_active` is True, calls to test runners or verification tools are rejected until an edit/write tool records a file modification in `mutation_ledger`.

---

### Phase 2.1-E: Full Failure-Path Verification & Acceptance Gate
**Goal**: 100% test coverage over all 12 Staff Architect acceptance criteria with clean Git audit.
* **12 Dedicated Verification Scenarios**:
  1. Unknown port never causes process restart or termination.
  2. Foreign process is never terminated or relaunched.
  3. Session A cannot terminate Session B worker processes.
  4. Supervisor exception in inspection causes safe fail-closed.
  5. HTTP 401 and 403 preserve exact status codes.
  6. HTTP 501 is explicitly non-retryable.
  7. Stale verification evidence (revision mismatch) suppresses remediation.
  8. Recovery budget survives session serialization & restore without reset.
  9. Concurrent worker race conditions cannot exceed 8 attempts.
  10. Non-idempotent tool timeout recovers environment but does not repeat tool mutation.
  11. Mutation lock blocks test runner until workspace mutation occurs.
  12. Unknown recovery strategy is rejected by dispatcher.
* **Full Core Regression Suite**: Preserve 149/149 green tests.
