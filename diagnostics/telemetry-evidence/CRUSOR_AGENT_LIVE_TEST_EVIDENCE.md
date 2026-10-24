# Crusor Agent Live Hardening Test Evidence

**Date:** 2026-10-23

**Session ID:** `session-e181f632730e4daba43adedb09101923`

**Model:** `z-ai/glm-5.3-flash`

**Host environment:** Windows (win32), Python 3.14.4 / Python 3.11.2

**Target:** Agent Core hardening on `arena/a7c2c868-pulseairepo`

## 1. Scope and provenance

A live Crusor Agent evaluation executed 22 reasoning/tool steps. The desktop
agent then queried the local `~/.crusorai/runtime_events.db` and
`~/.crusorai/verification.db` databases for this session.

The live run directly demonstrates durable tool-body omission, durable secret
redaction, ordinary terminal success/non-zero failure handling, versioned
verification events, and cleanup. Deterministic priority selection and the
zero-exit masked-success edge case are corroborated by the committed benchmark
and automated-test receipt; they are not overstated as direct observations of
the listed live commands.

No raw database or token value is committed in this evidence file. The probe
used a vendor-prefix-shaped **synthetic** token; its literal value is
intentionally omitted here to avoid creating token-shaped repository content.

## 2. Live observations

### Task 1: bounded workspace behavior

**Action:** The agent performed shallow listings across the workspace root and
project subdirectories (`.crusorai`, `video-nature`, and `demo-site`).

**Observed:** Deep `node_modules`, `.next`, and generated build/cache contents
did not pollute the agent's selected context. The listing transcript alone does
not expose the scanner's internal candidate counters; deterministic bounded
top-k behavior is established separately by the benchmark and scanner tests.

### Task 2: durable redaction and tool-intent safety

**Action:** The agent wrote `scratch/security_probe.py` containing a synthetic
credential-shaped value.

**Durable storage proof (`~/.crusorai/runtime_events.db`):**

- **Tool-body omission:** `runtime_events` sequences `14246` and `14297`
  stored typed omission metadata instead of the raw file body:

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

- **Live diff masking:** `tool.result` sequence `14248` displayed:

  ```python
  DUMMY_KEY = "[redacted-secret]"
  ```

- **File-search masking:** Search results displayed `DUMMY_KEY="***"`.
- **Durable leak check:** All 70 journal rows for this session were searched
  for the exact synthetic probe value; zero matches were found.

### Task 3: terminal exit handling

**Actions:**

1. `python -c "import sys; print('Verification probe complete'); sys.exit(0)"`
   completed with exit code `0`.
2. Simulated warning/failure commands completed with non-zero exit codes `3`
   and `1`.

**Observed:** Non-zero failures produced recovery guidance without a crash or
retry loop. Because the listed failure commands genuinely exited non-zero,
this live run does not by itself exercise the distinct masked-success condition
(failure-shaped output with shell exit code `0`); that condition is covered by
the automated `test_terminal_masked_success.py` contracts.

### Task 4: typed evidence and replay data

`runtime_events.db` contained versioned `verification.updated` rows, including
sequences `14247`, `14252`, `14299`, and `14306`. A representative payload was:

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
  "workspace": "<workspace>"
}
```

The absolute Windows workspace path is normalized in this committed report.
`verification.db` ledger entry `51` recorded:

- kind: `typecheck`;
- scope: `full`;
- status: `passed` (exit code `0`);
- output: `typecheck_workspace (project: cd/): tsc --noEmit passed with 0 errors.`

The scratch security-probe files were removed after validation.

## 3. Outcome matrix

| Requirement | Evidence | Result |
|---|---|:---:|
| Central tool-body omission | SQLite rows contain typed omission metadata, not source body | **Passed** |
| Durable secret redaction | Exact synthetic probe value absent from all 70 session rows | **Passed** |
| Terminal success/non-zero failure handling | Exit codes and recovery behavior observed live | **Passed** |
| Zero-exit masked-success edge case | Automated masked-success contracts, not claimed as live | **Passed (automated)** |
| Typed verification evidence | Schema v1 evidence IDs persisted in runtime journal | **Passed** |
| Clean teardown | Scratch probe removed | **Passed** |
