# Crusor Agent Live Hardening Test Evidence

**Date:** 2026-10-23  
**Session ID:** `session-e181f632730e4daba43adedb09101923`  
**Model:** `z-ai/glm-5.3-flash`  
**Host Environment:** Windows (win32), Python 3.14.4 / Python 3.11.2  
**Target Architecture:** Crusor Agent Core Hardening (Branch: `arena/a7c2c868-pulseairepo`)  

---

## 1. Executive Summary

A live end-to-end evaluation was executed against the **Crusor Agent** using the Agent Core verification prompt. The agent executed 22 reasoning and tool steps, completing all 4 hardening validation phases with 100% verified compliance.

---

## 2. Live Task Verifications & Proof

### Task 1: Bounded Workspace Scan & Context Selection
* **Action:** Agent performed bounded listings across the workspace root and project subdirectories (`.crusorai`, `video-nature`, `demo-site`).
* **Evidence:**
  - One-level listing discipline was strictly enforced.
  - Deep `node_modules`, `.next`, and build artifacts were pruned from the context window.
  - Context retrieval respected candidate window limits and coarse-size prioritization without ranking churn.

### Task 2: Durable Redaction & Tool-Intent Safety
* **Action:** Agent wrote `scratch/security_probe.py` containing a sensitive token:
  `API_SECRET_KEY="sk-ant-api03-sampleDummyKeyForTestingOnly1234567890"`
* **Durable Storage Proof (`~/.crusorai/runtime_events.db`):**
  - **Tool-Body Omission:** In `runtime_events` sequence `14246` and `14297`, the entire raw file body was centrally omitted inside `EventJournal.append`:
    ```json
    {
      "args": {
        "content": {
          "__omitted__": true,
          "reason": "tool_body",
          "size": 886,
          "unit": "characters"
        },
        "path": "scratch/security_probe.py"
      },
      "tool_name": "write_file"
    }
    ```
  - **Live Diff Masking:** In `tool.result` sequence `14248`, the diff preview masked the raw secret:
    ```python
    DUMMY_KEY = "[redacted-secret]"
    ```
  - **File Search Redaction:** In tool search results, the key was masked to `DUMMY_KEY="***"`.
  - **Durable Leak Check:** A database scan across all 70 journal rows for this session confirmed that raw secret strings never entered durable SQLite payloads.

### Task 3: Terminal Command Execution & Masked-Success Validation
* **Action:** The agent evaluated exit-code contracts and benign failure shapes:
  1. Clean command: `python -c "import sys; print('Verification probe complete'); sys.exit(0)"` → Exit code `0`.
  2. Failure shape: Simulated legacy fallback warning and non-zero exit codes (`exit 3`, `exit 1`).
* **Evidence:** The terminal masked-success handler caught failure signatures, surfaced actionable recovery hints, and avoided infinite retry/crash loops.

### Task 4: Evidence & Protocol Replay
* **Action:** Verified `verification.updated` envelope generation and ledger persistence.
* **Evidence:**
  - `runtime_events.db` generated versioned verification rows (e.g., sequence `14247`, `14252`, `14299`, `14306`):
    ```json
    {
      "command": "npm run typecheck",
      "evidence_id": "verify-68f5f450b1c14692ba3160808ed8700a",
      "evidence_kind": "explicit",
      "exit_code": 0,
      "kind": "typecheck",
      "schema_version": 1,
      "scope": "full",
      "status": "passed",
      "workspace": "C:\\Users\\Administrator\\Downloads\\testCRUSOR"
    }
    ```
  - `verification.db` recorded ledger entry `51`:
    - Kind: `typecheck`
    - Scope: `full`
    - Status: `passed` (Exit code: 0)
    - Output: `✅ typecheck_workspace (project: cd/): tsc --noEmit passed with 0 errors.`

---

## 3. Test Outcome Matrix

| Hardening Requirement | Verification Mechanism | Live Result | Status |
|---|---|---|:---:|
| **Central Tool-Body Omission** | `EventJournal.append` serialization boundary | Raw body replaced with typed omission metadata | **PASSED** |
| **Durable Secret Redaction** | Non-reusable persistence redactor | Zero raw secret keys stored in SQLite rows | **PASSED** |
| **Terminal Masked-Success** | Terminal error & warning handler | Benign failures diagnosed with recovery hints | **PASSED** |
| **Typed Protocol Replay** | Versioned `verification.updated` envelope | Evidence IDs and schema v1 correctly projected | **PASSED** |
| **Clean Teardown** | Workspace cleanup | Scratch security probe files cleaned up | **PASSED** |
