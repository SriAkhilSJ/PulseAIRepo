# PHASE 11.4 BLAST RADIUS & RISK ASSESSMENT REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.4 Change Impact Analysis  

---

## 1. EVIDENCE-BASED RISK TIERS

`BlastRadiusRiskAssessor` (`src/impact/risk_assessor.py`) classifies change risk:

| Risk Tier | Criteria | Explanation |
|---|---|---|
| `CRITICAL` | Auth, crypto, token, password, sandbox, or Upstream Invariant 7 modifications | Immediate threat to system security or core platform boundaries |
| `HIGH` | Database schema changes, breaking API contracts, wide blast radius (>15 components), or zero test coverage | Risk of persistent data corruption or widespread regressions |
| `MEDIUM` | Moderate blast radius (>3 components) or potentially breaking interface changes | Requires careful verification and caller review |
| `LOW` | Isolated modification with local blast radius and existing passing tests | Minimal risk |

---

## 2. EXPLICIT FACTOR EXPLANATIONS & UNCERTAINTY DISCLOSURE

The assessor never outputs an arbitrary numerical score without rationale. Every report includes `risk_factors` explaining the contributing factors, and `uncertainties` disclosing heuristic or unverified relationships.
