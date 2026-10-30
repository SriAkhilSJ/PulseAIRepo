# CrusorAI 2.1 Phase 2: Master Engineering & Implementation Plan

> **Document Type**: Authoritative Technical Blueprint & Step-by-Step Implementation Contract  
> **Target Subsystem**: Autonomous Reliability & Recovery Engine (ARRE)  
> **Target Files**: `src/runtime/recovery_engine.py`, `src/tests/test_recovery_engine.py`  
> **Status**: Approved for Implementation (incorporating Staff Architect Peer Review)  

---

## 1. Executive Summary: The Discipline of Recovery

> *"Recovery must be intelligent enough to correct problems, but disciplined enough to know when to stop."*

In Phase 1, we implemented and shipped [`src/runtime/argument_normalizer.py`](file:///c:/Users/Administrator/Downloads/CRUSORAI/PulseAIRepo/src/runtime/argument_normalizer.py) on `main` (commit [`075f6a96`](https://github.com/SriAkhilSJ/PulseAIRepo/commit/075f6a96ca4268fcad551a622067826d80f9e24d)), guaranteeing schema-guarded aliasing and recursive secret redaction.

**Phase 2** refines the existing [`src/runtime/recovery_engine.py`](file:///c:/Users/Administrator/Downloads/CRUSORAI/PulseAIRepo/src/runtime/recovery_engine.py) in-place without creating duplicate modules or architectural churn. It transforms ARRE from a basic error matcher into an **execution-governed, process-aware recovery controller**.

---

## 2. Pin-to-Pin Component Specifications

```
                       ARRE PHASE 2 RECOVERY ARCHITECTURE
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │ 1. Expanded Taxonomy (14 Classes)  → Logic/Spec, Provider Tiers, Process St. │
  │ 2. Safe Default Idempotency        → is_idempotent defaults to False!       │
  │ 3. Process-Aware Connection Liveness→ Dead (relaunch) vs Alive (warmup)      │
  │ 4. Resource Strategy Separation    → Context vs Disk vs RAM vs Hard Cap     │
  │ 5. Global Recovery Budget Tracker  → Max 8 attempts, 180s, monotonic, locks  │
  └─────────────────────────────────────────────────────────────────────────────┘
```

---

### Step 1: Expanded 14-Class Failure Taxonomy

We formally expand the taxonomy from 10 classes to **14 distinct operational classes and subtypes**:

| # | Failure Class | Subtype / Condition | Is Retryable? | Max Additional Retries | Deterministic Strategy |
| :-: | :--- | :--- | :---: | :---: | :--- |
| **1** | `logic_or_specification_failure` | Requirement unfulfilled despite clean compile | ✅ Yes | 2 | `requirement_delta_remediation`: Identify missing requirement from structured verification, formulate targeted delta plan, force independent re-verification. |
| **2** | `syntax_error` | `SyntaxError`, `IndentationError` | ✅ Yes | 3 | `ast_diagnostic_feedback`: Provide exact line/column pointers to model. No unreviewed code edits. |
| **3** | `schema_argument_error` | Missing argument, conflicting alias | ✅ Yes | 2 | `schema_feedback_prompt`: Return JSON Schema delta and error code. |
| **4** | `invalid_request_error` | HTTP 400 | ❌ No | 0 | `diagnose_invalid_request`: Return actionable parameter schema error. **Never retry identical bad payload.** |
| **5** | `provider_auth_failure` | HTTP 401, 403 | ❌ No | 0 | `fail_fast_auth`: Immediate halt. Escalate to user for credentials. |
| **6** | `provider_rate_limit` | HTTP 429 | ✅ Yes | 4 | `respect_retry_after_or_backoff`: Parse RFC `Retry-After` header. Fall back to exponential backoff with jitter. |
| **7** | `provider_transient_error`| HTTP 500, 502, 503, 504 | ✅ Yes | 3 | `exponential_backoff_jitter`: Bounded exponential backoff with jitter (`min(2^attempt, 16s)`). |
| **8** | `service_not_running` | `ConnectionRefusedError` + Process Dead | ✅ Yes | 1 | `relaunch_owned_service`: Relaunch managed dev server if owned by CrusorAI supervisor. |
| **9** | `network_warmup_delay` | `ConnectionRefusedError` + Process Alive | ✅ Yes | 2 | `bounded_warmup_poll`: Short pause (1.5s) to allow listening port to bind. |
| **10**| `flaky_network_timeout` | `TimeoutError` (Idempotent=True) | ✅ Yes | 2 | `bounded_idempotent_retry`: Additional attempts only when tool registry verifies idempotency. |
| **11**| `assertion_failure` | Unit test exit code > 0 | ✅ Yes | 3 | `alternating_mutation_lock`: Lock test execution until file modification occurs. |
| **12**| `disk_exhaustion` | Errno 28 (No space left on device) | ✅ Yes | 1 | `drain_eligible_logs`: Safely truncate ephemeral debug logs; request disk clean. |
| **13**| `hard_token_budget_stop` | Token ceiling reached | ❌ No | 0 | `hard_stop_grace_summary`: Cease tool execution; emit graceful completion summary. |
| **14**| `permission_or_safety_denial`| EACCES, Path escape, Guard block | ❌ No | 0 | `audit_trail_fail_closed`: Halt immediately with security audit receipt. |

---

### Step 2: Safe Default Idempotency & Process Liveness Protocol

#### Default Idempotency Invariant
* **Rule**: `is_idempotent` must **default to `False`**.
* Only tools explicitly registered in `IDEMPOTENT_TOOL_REGISTRY` (e.g. `read_file`, `grep_search`, `http_get`) are recognized as idempotent.
* Destructive or stateful operations (`write_file`, `terminal`, payment execution) default to `is_idempotent=False`. If they encounter a timeout, they **fail closed without blind retries**.

#### Process-Aware Connection Recovery
When `ConnectionRefusedError` or `ECONNREFUSED` occurs on port $P$:
```python
def evaluate_connection_refused(port: int, process_supervisor: Optional[ProcessSupervisor]) -> FailureClassification:
    if not process_supervisor:
        return FailureClassification(
            failure_class="service_not_running",
            is_retryable=False,
            max_additional_retries=0,
            recommended_strategy="unsupervised_port_investigate",
            diagnostic_message=f"Connection refused on port {port}. No process supervisor attached; manual inspection required.",
        )

    is_alive, is_owned = process_supervisor.inspect_port_owner(port)

    if is_alive:
        # Process is alive but socket not accepting yet -> Warmup delay
        return FailureClassification(
            failure_class="network_warmup_delay",
            is_retryable=True,
            max_additional_retries=2,
            recommended_strategy="bounded_warmup_poll",
            diagnostic_message=f"Process on port {port} is initializing. Polling for readiness.",
        )
    elif is_owned:
        # Process was launched by CrusorAI but died -> Safe to relaunch
        return FailureClassification(
            failure_class="service_not_running",
            is_retryable=True,
            max_additional_retries=1,
            recommended_strategy="relaunch_owned_service",
            diagnostic_message=f"Managed service on port {port} terminated unexpectedly. Attempting single relaunch.",
        )
    else:
        # Port belongs to unknown / foreign system process -> Strictly forbid termination
        return FailureClassification(
            failure_class="service_not_running",
            is_retryable=False,
            max_additional_retries=0,
            recommended_strategy="unowned_service_fail_closed",
            diagnostic_message=f"Connection refused on port {port}. Foreign process detected; cannot restart unowned process.",
        )
```

---

### Step 3: Global Recovery Budget Tracker (`GlobalRecoveryBudgetTracker`)

Per-session, thread-safe, monotonic accounting enforcing global ceilings so chained individual failures cannot drain the user's budget.

```python
import threading
import time

class GlobalRecoveryBudgetTracker:
    def __init__(
        self,
        max_total_recovery_attempts: int = 8,
        max_recovery_wall_time_seconds: float = 180.0,
        max_identical_failure_repeats: int = 2,
    ) -> None:
        self.max_total_attempts = max_total_recovery_attempts
        self.max_wall_time = max_recovery_wall_time_seconds
        self.max_identical_repeats = max_identical_failure_repeats

        self._lock = threading.Lock()
        self._start_time = time.monotonic()
        self._total_attempts = 0
        self._failure_history: list[str] = []

    def check_recovery_permitted(self, failure_fingerprint: str) -> tuple[bool, Optional[str]]:
        """Evaluate whether recovery is permitted under global ceilings."""
        with self._lock:
            # 1. Total recovery attempt limit
            if self._total_attempts >= self.max_total_attempts:
                return False, f"GLOBAL_RECOVERY_LIMIT_EXCEEDED: Maximum total recovery attempts ({self.max_total_attempts}) reached."

            # 2. Wall-clock time ceiling
            elapsed = time.monotonic() - self._start_time
            if elapsed >= self.max_wall_time:
                return False, f"GLOBAL_RECOVERY_TIMEOUT: Recovery wall time ({elapsed:.1f}s) exceeded limit of {self.max_wall_time}s."

            # 3. Identical failure loop breaker
            recent_repeats = self._failure_history[-self.max_identical_repeats:]
            if len(recent_repeats) == self.max_identical_repeats and all(f == failure_fingerprint for f in recent_repeats):
                return False, f"DOOM_LOOP_TERMINATION: Identical failure '{failure_fingerprint}' repeated {self.max_identical_repeats} consecutive times."

            return True, None

    def record_recovery_attempt(self, failure_fingerprint: str) -> None:
        with self._lock:
            self._total_attempts += 1
            self._failure_history.append(failure_fingerprint)
```

---

### Step 4: Verification & Test Plan for Phase 2

We will write **12 focused unit tests** in `src/tests/test_recovery_engine.py`:

1. `test_logic_or_specification_failure_classification`: Verifies requirement delta feedback.
2. `test_http_400_fails_closed_without_retry`: Verifies invalid requests are not blindly retried.
3. `test_http_429_respects_retry_after`: Verifies parsing of `Retry-After: 12`.
4. `test_http_5xx_exponential_backoff`: Verifies backoff calculation and bounded retry flag.
5. `test_connection_refused_process_alive_warmup`: Verifies classification as `network_warmup_delay`.
6. `test_connection_refused_process_dead_owned`: Verifies classification as `service_not_running` (relaunch).
7. `test_connection_refused_unowned_fails_closed`: Verifies refusal to kill or restart foreign PIDs.
8. `test_default_idempotency_is_false`: Verifies unspecified idempotency rejects blind retries.
9. `test_global_recovery_budget_total_attempts_ceiling`: Verifies halt at 8 attempts across mixed errors.
10. `test_global_recovery_budget_wall_time_limit`: Verifies halt at 180s monotonic ceiling.
11. `test_global_recovery_budget_identical_failure_breaker`: Verifies doom loop termination after 2 identical repeats.
12. `test_resource_exhaustion_strategy_separation`: Verifies disk full (`drain_logs`) vs hard token stop (`grace_summary`).

---

## 3. Implementation Phasing & Commit Gates

```
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 2 Implementation Steps                                           │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Refine src/runtime/recovery_engine.py in-place with 14 classes      │
│ 2. Add GlobalRecoveryBudgetTracker & safe idempotency defaults         │
│ 3. Add 12 focused unit tests in src/tests/test_recovery_engine.py      │
│ 4. Run full 94-test core regression suite (ensure 100% pass)           │
│ 5. Commit to main with clean verification receipts                     │
└────────────────────────────────────────────────────────────────────────┘
```

This plan incorporates 100% of the architectural review requirements. Once you give the go-ahead, we will execute Step 1 immediately.
