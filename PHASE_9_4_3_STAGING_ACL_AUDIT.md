# CRUSOR AI IDE — PHASE 9.4.3 STAGING ACL AUDIT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Phase:** 9.4.3 (AppContainer Least-Privilege Closure & Network Egress Proof)  
**Security Boundary:** Windows AppContainer Token & NTFS DACL Enforcement  

---

## 1. PURPOSE & PROBLEM DEFINITION

In Phase 9.4.2, the execution broker granted staging directory access using the well-known group SID `ALL APPLICATION PACKAGES` (`S-1-15-2-1`):
```text
icacls <staging_dir> /grant *S-1-15-2-1:(OI)(CI)F
```
While this permitted the sandboxed worker process to run, it violated the principle of least privilege: any AppContainer process executing on the machine under any package could potentially read or mutate the staging files of an active Crusor worker session.

Phase 9.4.3 eliminates this shared boundary by replacing `S-1-15-2-1` with the exact, cryptographically unique per-container AppContainer SID (`S-1-15-2-XXXX...`).

---

## 2. IMPLEMENTATION AUDIT (`src/security/sandbox/windows.py`)

In `WindowsSandboxManager.initialize()`:
```python
# Grant staging directory full control exclusively to the unique AppContainer SID
if staging_dir.exists():
    subprocess.run(
        ["icacls", str(staging_dir), "/grant", f"*{self._appcontainer_sid_string}:(OI)(CI)F"],
        capture_output=True,
        check=False,
    )
```

The well-known group `*S-1-15-2-1` has been completely eliminated from the staging DACL.

---

## 3. EMPIRICAL ACL AUDIT EVIDENCE

### Test ID: `ADV-LP-01`
- **Assigned Container SID:** `S-1-15-2-3713221067-1360735155-117765397-2874647687-3023873589-2548069098-1303210`
- **icacls Output:**
```text
C:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\bench-results\phase943_least_privilege\staging_lp01_27e365
    S-1-15-2-3713221067-1360735155-117765397-2874647687-3023873589-2548069098-1303210:(OI)(CI)(F)
    DESKTOP-1ULGF16\CodexSandboxUsers:(I)(OI)(CI)(RX)
    NT AUTHORITY\SYSTEM:(I)(OI)(CI)(F)
    BUILTIN\Administrators:(I)(OI)(CI)(F)
    DESKTOP-1ULGF16\Administrator:(I)(OI)(CI)(F)

Successfully processed 1 files; Failed processing 0 files
```
- **Broad `S-1-15-2-1` Grant:** **ABSENT**
- **Exact SID Full Control `(OI)(CI)(F)`:** **VERIFIED**

---

## 4. CROSS-CONTAINER ISOLATION PROOF

### Test ID: `ADV-LP-02` (Cross-Container Staging Read Denial)
- **Container A SID:** `S-1-15-2-864830919-3064290713-2613823849-682027618-2604995409-1562657727-1560887976`
- **Container B Execution:** Worker B executes in a separate AppContainer profile and attempts to read Container A's secret file:
```python
with open(secret_file_container_a, 'r') as f:
    f.read()
```
- **Observed OS Response:**
```text
CROSS_CONTAINER_DENIED:PermissionError:[Errno 13] Permission denied: '.../staging_cont_a_324da9/secret_container_a.txt'
```
- **Result:** **CONTAINED (OS Kernel DACL Denial)**

### Test ID: `ADV-LP-03` (Cross-Container Staging Write Tamper Denial)
- **Container B Execution:** Worker B attempts to create or tamper with files inside Container A's staging area:
```python
with open(tamper_target_in_container_a, 'w') as f:
    f.write('TAMPER_ATTEMPT')
```
- **Observed OS Response:**
```text
CROSS_CONTAINER_WRITE_DENIED:PermissionError:[Errno 13] Permission denied: '.../staging_cont_a2_412295/malicious_payload.exe'
```
- **File Created on Disk:** **FALSE (0 bytes)**
- **Result:** **CONTAINED (OS Kernel DACL Denial)**

---

## 5. AUDIT CONCLUSION

Staging directories are strictly isolated per AppContainer identity. Cross-container data exfiltration and cross-container tampering are completely prevented by Windows NTFS kernel access control checks.

