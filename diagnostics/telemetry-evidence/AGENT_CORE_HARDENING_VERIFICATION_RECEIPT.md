# Agent Core Hardening Verification Receipt

**Date:** 2026-10-23  
**Branch:** `arena/a7c2c868-pulseairepo`  
**Commit Reference:** `9206348d2de43b00edd2fd6d6d1506bc0cea3652`  
**Host Environment:** Windows (win32), Python 3.14.4, pytest 9.1.1  

---

## 1. Code Compilation & Patch Hygiene

- **Bytecode Compilation (`compileall`):**
  - Command: `python -m compileall src scripts`
  - Result: **0 syntax or compilation errors** across all modules in `src/` and `scripts/`.
- **Git Diff Hygiene:**
  - Command: `git diff --check HEAD~2..HEAD`
  - Result: **Clean**, no trailing whitespace, no merge conflicts, no syntax markers.

---

## 2. Hardening Benchmark Validation

- **Command Executed:**
  ```bash
  python scripts/agent_core_hardening_benchmark.py --writes 200 --cpu-iterations 2000 --scan-runs 8
  ```
- **Live Host Measurements:**
  | Metric | Pre-Hardening Reference | Hardened Result | Delta / Improvement |
  |---|---:|---:|---:|
  | Representative Tool-Intent Payload | 50,165 B | 180 B | **-99.64%** |
  | SQLite Database (200 Intent Writes) | 10,137,600 B | 90,112 B | **-99.11%** |
  | Small Verification Event Payload | 86 B | 86 B | Identical metadata envelope |
  | Small Verification SQLite (200 Writes) | 73,728 B | 73,728 B | Stable storage footprint |
  | Sanitizer CPU (Tool Intent) | 185.5 µs median | 87.3 µs median | **-98.2 µs** (body omitted before serialization) |
  | Priority Scan Prefix Stability (8 shuffled runs) | 8 unique prefixes | 1 stable prefix | **Deterministic top-k ranking** |
  | Model API / Provider Call Cost | $0.00 (0 calls) | $0.00 (0 calls) | **Unchanged (zero provider dependency)** |

- **Security Boundary Verifications:**
  - `before_contains_body`: `true` → `after_contains_body`: `false`
  - `before_contains_opaque_secret`: `true` → `after_contains_opaque_secret`: `false`
  - `before_contains_prefixed_secret`: `true` → `after_contains_prefixed_secret`: `false`

---

## 3. Targeted Test Lane Verification

All tests executed cleanly with zero regressions:

1. **Persistence Redaction & Bounded Scan:**
   - Files: `src/tests/test_persistence_redaction.py`, `src/tests/test_bounded_scan.py`
   - Outcome: **37 passed** in 1.43s.
   - Verified:
     - Forced structured redaction in `EventJournal.append` and `VerificationLedger`.
     - Central omission of raw tool bodies (file contents, patches, HTTP payloads).
     - Non-reusable durable masking for opaque secrets, API keys, and authorization headers.
     - Worst-first bounded heap and coarse size-class prioritization in workspace scans.

2. **Context Budget, Masked Success, Protocol V2, OTel, & Typecheck:**
   - Files:
     - `src/tests/test_context_budget.py`
     - `src/tests/test_terminal_masked_success.py`
     - `src/tests/test_bridge_protocol_v2.py`
     - `src/tests/test_otel_tracing.py`
     - `src/tests/test_typecheck_subdir_project.py`
   - Outcome: **123 passed** in 2m 58s.
   - Verified:
     - Workspace context budget caps (file limits, byte ceilings, 50k directory boundaries).
     - Terminal masked-success evidence generation and recovery hints.
     - Protocol v2 bridge normalization, event bus streaming, and durable replay.
     - OpenTelemetry tracing spans and body-safe argument attributes.
     - Subdirectory TypeScript discovery and typecheck receipts.

3. **Event Safety:**
   - File: `src/tests/test_event_safety.py`
   - Outcome: **21 passed** in 1.65s.
   - Verified: Session isolation, bounded subscriber eviction, tool event pairing, and approval timeouts.

**Total Verified Passes:** **181 tests passed, 0 failed.**
