# CRUSOR AI IDE — PHASE 9.4 THREAT MODEL

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.4 (Enterprise Execution Sandbox & OS-Level Process Isolation)  
**Standard:** STRIDE / Zero-Trust Execution Isolation  
**Target Architecture:** Multi-tier Desktop AI IDE (Electron + Python Backend + Isolated Workers)  

---

## 1. ASSETS & PROTECTION PRIORITIES

| Asset ID | Asset Name | Description | Sensitivity | Impact of Compromise |
| :--- | :--- | :--- | :--- | :--- |
| **A-1** | **User Credentials & Private Keys** | SSH keys (`~/.ssh/id_*`), cloud credentials (`~/.aws`, `~/.azure`, `gcloud`), Git credentials, API keys (`OPENAI_API_KEY`, etc.). | **Critical** | Complete compromise of developer accounts, cloud infrastructure, and private repositories. |
| **A-2** | **Host Filesystem Integrity** | System files, user profile documents, application data, other workspace repositories on the machine. | **Critical** | System instability, data destruction, ransomware, or host persistence. |
| **A-3** | **Project Repository & Git State** | User code, untracked files, uncommitted changes, Git history, dirty buffers, and undo history. | **High** | Code corruption, loss of uncommitted work, unauthorized commits. |
| **A-4** | **Host System Resources** | CPU time, memory, disk I/O, process count, disk capacity. | **High** | Denial of Service (DoS), freeze/crash of desktop IDE, host machine lockup. |
| **A-5** | **Local Network & Infrastructure** | Intranet services, router administration interfaces, cloud metadata endpoints (`169.254.169.254`), localhost dev servers. | **High** | Lateral movement, SSRF, unauthorized internal API invocation. |
| **A-6** | **Agent Runtime & FinOps State** | LangGraph memory, SQLite ledgers, TokenTracker, SafetyGuard policy state. | **High** | Bypassing cost limits, corrupting audit trails, falsifying task receipts. |

---

## 2. TRUST BOUNDARIES & ARCHITECTURAL TIERS

```text
[TIER 0: USER INTERACTION & HOST OS]
  ▲  Human Developer / Operating System Shell
══════════════════════════════════════════════════════════════════════════════════════ [TRUST BOUNDARY 1: User / UI]
[TIER 1: CRUSOR DESKTOP SHELL]
  ├── Electron Main Process (`CrusorAI.exe`)
  └── VS Code Workbench Renderer (Monaco, Custom Contributions)
══════════════════════════════════════════════════════════════════════════════════════ [TRUST BOUNDARY 2: Desktop / RPC]
[TIER 2: AGENT CORE RUNTIME]
  ├── Python Backend (`python.exe` - LangGraph Runtime)
  ├── SafetyGuard & Approval Verification
  ├── Financial Ledger & Token Accounting
  └── Task Validation Engine
══════════════════════════════════════════════════════════════════════════════════════ [TRUST BOUNDARY 3: Agent / Execution Broker]
[TIER 3: SECURE EXECUTION BROKER]
  ├── Request Authentication & Approval Token Binding
  ├── Staging Manager (Mode A / Mode B Workspace Staging)
  └── OS Sandbox Manager Factory
══════════════════════════════════════════════════════════════════════════════════════ [TRUST BOUNDARY 4: Host Kernel / Isolated Worker]
[TIER 4: ISOLATED EXECUTION WORKER (SANDBOXED PROCESS)]
  ├── Windows Job Object (CPU, Memory, Active Process limits, Tree Termination)
  ├── Restricted Token (LUA / Stripped Privileges)
  ├── Sanitized Environment (Allowlist only, Zero Secrets)
  ├── Isolated Staging Directory (Controlled Filesystem Mount)
  └── Network Isolation (`NETWORK = DENY`)
```

---

## 3. ATTACK SURFACES & THREAT SCENARIOS

### 3.1 Scenario S-1: Malicious Code Execution (Python / JS / Shell)
- **Threat:** Model generates code designed to scan the host filesystem, install persistence via registry/startup, or execute shell commands.
- **Attack Vector:** Model calls `execute_code` or `run_terminal` with arbitrary payloads.
- **STRIDE:** Elevation of Privilege, Tampering.
- **Mitigation:**
  - `execute_code` is decoupled from the agent process. It runs in an isolated subprocess under the Execution Broker.
  - Subprocess is bound to a Windows Job Object with memory and process limits.
  - Restricted Token prevents administrative privilege escalation.

### 3.2 Scenario S-2: Filesystem Traversal & Symlink/Junction Escapes
- **Threat:** Agent executes a script or command with relative traversal (`../../../../Windows`) or creates an NTFS junction/symlink inside the workspace pointing to `C:\Users\Administrator`.
- **Attack Vector:** Subprocess attempts to read or mutate files outside authorized workspace boundaries.
- **STRIDE:** Information Disclosure, Tampering.
- **Mitigation:**
  - Filesystem access is strictly jailed via the Broker Staging Area.
  - Path canonicalization resolves all reparse points, NTFS junctions, and symbolic links before allowing file operations.
  - Real-time path containment verification blocks operations resolving outside the staging/workspace root.

### 3.3 Scenario S-3: Credential & Secret Theft via Environment Inheritance
- **Threat:** Command executes `env`, `set`, or inspects `os.environ` to harvest API keys (`OPENAI_API_KEY`, etc.), cloud tokens, or git credentials.
- **Attack Vector:** Agent terminal execution inherits parent process environment.
- **STRIDE:** Information Disclosure.
- **Mitigation:**
  - Explicit minimal allowlist policy (`MinimalEnvironmentPolicy`).
  - Strict stripping of all credentials, API keys, SSH configs, and token variables.
  - Only safe OS variables (`SYSTEMROOT`, `COMSPEC`, `PATH`, sanitized `TMP`/`TEMP`) are provided.

### 3.4 Scenario S-4: Unrestricted Outbound Network Access & Data Exfiltration
- **Threat:** Malicious payload initiates outbound HTTP/TCP connection to exfiltrate files or contact external command-and-control servers.
- **Attack Vector:** `curl`, `python -m urllib`, `requests`, PowerShell `Invoke-WebRequest`, raw sockets.
- **STRIDE:** Information Disclosure, Tampering.
- **Mitigation:**
  - Default policy: `NETWORK = DENY`.
  - Windows Sandbox denies network access (proxy/firewall restrictions, lack of network capability in sandbox token, local socket interdiction).
  - Explicit human approval required for any task demanding network capability.

### 3.5 Scenario S-5: Resource Exhaustion & Denial of Service (DoS)
- **Threat:** Malicious script initiates a fork-bomb, allocates gigabytes of RAM, or writes infinite bytes to disk to lock up the host system.
- **Attack Vector:** Unbounded subprocess spawning or infinite loops.
- **STRIDE:** Denial of Service.
- **Mitigation:**
  - Windows Job Object enforces `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` (max 10 processes).
  - Windows Job Object enforces `JOB_OBJECT_LIMIT_JOB_MEMORY` (hard cap, e.g. 512MB).
  - Output streams (`stdout`/`stderr`) capped at 1MB with automatic truncation.
  - Bounded wall-clock timeouts terminate the entire Job Object process tree via `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.

### 3.6 Scenario S-6: Forged Approval & Stale Token Replay
- **Threat:** Compromised tool dispatcher attempts to execute unauthorized commands by fabricating approval flags or reusing prior approvals.
- **Attack Vector:** Replaying previously issued approval tokens or passing `approved=True` directly.
- **STRIDE:** Spoofing, Elevation of Privilege.
- **Mitigation:**
  - Cryptographic approval binding: Approval token is a cryptographically signed/hashed token binding `(session_id, request_id, command_hash, workspace_id, expiry)`.
  - Single-use consumption: Tokens are invalidated immediately upon consumption (preventing replay attacks).

### 3.7 Scenario S-7: Shell Dialect & Injection Divergence
- **Threat:** Exploit subtle differences between direct argv execution and shell parsing (`cmd.exe /c` vs `powershell.exe` vs direct process execution) to evade command filters.
- **Attack Vector:** Metacharacter injection (`&`, `|`, `;`, `%VAR%`, backticks).
- **STRIDE:** Tampering.
- **Mitigation:**
  - Prefer direct structured argv vectors wherever possible.
  - When shell invocation is required, wrap within isolated script files inside staging rather than passing arbitrary inline strings to the command line interpreter.

---

## 4. RESIDUAL RISKS & ACCEPTABLE TOLERANCES

1. **Kernel Zero-Day Exploits:** An exploit in Windows `ntoskrnl.exe` or graphics drivers could escape Job Object and Restricted Token boundaries. This is mitigated by defense-in-depth (host OS patching, least-privilege user accounts).
2. **Side-Channel Timing Attacks:** Microarchitectural timing attacks (Spectre/Meltdown) between isolated workers and parent processes on shared CPU cores. Acceptable enterprise tolerance for local IDE development environments.
3. **Pre-Existing Host Malware:** If the host machine is already compromised prior to running Crusor, the sandbox cannot guarantee host integrity.

---

## 5. THREAT MODEL CONCLUSION

To achieve true enterprise-grade execution security, Crusor AI IDE cannot rely on application-level string checks or approval booleans alone. It must enforce **hardware- and OS-level boundaries**:
1. Dedicated Execution Broker as the sole gateway for process creation.
2. Operating system process jailing via Windows Job Objects and Restricted Tokens.
3. Strict filesystem staging isolating workspaces from direct mutation.
4. Minimal allowlisted environment stripping all credentials.
5. Strict network denial by default.

