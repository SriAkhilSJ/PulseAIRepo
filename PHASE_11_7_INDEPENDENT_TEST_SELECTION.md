# PHASE 11.7 INDEPENDENT TEST SELECTION

**Component:** `src/verification/test_selector.py::IndependentTestSelector`  
**Verdict:** `INDEPENDENT VERIFICATION VERIFIED`  

---

## 1. TEST DISCOVERY & SELECTION ALGORITHM

The verifier independently determines necessary test coverage:
1. **Target File Matching:** Discovers unit tests corresponding to modified modules.
2. **Impact-Driven Selection:** Pulls relevant tests identified by Phase 11.4 Change Impact Analysis.
3. **Security Sensitivity Probes:** Selects authentication and security tests when auth/token modules change.
4. **Milestone Regression Fallback:** Executes baseline regression suites if no specific unit tests exist.

## 2. DISCLOSURE OF UNEXECUTABLE CHECKS
- External services (e.g. live Stripe gateways, live AWS S3 buckets) are classified as `UNEXECUTABLE_CHECKS`.
- Unexecuted checks are NEVER converted into passing results.
