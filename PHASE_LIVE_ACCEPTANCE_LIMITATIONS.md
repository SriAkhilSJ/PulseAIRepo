# PHASE LIVE ACCEPTANCE LIMITATIONS
## Final Live Product Acceptance — Technical Nuances & Environmental Disclosures

### 1. Headless Virtual Machine vs Interactive Physical Display
- The test harness operated within a Windows Server headless/virtualized automation session without a physical monitor attached.
- Electron's main process runs in headless Node ESM mode; standard Chromium GPU rendering acceleration is automatically disabled in this topology.
- All DOM and protocol automation is driven over Chrome DevTools Protocol (CDP) via HTTP/WebSocket loopback.

### 2. Commercial Provider Latency Variances
- While Velona flash models (`qwen/qwen3.7-flash`, `deepseek/deepseek-v4.1-flash`) responded in 1.5–1.8 seconds on simple probes, comprehensive task code authoring on `z-ai/glm-5.3-flash` required ~115 seconds to stream all 3,132 output tokens (12.5 KB of code).
- Future production tuning may recommend streaming token chunk callbacks directly to the UI progress bar to enhance perceived responsiveness.

### 3. Windows Native AppContainer Boundaries
- Windows AppContainer isolation is enforced on terminal execution tools. In environments lacking appropriate Security Identifier (SID) creation rights, fallback to bounded subprocess job objects is applied transparently.
