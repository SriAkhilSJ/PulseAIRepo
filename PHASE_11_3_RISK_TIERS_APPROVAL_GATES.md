# PHASE 11.3 RISK TIERS & APPROVAL GATES REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.3 Workspace Discipline & Change Management  

---

## 1. RISK CLASSIFICATION TIERS

`RiskApprovalGate` (`src/workspace/risk_policy.py`) evaluates every proposed mutation into one of four deterministic tiers:

1. **`LOW_RISK`:**
   - Modifying or deleting agent-created files.
   - Non-destructive creation of new files inside authorized modules.
   - Auto-authorized under active task session.
2. **`MEDIUM_RISK`:**
   - Modifications to existing user code within active task scope.
   - Dependency updates or configuration adjustments.
   - Requires explicit task logging and transaction journal entry.
3. **`HIGH_RISK`:**
   - Deletion or overwrite of pre-existing user files.
   - Modifications to core security files, database migrations, or `desktop/SELECTIVE_MANIFEST.json`.
   - Requires explicit cryptographic approval token (`APPV-...`).
4. **`PROHIBITED`:**
   - Path escaping workspace root.
   - Writing to `.git` internals, `.env`, `.ssh`.
   - Destructive commands (`git reset --hard`, `git clean -fd`, `rm -rf /`).
   - Immediately rejected (Fail-Closed).

---

## 2. CRYPTOGRAPHIC APPROVAL TOKENS & REPLAY DEFENSE

High-risk mutations require a cryptographic single-use token:
- Format: `APPV-{HMAC_SHA256[:24]}-{EXPIRATION_TIMESTAMP}`
- Cryptographically bound to: `task_id`, `workspace_root`, `file_path`, `operation_type`, and `expiration`.
- Replay Prevention: Verified tokens are immediately recorded in `_consumed_tokens`. Replay attempts fail immediately.
