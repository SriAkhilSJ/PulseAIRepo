# 📊 Agent Performance & Diagnostics Audit
**Session ID:** `session-c632f23446f34f5baf45beca69df2e1d`  
**Generated At:** `2026-10-11 05:42:53 UTC`  

---
## 🏆 Overall Health Scorecard

| Metric | Result | Target |
| :--- | :--- | :--- |
| **Overall Health Score** | **72.1 / 100** (`C (Moderate Bottlenecks)`) | $\ge 85$ (Grade A) |
| **Total Steps & Duration** | 26 steps in 0.0s (avg 0.0s/step) | $<5.0$s / step |
| **Total Token Usage** | 131,783 input / 3,219 output | Dynamic Bounded |
| **Prompt Cache Hit Rate** | **0.0%** (0 cached) | $\ge 70\%$ |
| **Estimated Cost** | **$0.1414 USD** | $< $0.05 / task |

### Score Breakdown
- **Latency Efficiency:** `25.0 / 25`
- **Prompt Cache Stability:** `5.0 / 25`
- **Tool Correctness & Safety:** `21.7 / 25`
- **Batching & Concurrency:** `20.4 / 25`

---
## 💡 Actionable Improvement Ideas (How to Make it Better)

- ⚡ **Enable Prompt Caching:** Your prompt cache hit rate is below 60%. Ensure your system persona and tool definitions are placed at the static prefix to prevent cache-busting.
- 🔧 **Tool Error Remediation:** 2 tool calls failed. Check environment setup, missing dependencies, or file paths.

---
## 📜 Step-by-Step Execution Log

| Step | Node | Duration | Tokens (In/Out) | Cache % | Tools Executed & Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `ai` | 0.00s | 6,904 / 427 | 0% | `✅ todo_list` `✅ list_files`  |
| **2** | `tools` | 0.00s | - | - | `✅ todo_list` `✅ list_files`  |
| **3** | `ai` | 0.00s | 7,603 / 91 | 0% | `✅ scaffold_nextjs`  |
| **4** | `tools` | 0.00s | - | - | `✅ scaffold_nextjs`  |
| **5** | `ai` | 0.00s | 7,710 / 142 | 0% | `✅ terminal`  |
| **6** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **7** | `ai` | 0.00s | 7,894 / 102 | 0% | `✅ list_files` `✅ read_file`  |
| **8** | `tools` | 0.00s | - | - | `✅ list_files` `✅ read_file`  |
| **9** | `ai` | 0.00s | 8,232 / 134 | 0% | `✅ read_file` `✅ read_file`  |
| **10** | `tools` | 0.00s | - | - | `✅ read_file` `✅ read_file`  |
| **11** | `ai` | 0.00s | 8,623 / 334 | 0% | `✅ todo_list` `✅ media_search` `✅ media_search` `✅ media_search`  |
| **12** | `tools` | 0.00s | - | - | `✅ todo_list` `✅ media_search` `✅ media_search` `✅ media_search`  |
| **13** | `ai` | 0.00s | 10,041 / 149 | 0% | `✅ media_search` `✅ media_search`  |
| **14** | `tools` | 0.00s | - | - | `✅ media_search` `✅ media_search`  |
| **15** | `ai` | 0.00s | 10,693 / 139 | 0% | `✅ media_search` `✅ media_search`  |
| **16** | `tools` | 0.00s | - | - | `✅ media_search` `✅ media_search`  |
| **17** | `ai` | 0.00s | 11,964 / 828 | 0% | `✅ media_download` `✅ media_download` `✅ media_download` `✅ media_download` `✅ media_download` `✅ media_download` `✅ media_download` `✅ media_download` `✅ media_download` `✅ media_download`  |
| **18** | `tools` | 0.00s | - | - | `✅ media_download` `✅ media_download` `❌ media_download` `✅ media_download` `✅ media_download` `✅ media_download` `✅ media_download` `✅ media_download` `✅ media_download` `❌ media_download`  |
| **19** | `ai` | 0.00s | 12,750 / 65 | 0% | `✅ list_files`  |
| **20** | `tools` | 0.00s | - | - | `✅ list_files`  |
| **21** | `ai` | 0.00s | 12,769 / 150 | 0% | `✅ terminal`  |
| **22** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **23** | `ai` | 0.00s | 13,079 / 512 | 0% | `✅ terminal`  |
| **24** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **25** | `ai` | 0.00s | 13,521 / 146 | 0% | `✅ terminal`  |
| **26** | `tools` | 0.00s | - | - | `✅ terminal`  |