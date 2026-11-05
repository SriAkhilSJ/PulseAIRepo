# PHASE 11.5 RISK-BASED TEST SELECTION REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Verdict:** `REGRESSION PREVENTION VERIFIED`  

---

## 1. PURPOSE & DESIGN

Running all 300+ tests on every single one-line change introduces prohibitive latency. The `RiskBasedTestSelector` (`src/regression/selector.py`) uses Phase 11.4 `ChangeImpactReport` and static dependency graphs to intelligently select and order only the relevant tests.

---

## 2. PRIORITY HIERARCHY

| Tier | Priority Level | Target Tests | Selection Criteria |
| :--- | :--- | :--- | :--- |
| **P0** | `IMMEDIATE` | Direct Changed Tests | Tests residing in or directly testing modified files/symbols |
| **P1** | `HIGH` | Dependents & Callers | Tests for direct callers, consumers, or downstream dependencies |
| **P2** | `MEDIUM` | Contracts & APIs | Public API endpoints, database schemas, and interface contract tests |
| **P3** | `STANDARD` | Subsystem Regression | Broad test suite covering the affected functional module |
| **P4** | `EXTENDED` | End-to-End Suite | Full workspace test suite, run before final task closure |

---

## 3. TIMEOUT & BUDGET ALLOCATION

The selector allocates dynamic timeout budgets per priority tier:
- P0: Max 30 seconds
- P1: Max 60 seconds
- P2: Max 90 seconds
- P3: Max 180 seconds
- P4: Full suite execution budget

If any P0 or P1 test fails, execution halts early to prevent wasting resources on downstream tiers.
