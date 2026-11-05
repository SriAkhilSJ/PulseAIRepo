# CRUSOR AI IDE — PHASE 9.4.3 WORKSPACE PERMISSION EVIDENCE

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Phase:** 9.4.3 (AppContainer Least-Privilege Closure & Network Egress Proof)  
**Security Boundary:** Dynamic Workspace DACL Management & Three-Zone Filesystem Model  

---

## 1. THREE-ZONE FILESYSTEM ARCHITECTURE

Crusor enforces an OS-level three-zone filesystem model:

| Zone | Path | Permitted Access | Enforcement Mechanism |
|---|---|---|---|
| **Zone A** | Input Snapshots | Read-Only | Read-only copy or container SID read grant |
| **Zone B** | Execution Staging | Read/Write | Isolated per-container SID DACL `*(SID):(OI)(CI)F` |
| **Zone C** | Host Workspace | Protected | Protected from direct mutation; worker changes staged |

---

## 2. WORKSPACE ACL LIFECYCLE AUDIT

When an operation executes under `ExecutionMode.READ_ONLY`:
1. **Dynamic Grant:** The broker grants read access (`RX`) **strictly** to the unique container SID:
   ```python
   subprocess.run(["icacls", str(ws_path), "/grant", f"*{self._appcontainer_sid_string}:(OI)(CI)RX"])
   ```
2. **Lifecycle Tracking:** The granted path is stored in `self._granted_workspace_path`.
3. **Deterministic Revocation:** During `cleanup()` (whether normal, error, cancellation, or timeout):
   ```python
   if self._granted_workspace_path and self._appcontainer_sid_string:
       subprocess.run(["icacls", str(self._granted_workspace_path), "/remove", f"*{self._appcontainer_sid_string}"])
   ```

---

## 3. EMPIRICAL VERIFICATION EVIDENCE

### Test ID: `ADV-LP-04` (Zone B Staging Read/Write Verification)
- Worker writes to output file in assigned temporary staging directory:
```python
with open(os.path.join(staging, 'zone_b_output.txt'), 'w') as f:
    f.write('ZONE_B_WRITE_SUCCESS')
```
- **Observed Result:** `ZONE_B_VERIFIED:ZONE_B_WRITE_SUCCESS` (Exit Code 0).
- **Result:** **PASS [CONTAINED]**

### Test ID: `ADV-LP-05` (Zone C Host Workspace Direct Mutation Blocked)
- Worker in `READ_ONLY` mode attempts direct appending to `host_sensitive_source.py`:
```python
with open(host_file, 'a') as f:
    f.write('TAMPERED_BY_APPCONTAINER')
```
- **Observed Result:**
```text
ZONE_C_CONTAINED:PermissionError:[Errno 13] Permission denied: '.../test_workspace/host_sensitive_source.py'
```
- **Host File Content After Execution:** `IMMUTABLE_HOST_CONFIG = True\n` (100% intact, zero mutation).
- **Result:** **PASS [CONTAINED]**

### Test ID: `ADV-LP-06` (Dynamic Scoped Grant During Execution)
- Container SID: `S-1-15-2-516862217-3193102777-1612918078-998804118-692368668-448580402-6395727`
- icacls inspection during active run:
```text
test_workspace S-1-15-2-516862217-3193102777-1612918078-998804118-692368668-448580402-6395727:(OI)(CI)(RX)
```
- **Result:** **PASS [CONTAINED]**

### Test ID: `ADV-LP-07` & `ADV-LP-08` (Deterministic Revocation on Cleanup & Timeout)
- **Normal Cleanup:** Container SID purged from workspace DACL (`residual_in_dacl: false`, `CLEANUP_SUCCESS`).
- **Timeout Cleanup:** Worker times out after 1.0s, Job Object terminates process tree, and broker cleans up profile and workspace grant.
- **Residual ACEs on Workspace Root:** **ZERO**.
- **Result:** **PASS [CONTAINED]**

