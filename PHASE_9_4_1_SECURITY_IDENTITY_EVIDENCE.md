# CRUSOR AI IDE — PHASE 9.4.1 SECURITY IDENTITY EVIDENCE

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.4  
**Audit Date:** 2026-11-04  
**Telemetry File:** `bench-results/phase941_windows_boundary/process_token_evidence.json`  
**Paid LLM API Budget Expended:** **₹0.00**  

---

## 1. RUNTIME SECURITY IDENTITY CAPTURE

Runtime inspection of a process spawned under `WindowsSandboxManager` via `whoami /all` reveals the following security token properties:

```text
USER INFORMATION
----------------
User Name:                     desktop-1ulgf16\administrator
User SID:                      S-1-5-21-3927822043-602086999-1184865301-500

MANDATORY INTEGRITY LABEL
-------------------------
Integrity Level:               Medium Mandatory Level
SID:                           S-1-16-8192

GROUP SIDS & ATTRIBUTES
-----------------------
Everyone                       (S-1-1-0)             Mandatory group, Enabled by default
BUILTIN\Users                  (S-1-5-32-545)        Mandatory group, Enabled by default
NT AUTHORITY\Authenticated     (S-1-5-11)            Mandatory group, Enabled by default
NT AUTHORITY\INTERACTIVE       (S-1-5-4)             Mandatory group, Enabled by default
BUILTIN\Administrators         (S-1-5-32-544)        Group used for deny only

PRIVILEGES
----------
SeChangeNotifyPrivilege        Bypass traverse checking    Enabled
All other privileges                                       Disabled or Not Held
```

---

## 2. DETAILED SECURITY PROPERTY EVALUATION

| Property | Actual Value | Security Assessment |
| :--- | :--- | :--- |
| **Token Type** | Primary Interactive Token | Child process inherits the standard user-mode token of the desktop session. |
| **Integrity Level** | Medium Mandatory Level (`S-1-16-8192`) | Standard desktop application integrity level; not Low Integrity (`S-1-16-4096`). |
| **AppContainer SID** | **None (Not Present)** | Process does not execute in an AppContainer package. |
| **Restricted SIDs** | **None** | Process does not carry a restricted SIDs table. |
| **Administrative Power** | **Deny Only** | Administrative SID is stripped to deny-only; cannot modify system files or install drivers. |
| **Parent/Child Relationship** | `python.exe` $\rightarrow$ `cmd.exe` / worker | Process is spawned as a child and assigned to parent Job Object. |

---

## 3. IDENTIFICATION OF REMAINING EXPOSURE

Because the worker executes as `desktop-1ulgf16\administrator` at `Medium Mandatory Level` (rather than a separate restricted OS account or AppContainer):
1. **Host Filesystem Visibility:** Standard Windows NTFS discretionary access control lists (DACLs) grant read access to user-owned files in `C:\Users\Administrator`. If an agent-generated script dynamically constructs paths without passing them to the command line (e.g. `open(Path.home() / 'secret.txt')`), Windows kernel DACLs permit the read.
2. **Mitigation Enforced:** Crusor relies on:
   - **Pre-flight Argument Inspection:** Rejecting any command that mentions credential keywords or directory traversal sequences (`..`).
   - **Isolated Staging (Mode B):** Forcing working directory into `bench-results/phase941_windows_boundary/staging` so default relative file operations remain isolated.
   - **Minimal Environment:** Stripping all API keys and credential paths from environment variables.
3. **True OS-Level Fix:** Complete OS-level filesystem jailing on Windows requires either:
   - Spawning workers inside a Windows AppContainer with isolated capabilities, or
   - Spawning workers under a dedicated restricted local user account (e.g. `crusor_worker_sandbox`) with explicit DACL denying access to the main user profile.
   Since user-mode desktop applications cannot create AppContainers or logon new accounts without administrator service rights, this boundary is truthfully recorded as **Broker/Application Enforced**.

