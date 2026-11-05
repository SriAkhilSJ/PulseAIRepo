# PHASE 11.7 VERIFICATION REPORT SCHEMA

**Component:** `src/verification/models.py::VerificationReport`  
**Storage Location:** `.crusorai/verification/{task_id}/verification_report.json`  
**Verdict:** `INDEPENDENT VERIFICATION VERIFIED`  

---

## 1. CORE REPORT FIELDS

- `task_id`, `workspace_id`, `original_user_request`
- `repository_revision`, `implementation_revision` (SHA256 snapshot)
- `scope`: Changed files and acknowledged limitations
- `requirement_coverage`: Detailed list of `RequirementVerificationRecord`s
- `test_selection` & `test_execution_results`
- `test_integrity`: Weak test audit results
- `runtime_results`: Entry point startup probe details
- `workflow_results`: End-to-end transactional flow records
- `security_findings` & `quality_findings`
- `verdict` & `verdict_rationale`
- `evidence_digest`: Cryptographic SHA256 signature across all evidence fields
