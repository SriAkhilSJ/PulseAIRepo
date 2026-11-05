# PHASE 11.5 REGRESSION REPORT SCHEMA REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Verdict:** `REGRESSION PREVENTION VERIFIED`  

---

## 1. JSON SCHEMA OVERVIEW

The `RegressionReport` dataclass (`src/regression/models.py`) defines the schema:

```json
{
  "report_id": "string (UUID)",
  "task_id": "string",
  "workspace_root": "string (path)",
  "tenant_id": "string",
  "timestamp": "float (epoch)",
  "overall_status": "CLEAN | REGRESSED | BUILD_BROKEN | SECURITY_VIOLATED | INTEGRITY_VIOLATED | RECOVERED | FAILED_UNRECOVERED",
  "baseline_summary": {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "skipped": 0,
    "duration_seconds": 0.0
  },
  "post_change_summary": {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "skipped": 0,
    "duration_seconds": 0.0
  },
  "regressions": [
    {
      "test_name": "string",
      "test_file": "string",
      "status": "FAILING",
      "duration": 0.0,
      "failure_message": "string",
      "classification": "NEW_REGRESSION"
    }
  ],
  "diagnoses": [
    {
      "test_name": "string",
      "suspected_file": "string",
      "suspected_symbol": "string",
      "certainty": "CONFIRMED | PROBABLE | POSSIBLE | UNKNOWN",
      "explanation": "string",
      "stack_trace": "string",
      "expected_behavior": "string",
      "actual_behavior": "string"
    }
  ],
  "flaky_tests": [],
  "integrity_violations": [],
  "recovery_action": {
    "is_safe_to_rollback": true,
    "actions": [],
    "affected_user_files": [],
    "refusal_reasons": []
  },
  "human_summary": "string"
}
```
