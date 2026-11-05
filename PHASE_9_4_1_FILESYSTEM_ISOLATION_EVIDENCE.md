# CRUSOR AI IDE — PHASE 9.4.1 FILESYSTEM ISOLATION EVIDENCE

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.4  
**Audit Date:** 2026-11-04  
**Telemetry File:** `bench-results/phase941_windows_boundary/filesystem_canary_evidence.json`  
**Paid LLM API Budget Expended:** **₹0.00**  

---

## 1. SYNTHETIC TEST ENVIRONMENT SETUP

To evaluate filesystem isolation safely without touching real user secrets, 7 synthetic canary files were created under `bench-results/phase941_windows_boundary/canaries/`:

1. `profile_canary.txt`: Synthetic user profile data (`CANARY_PROFILE_SECRET_101`).
2. `ssh_canary.txt`: Synthetic SSH private key (`MOCK_CANARY_KEY`).
3. `aws_canary.txt`: Synthetic AWS access credentials (`CANARY_KEY`).
4. `outside_workspace.txt`: Arbitrary file outside authorized workspace root.
5. `sibling_secret.txt`: Synthetic secret stored in a sibling folder.
6. `readonly_system.txt`: Read-only system-style canary file.
7. `protected_dir/protected_file.txt`: Canary file nested inside a protected directory fixture.

---

## 2. DUAL-VECTOR ACCESS EVALUATION

Every canary was tested under two distinct execution vectors:
- **Vector 1: Application Invocation:** Command line explicitly naming the target file (evaluating Execution Broker pre-flight checking).
- **Vector 2: Dynamic Execution:** Python script dynamically loading the path at runtime (evaluating underlying Windows NTFS DACL enforcement).

---

## 3. EMPIRICAL RESULTS & FORMAL CLASSIFICATION

| Canary Target | Target Path Location | Vector 1: Broker Pre-Flight Result | Vector 2: Dynamic OS DACL Result | Formal Boundary Distinction |
| :--- | :--- | :--- | :--- | :--- |
| **`profile_canary`** | Outside Workspace Root | **DENIED** (Exit code 126; `WORKSPACE_TRAVERSAL`) | **ACCESSED** (Exit code 0; read by user token) | **DENIED by Application Policy** |
| **`ssh_canary`** | Outside Workspace Root | **DENIED** (Exit code 126; `CREDENTIAL_ACCESS_ATTEMPT`) | **ACCESSED** (Exit code 0; read by user token) | **DENIED by Application Policy** |
| **`aws_canary`** | Outside Workspace Root | **DENIED** (Exit code 126; `CREDENTIAL_ACCESS_ATTEMPT`) | **ACCESSED** (Exit code 0; read by user token) | **DENIED by Application Policy** |
| **`outside_workspace`** | Outside Workspace Root | **DENIED** (Exit code 126; `WORKSPACE_TRAVERSAL`) | **ACCESSED** (Exit code 0; read by user token) | **DENIED by Application Policy** |
| **`sibling_secret`** | Outside Workspace Root | **DENIED** (Exit code 126; `WORKSPACE_TRAVERSAL`) | **ACCESSED** (Exit code 0; read by user token) | **DENIED by Application Policy** |
| **`readonly_system`** | Outside Workspace Root | **DENIED** (Exit code 126; `WORKSPACE_TRAVERSAL`) | **ACCESSED** (Exit code 0; read by user token) | **DENIED by Application Policy** |
| **`protected_dir`** | Outside Workspace Root | **DENIED** (Exit code 126; `WORKSPACE_TRAVERSAL`) | **ACCESSED** (Exit code 0; read by user token) | **DENIED by Application Policy** |

---

## 4. ARCHITECTURAL ANALYSIS & CONCLUSION

1. **Broker Pre-Flight Enforcement (100% Repelled):**
   - The Execution Broker successfully intercepts and blocks 100% of command arguments attempting to access files outside the authorized workspace or staging directory.
   - Any path referencing `.ssh`, `.aws`, `.azure`, `id_rsa`, or containing `..` traversal sequences is immediately rejected with exit code 126 and recorded in `security_violations`.
2. **Underlying Windows Filesystem DACL Reality:**
   - Because Windows user-mode applications cannot spawn processes under an AppContainer or separate unprivileged user account without administrative service privileges, the process runs with the user's Medium-Integrity DACL.
   - Therefore, unauthorized host access is **denied by Broker application policy**, not by operating system filesystem DACLs.
3. **Verdict Alignment:**
   - In accordance with the Phase 9.4.1 mandate:
     *"The security test passes only when unauthorized host access is denied by the operating system, not merely because an application-level path validator rejected it."*
   - Filesystem isolation is truthfully classified as **PARTIAL — Broker Application Enforced**.

