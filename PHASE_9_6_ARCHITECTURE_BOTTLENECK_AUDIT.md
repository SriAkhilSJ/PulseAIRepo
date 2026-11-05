# CRUSOR AI IDE — PHASE 9.6: ARCHITECTURE & BOTTLENECK AUDIT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.5  
**Execution Platform:** Windows 10/11 x64  
**Verdict:** `DESKTOP PERFORMANCE AND OBSERVABILITY VERIFIED`  

---

## 1. COMPONENT-BY-COMPONENT ARCHITECTURAL ANALYSIS

### A. Electron Main Process
The Main process orchestrates native application lifecycle, menu bars, window creation, and utility process spawning.
- **Bottleneck Identified:** Early initialization executed synchronous disk lookups for previous session records before rendering the initial window frame.
- **Remediation:** Defer disk I/O until the renderer dispatches `workbenchReady`.

### B. Renderer Process & VS Code Workbench
The renderer hosts VS Code's DOM and custom Crusor UI panels (Chat, Inline Diff, Model Switcher).
- **Bottleneck Identified:** High token output rates (e.g. 80 tokens/sec) triggered excessive per-token React/DOM reconciliation passes, causing perceptible typing lag.
- **Remediation:** Token stream buffering: chunk delivery into 30ms render batches.

### C. Node Utility Process Worker
`crusorAIWorkerProcessService.ts` runs inside an isolated Node utility process, brokering IPC frames between the workbench renderer and Python sidecar.
- **Bottleneck Identified:** If the Python sidecar briefly pauses (e.g. garbage collection or heavy AST parsing), the utility process queued outbound messages without backpressure, risking memory inflation.
- **Remediation:** Bounded queue depth (max 1,000 messages) with backpressure shedding and error feedback (`BridgeBackpressureError`).

### D. Python Sidecar (`src.bridge`)
The Python sidecar runs the LangGraph agent state machine.
- **Bottleneck Identified:** Unconstrained mathematical libraries (NumPy, SciPy) spawned background threads across all available CPU cores, starving the Node UI thread.
- **Remediation:** Enforce thread clamping at process bootstrap: `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `OMP_NUM_THREADS=1`.

---

## 2. CROSS-PROCESS COMMUNICATION FLOW

```
[ Workbench Renderer ]
        |
        |  1. VS Code Native IPC (Fast Channel)
        v
[ Node Utility Process ]
        |
        |  2. stdio Pipes (JSONL Protocol v2)
        |     - Bounded Queue: 1,000 frames
        |     - Max Frame Size: 1 MB
        |     - Correlation: request_id & correlation_id
        v
[ Python Sidecar (src.bridge) ]
        |
        |  3. In-Process Function Dispatch
        v
[ Agent Core / LangGraph Runtime ]
        |
        +-----> [ Context Engine ] (LRU In-Memory Cache)
        +-----> [ MCP Gateway ] (Job Object Isolation)
        +-----> [ Browser Agent ] (Chromium Sandbox)
```
