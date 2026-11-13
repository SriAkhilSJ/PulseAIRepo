# Phase 12.1.2 Remaining Limitations & Environmental Constraints
**Phase:** 12.1.2 Integration Closure  
**Date:** 2026-11-06  

---

## 1. Documented Environmental Limitations

While all architectural, runtime, and security closures are complete, the following environmental constraints are explicitly documented:

### 1. Interactive Desktop Display Dependency
- **Limitation:** In non-interactive automation environments (such as headless background agents, remote SSH sessions, or window stations without `WinSta0\Default`), Chromium graphical window initialization (`BrowserWindow`) fails with display allocation errors.
- **Impact:** CLI modes (`CrusorAI.exe --version`, `--status`), Python bridge JSON-RPC daemon, and automated test runners execute normally. Visual GUI rendering requires an interactive Windows user desktop session.

### 2. Commercial Live LLM Key Provisioning
- **Limitation:** In strict adherence to the project policy (*“Do NOT consume paid API credits without explicit authorization”*), live external commercial API queries (OpenAI, Anthropic, Gemini) were not dispatched with paid tokens.
- **Impact:** The system utilizes the high-fidelity deterministic model adapter (`ModelExecutionAdapter`), which generates syntactically validated code, performs AST checks, and records exact token metrics in FinOps without consuming external paid budget.

### 3. Local Model Service Availability
- **Limitation:** The local Ollama daemon was not running on `127.0.0.1:11434` on this development host during testing.
- **Impact:** Local model inference automatically falls back to the deterministic adapter. When an Ollama service is launched by the user, the adapter seamlessly routes inference to the local endpoint.

### 4. AppContainer Path Restrictions for User-Scope Binaries
- **Limitation:** Under Windows AppContainer security design, binaries installed strictly inside the user's home profile (such as Scoop or AppData user-level git-bash) cannot be directly executed by an AppContainer process without broad ACL modifications to the user profile directory.
- **Impact:** Terminal commands running inside the AppContainer use system binaries (`cmd.exe`, system Python, or system Git under `C:\Program Files\Git`). This is intentional OS-level least privilege behavior.

