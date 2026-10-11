# 📊 Agent Performance & Diagnostics Audit
**Session ID:** `session-20b8c03d8889461b977700b540141818`  
**Generated At:** `2026-10-11 10:25:25 UTC`  

---
## 🏆 Overall Health Scorecard

| Metric | Result | Target |
| :--- | :--- | :--- |
| **Overall Health Score** | **64.4 / 100** (`D (Needs Optimization)`) | $\ge 85$ (Grade A) |
| **Total Steps & Duration** | 86 steps in 0.0s (avg 0.0s/step) | $<5.0$s / step |
| **Total Token Usage** | 425,621 input / 6,061 output | Dynamic Bounded |
| **Prompt Cache Hit Rate** | **0.0%** (0 cached) | $\ge 70\%$ |
| **Estimated Cost** | **$0.4438 USD** | $< $0.05 / task |

### Score Breakdown
- **Latency Efficiency:** `25.0 / 25`
- **Prompt Cache Stability:** `5.0 / 25`
- **Tool Correctness & Safety:** `18.5 / 25`
- **Batching & Concurrency:** `15.9 / 25`

---
## 💡 Actionable Improvement Ideas (How to Make it Better)

- ⚡ **Enable Prompt Caching:** Your prompt cache hit rate is below 60%. Ensure your system persona and tool definitions are placed at the static prefix to prevent cache-busting.
- 🔧 **Tool Error Remediation:** 6 tool calls failed. Check environment setup, missing dependencies, or file paths.
- 📦 **Encourage Parallel Tool Calling & PTC:** The model is emitting tools serially. Add prompt examples demonstrating multi-file writes in a single assistant turn.

---
## 📜 Step-by-Step Execution Log

| Step | Node | Duration | Tokens (In/Out) | Cache % | Tools Executed & Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `ai` | 0.00s | 4,773 / 121 | 0% | `✅ generate_image`  |
| **2** | `tools` | 0.00s | - | - | `✅ generate_image`  |
| **3** | `ai` | 0.00s | 4,925 / 85 | 0% | `✅ terminal`  |
| **4** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **5** | `ai` | 0.00s | 5,081 / 134 | 0% | `✅ terminal`  |
| **6** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **7** | `ai` | 0.00s | 5,368 / 153 | 0% | `✅ generate_image`  |
| **8** | `tools` | 0.00s | - | - | `✅ generate_image`  |
| **9** | `ai` | 0.00s | 5,535 / 486 | 0% | `✅ write_file` `✅ write_file`  |
| **10** | `tools` | 0.00s | - | - | `✅ write_file` `❌ write_file`  |
| **11** | `ai` | 0.00s | 5,736 / 66 | 0% | `✅ terminal`  |
| **12** | `tools` | 0.00s | - | - | `❌ terminal`  |
| **13** | `ai` | 0.00s | 5,896 / 88 | 0% | `✅ terminal`  |
| **14** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **15** | `ai` | 0.00s | 6,186 / 230 | 0% | `✅ terminal`  |
| **16** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **17** | `ai` | 0.00s | 6,857 / 172 | 0% | `✅ generate_image`  |
| **18** | `tools` | 0.00s | - | - | `✅ generate_image`  |
| **19** | `ai` | 0.00s | 7,034 / 85 | 0% | `✅ terminal`  |
| **20** | `tools` | 0.00s | - | - | `❌ terminal`  |
| **21** | `ai` | 0.00s | 7,248 / 105 | 0% | `✅ media_search`  |
| **22** | `tools` | 0.00s | - | - | `✅ media_search`  |
| **23** | `ai` | 0.00s | 7,355 / 54 | 0% | `✅ media_search`  |
| **24** | `tools` | 0.00s | - | - | `✅ media_search`  |
| **25** | `ai` | 0.00s | 7,899 / 76 | 0% | `✅ media_download`  |
| **26** | `tools` | 0.00s | - | - | `✅ media_download`  |
| **27** | `ai` | 0.00s | 7,975 / 133 | 0% | `✅ terminal`  |
| **28** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **29** | `ai` | 0.00s | 8,011 / 226 | 0% | `✅ terminal`  |
| **30** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **31** | `ai` | 0.00s | 8,076 / 96 | 0% | `✅ terminal`  |
| **32** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **33** | `ai` | 0.00s | 8,114 / 263 | 0% | `✅ terminal`  |
| **34** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **35** | `ai` | 0.00s | 8,756 / 275 | 0% | `✅ terminal`  |
| **36** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **37** | `ai` | 0.00s | 9,034 / 87 | 0% | `✅ terminal`  |
| **38** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **39** | `ai` | 0.00s | 9,105 / 105 | 0% | `✅ display_crusor_task`  |
| **40** | `tools` | 0.00s | - | - | `✅ display_crusor_task`  |
| **41** | `ai` | 0.00s | 9,590 / 204 | 0% | *None* |
| **42** | `ai` | 0.00s | 10,068 / 435 | 0% | `✅ skill_manage`  |
| **43** | `tools` | 0.00s | - | - | `✅ skill_manage`  |
| **44** | `ai` | 0.00s | 10,481 / 181 | 0% | *None* |
| **45** | `ai` | 0.00s | 10,669 / 222 | 0% | `✅ todo_list` `✅ typecheck_workspace`  |
| **46** | `tools` | 0.00s | - | - | `✅ todo_list` `✅ typecheck_workspace`  |
| **47** | `ai` | 0.00s | 10,980 / 97 | 0% | `✅ read_file`  |
| **48** | `tools` | 0.00s | - | - | `✅ read_file`  |
| **49** | `ai` | 0.00s | 10,903 / 97 | 0% | `✅ terminal`  |
| **50** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **51** | `ai` | 0.00s | 10,944 / 173 | 0% | `✅ search_files` `✅ list_files`  |
| **52** | `tools` | 0.00s | - | - | `✅ search_files` `✅ list_files`  |
| **53** | `ai` | 0.00s | 11,248 / 94 | 0% | `✅ list_files` `✅ list_files`  |
| **54** | `tools` | 0.00s | - | - | `✅ list_files` `✅ list_files`  |
| **55** | `ai` | 0.00s | 11,279 / 48 | 0% | `✅ read_file`  |
| **56** | `tools` | 0.00s | - | - | `✅ read_file`  |
| **57** | `ai` | 0.00s | 11,466 / 87 | 0% | `✅ terminal`  |
| **58** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **59** | `ai` | 0.00s | 11,726 / 52 | 0% | `✅ search_code`  |
| **60** | `tools` | 0.00s | - | - | `✅ search_code`  |
| **61** | `ai` | 0.00s | 11,927 / 43 | 0% | `✅ read_file`  |
| **62** | `tools` | 0.00s | - | - | `❌ read_file`  |
| **63** | `ai` | 0.00s | 11,986 / 88 | 0% | `✅ terminal`  |
| **64** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **65** | `ai` | 0.00s | 12,093 / 50 | 0% | `✅ read_file`  |
| **66** | `tools` | 0.00s | - | - | `✅ read_file`  |
| **67** | `ai` | 0.00s | 12,296 / 120 | 0% | `✅ terminal`  |
| **68** | `tools` | 0.00s | - | - | `❌ terminal`  |
| **69** | `ai` | 0.00s | 12,446 / 130 | 0% | `✅ terminal`  |
| **70** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **71** | `ai` | 0.00s | 12,681 / 100 | 0% | `✅ terminal`  |
| **72** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **73** | `ai` | 0.00s | 12,848 / 47 | 0% | `✅ read_file`  |
| **74** | `tools` | 0.00s | - | - | `✅ read_file`  |
| **75** | `ai` | 0.00s | 13,049 / 156 | 0% | `✅ terminal`  |
| **76** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **77** | `ai` | 0.00s | 13,267 / 56 | 0% | `✅ search_code`  |
| **78** | `tools` | 0.00s | - | - | `✅ search_code`  |
| **79** | `ai` | 0.00s | 13,295 / 172 | 0% | `✅ terminal`  |
| **80** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **81** | `ai` | 0.00s | 13,595 / 117 | 0% | `✅ terminal`  |
| **82** | `tools` | 0.00s | - | - | `❌ terminal`  |
| **83** | `ai` | 0.00s | 13,775 / 127 | 0% | `✅ terminal`  |
| **84** | `tools` | 0.00s | - | - | `✅ terminal`  |
| **85** | `ai` | 0.00s | 14,045 / 125 | 0% | `✅ terminal`  |
| **86** | `tools` | 0.00s | - | - | `✅ terminal`  |