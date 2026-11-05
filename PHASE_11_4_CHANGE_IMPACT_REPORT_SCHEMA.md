# PHASE 11.4 CHANGE IMPACT REPORT SCHEMA

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.4 Change Impact Analysis  

---

## 1. MACHINE-READABLE SCHEMA (`ChangeImpactReport`)

```json
{
  "task_id": "task_123",
  "proposed_change_summary": "Update user authentication token verification",
  "changed_files": ["src/auth/jwt.py"],
  "changed_symbols": ["verify_token"],
  "direct_dependents": [...],
  "transitive_dependents": [...],
  "affected_components": [...],
  "affected_apis": [...],
  "affected_database_structures": [...],
  "affected_configuration": [...],
  "security_implications": [...],
  "architecture_implications": [...],
  "requirement_traceability": [...],
  "adr_traceability": [...],
  "public_contract_compatibility": "BACKWARD_COMPATIBLE",
  "contract_compatibility_details": [...],
  "relevant_tests": [...],
  "missing_test_coverage": [],
  "risk_classification": "CRITICAL",
  "risk_factors": ["Security-critical component modification detected: 'verify_token'"],
  "uncertainties": [],
  "recommended_implementation_scope": {
    "necessary": ["src/auth/jwt.py"],
    "related": ["src/api/auth_router.py"],
    "optional": [],
    "unrelated": [],
    "requires_approval": ["src/auth/jwt.py"]
  },
  "recommended_verification_plan": [...],
  "evidence_provenance": {...},
  "generated_timestamp": 1730741000.0
}
```
