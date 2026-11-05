# CRUSOR AI IDE — PHASE 9.6: IPC & BRIDGE RELIABILITY REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.5  
**Implementation Source:** `src/observability/bridge_governor.py`  
**Verdict:** `DESKTOP PERFORMANCE AND OBSERVABILITY VERIFIED`  

---

## 1. BRIDGE RELIABILITY ENFORCEMENTS

### A. Request Correlation Matching
Every frame emitted by either the workbench or Python sidecar includes:
- `request_id`: Identifies the exact request-response pair.
- `correlation_id`: Ties the operation to the global user turn.
Responses arriving out of order are matched deterministically via an in-memory pending request registry.

### B. Frame Boundary Integrity
- All communication uses UTF-8 newline-delimited JSON.
- `MAX_FRAME_BYTES = 1048576` (1 MB) limit enforced. Oversized frames are rejected immediately before JSON parsing.

### C. Request Timeouts & Sweeping
- Default request timeout: 30.0 seconds (configurable per method).
- Background sweep detects stalled calls, removes them from pending registries, and records `BRIDGE_TIMEOUT` telemetry spans.

### D. Active Cancellation
- When a user clicks "Stop Generating" or closes a panel, `cancel_request(request_id)` immediately marks the pending request cancelled and dispatches a lightweight `{"type": "cancel", "request_id": "..."}` frame to the sidecar.

### E. Sidecar Disconnection & Crash Recovery
- If the Python sidecar process exits unexpectedly (crash, kill, or OOM):
  - `record_sidecar_crash()` marks connection state to disconnected.
  - All pending futures are cleanly terminated with failure callbacks.
  - The health watchdog updates status to `DEGRADED`/`UNHEALTHY` with actionable diagnostics.
