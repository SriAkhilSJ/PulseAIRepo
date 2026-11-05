# PHASE 11.7 VERIFICATION INVALIDATION & RERUN

**Component:** `src/verification/invalidation.py::VerificationInvalidationManager`  
**Verdict:** `INDEPENDENT VERIFICATION VERIFIED`  

---

## 1. POST-VERIFICATION MUTATION DETECTION

- If any file is modified after a `VerificationReport` is signed, hash comparison immediately flags a mismatch.
- The report status transitions to invalidated.
- Re-verification is strictly required before final delivery can proceed.
