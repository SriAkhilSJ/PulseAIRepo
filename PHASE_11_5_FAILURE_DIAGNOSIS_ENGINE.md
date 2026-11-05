# PHASE 11.5 FAILURE DIAGNOSIS ENGINE REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Verdict:** `REGRESSION PREVENTION VERIFIED`  

---

## 1. ROOT CAUSE EXTRACTION

The `FailureDiagnosisEngine` (`src/regression/diagnosis.py`) parses failure output, stack traces, and exception types:
1. **Exception Extraction:** Isolates specific exception classes (`AssertionError`, `TypeError`, `KeyError`, `AttributeError`, `ImportError`, etc.).
2. **Stack Frame Tracing:** Extracts the exact file, line number, and function where the exception occurred.
3. **Symbol Correlation:** Matches the failing stack frame against the list of symbols modified by the agent in Phase 11.4 / 11.3.
4. **Behavior Discrepancy Parsing:** Parses assertion messages (e.g., `Expected X != Received Y`) to deduce expected vs actual behavior.

---

## 2. CERTAINTY LEVELS

- **`CONFIRMED`:** Direct stack trace frame points directly inside a symbol modified by the agent in this task.
- **`PROBABLE`:** Stack trace points to a caller or consumer of a symbol modified by the agent.
- **`POSSIBLE`:** Failure occurs in a module that imports or interacts with the modified module.
- **`UNKNOWN`:** Failure stack trace shows no obvious relation to the modified files.
