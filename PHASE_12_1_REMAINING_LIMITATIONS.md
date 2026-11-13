# PHASE 12.1 REMAINING LIMITATIONS
## Transparent Disclosure of Technical & Operational Boundaries

**Date:** 2026-11-06  
**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Status:** DISCLOSED & DOCUMENTED

---

### 1. Executive Summary

While Phase 12.1 resolved the critical P0 bypasses (routing file mutations through `WorkspaceMutationBroker`, integrating `EngineeringExecutionOrchestrator` into `src/bridge/__main__.py`, connecting `ModelExecutionAdapter`, and closing identity and FinOps gaps), several technical and operational boundaries remain. In adherence to Crusor's truthful reporting invariants, these limitations are explicitly documented.

---

### 2. Documented Technical Limitations

1. **Long-Running Process Foreground Timeout Promoted to Background:**
   - In `src/tools/terminal_tools.py`, commands that exceed the foreground timeout threshold (600s) are promoted to tracked background processes. While this prevents mechanical timeout retries, the desktop UI cannot receive realtime streaming logs from background processes until explicitly queried via `read_terminal_output`.

2. **Windows Non-Interactive Station Subprocess DACLs:**
   - On Windows environments running non-interactive service sessions, launching subshells directly via standard `powershell.exe` without WindowStation DACL initialization can encounter `0xC0000142` (`STATUS_DLL_INITIALIZATION_FAILED`). The bridge and Playwright MCP runner mitigate this by using Win32 `CreateProcess` with inherited station contexts or running `repair_all.exe`.

3. **Multi-Model Provider Quota Variation:**
   - While `ModelExecutionAdapter` abstracts multiple LLM providers (OpenAI, Gemini, Anthropic, Custom), providers have wildly divergent TPM/RPM limits and token pricing schedules. The FinOps pricing registry (`src/finops/pricing_registry.py`) provides default estimates for standard tiers, but custom API proxies must register exact rate schedules in configuration to guarantee 100% cost precision.

4. **Production Readiness Diagnostic vs Deployment Authority:**
   - `ProductionReadinessEngine` currently operates in an advisory mode during autonomous execution. While it detects missing secrets, insecure Docker configurations, and absent rollback plans, it does not automatically provision cloud infrastructure or deploy Kubernetes clusters, as automated cloud provisioning requires separate human credential grants.

5. **Code OSS Invariant 7 Preservation:**
   - Crusor maintains strict selective manifest discipline (`desktop/selective_manifest.json`) preserving upstream Code OSS files. Only core integration files (`src/bridge/__main__.py`, `src/tools/file_tools.py`, `src/orchestration/orchestrator.py`, `src/workspace/mutation_broker.py`, `src/orchestration/models.py`) were modified in Phase 12.1, with zero modifications made to `desktop/vscode` sources.

