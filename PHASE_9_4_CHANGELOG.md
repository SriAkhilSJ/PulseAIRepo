# CRUSOR AI IDE — PHASE 9.4 CHANGELOG

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.3.5.1  
**Phase Objective:** Enterprise Execution Sandbox & OS-Level Process Isolation  
**Date:** 2026-11-04  

---

## 1. NEW SOURCE MODULES CREATED

| Path | Description |
| :--- | :--- |
| `src/security/__init__.py` | Package root exporting contracts, broker, and sandbox factory. |
| `src/security/contracts.py` | Data structures: `ExecutionMode`, `ExecutionRequest`, `ExecutionReceipt`, `SecurityViolationType`, `generate_approval_token`, `verify_approval_token`, `compute_receipt_hash`. |
| `src/security/sandbox/__init__.py` | Sandbox subpackage root. |
| `src/security/sandbox/base.py` | `BaseSandboxManager` abstract base class defining sandbox interface. |
| `src/security/sandbox/windows.py` | `WindowsSandboxManager`: Windows Job Objects (`kernel32.dll`), `KILL_ON_JOB_CLOSE`, process count limits, memory limits, minimal environment allowlist, path containment, network denial, and 1MB stream byte capping. |
| `src/security/sandbox/linux.py` | `LinuxSandboxManager`: Bubblewrap/unshare user, mount, PID, and network namespaces with fail-closed policy. |
| `src/security/sandbox/macos.py` | `MacOSSandboxManager`: Seatbelt `sandbox-exec` profiles with fail-closed policy. |
| `src/security/sandbox/manager.py` | Factory function `get_sandbox_manager()` selecting OS-specific sandbox backend. |
| `src/security/execution_broker.py` | Central `ExecutionBroker` singleton enforcing request authentication, fail-closed workspace resolution, single-use HMAC approval tokens, staging isolation, and immutable receipt generation. |

---

## 2. NEW TEST MODULES & BENCHMARK HARNESSES

| Path | Description |
| :--- | :--- |
| `src/tests/test_phase_9_4_execution_sandbox.py` | 8 automated pytest tests covering approval tokens, workspace validation, replay attack rejection, environment secret stripping, path traversal blocking, stream byte capping, timeout/cancellation, and fail-closed platform adapters. |
| `scripts/run_phase_9_4_adversarial_suite.py` | 24-scenario adversarial benchmark harness testing real OS-level containment against attacks. |
| `bench-results/phase94_execution_sandbox/` | Benchmark directory containing disposable workspace fixtures, synthetic secrets outside workspace, staging directories, and raw JSON telemetry. |

---

## 3. PHASE DELIVERABLES PRODUCED

1. `PHASE_9_4_BASELINE_SECURITY_AUDIT.md`
2. `PHASE_9_4_THREAT_MODEL.md`
3. `PHASE_9_4_EXECUTION_BROKER_ARCHITECTURE.md`
4. `PHASE_9_4_IMPLEMENTATION_REPORT.md`
5. `PHASE_9_4_WINDOWS_SANDBOX_EVIDENCE.md`
6. `PHASE_9_4_PLATFORM_SUPPORT_MATRIX.md`
7. `PHASE_9_4_ADVERSARIAL_TEST_RESULTS.json`
8. `PHASE_9_4_SECURITY_VERIFICATION.md`
9. `PHASE_9_4_RAW_TEST_RESULTS.json`
10. `PHASE_9_4_CHANGELOG.md`

---

## 4. VERIFICATION EVIDENCE

- **Adversarial Benchmark:** 24 / 24 scenarios passed (100.00% pass rate in 4.70s).
- **Targeted Test Suite:** 8 / 8 passed in 1.95s.
- **Consolidated Regression Suite:** 127 / 127 passed in 11.76s across 13 test modules.
- **Upstream Invariant 7:** Verified with `scripts/refresh_selective_manifest.py` (**0 drift** across 5 upstream files).
- **Paid API Expenditure:** **₹0.00** (Zero paid API calls).

