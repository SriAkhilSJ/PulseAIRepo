# Blueprint Lessons Learned — CrusorAI vs Best Repos

**Source files:** `docs/ref_blueprints.html` and `docs/agent_core_blueprint.html`
**Compared against:** Aider, OpenCode, Void (fetched from GitHub repos / codeload)
**Date:** 2026-11-01

---

## 1. The Bad News (one line)

CrusorAI is the **most expensive and most wasteful** of the four harnesses. Most of its token spend is thrown away.

---

## 2. Fixed Cost Per Cycle — Comparison Table

This is what every LLM call pays **before it reads a single byte of your request** (system message + tool schemas).

| Harness | System Tok | Tools | Schema Tok | Tok/Tool | Compact Levels | Repo Map | Fixed / Cycle |
|---|---|---|---|---|---|---|---|
| Aider | 1,265 | 0 | 0 | — | 1 | 1,024 | **2,289** |
| OpenCode | 333 | 19 | 2,483 | 130 | 5 | 0 | **2,816** |
| Void | 1,400 | 15 | 497 | 33 | 1 | 0 | **1,897** |
| **CrusorAI** | **6,151** | **36** | **7,509** | **208** | **1** | **0** | **13,660** |

**CrusorAI's tool schemas alone (7,509 tok) exceed every competitor's entire fixed cost.**

- vs Aider: 13,660 / 2,289 ≈ **6× higher**
- vs OpenCode: 13,660 / 2,816 ≈ **4.8× higher**
- vs Void: 13,660 / 1,897 ≈ **7.2× higher**

---

## 3. CrusorAI's Own Runs — Where the Money Went

From `agent_core_blueprint.html` (measured from live run `41290247998`):

| Metric | Value |
|---|---|
| Prompts | 5 |
| Cycles | 104 |
| Tokens | 2,967,652 |
| Cost | $0.45 |
| Completed work | 472,716 tok (16%) |
| Discarded by cycle-cuts | 2,494,936 tok (84%) |
| Fixed overhead per cycle | 7,939 tok (27%) |
| Tokens per cycle (mean) | 28,805 |
| Cost per cycle | ~$0.0044 |
| Session wall clock inside model | 98.9% |
| Tools sent / defined | 36 / 68 |

**Cycle count explodes:** prompt 1 = 4 cycles, prompt 3 = 33 cycles, prompt 4 = 26, prompt 5 = 27.

---

## 4. Why CrusorAI Was Built This Way (Code Investigation)

### 4.1 Rich system persona — `src/prompts/claude_persona.py`
`CLAUDE_SYSTEM_PERSONA` is ~24,606 chars / 6,151 tokens. It was **consciously written** to make the agent "sound like a skilled colleague" — communication style, workflow (understand → think → act → verify → launch preview → report), every tool with long descriptions, safety rules, formatting rules, self-correction.

The `D35` section **deliberately added** more blocks: batch tool calling, finish-the-job discipline, grounding rules, large-write discipline, programmatic tool calling (PTC). These were copied/adapted from Hermes patterns.

The desktop default (6,151 tok) is re-sent on **every one of 104 cycles** = 639,704 tok ≈ $0.098/session just for the system message. The autonomous version is only 430 tok, but the harness ran with `approval_policy=workspace_session`, understating desktop cost by 14×.

### 4.2 Huge tool waist — `src/tools/toolsets.py`
`resolve_runtime_tool_names()` binds an "always-on waist": core + skill + MCP + workspace read/write + execution + verification + research/media + browser + UI scaffold + target/mobile device + delegation tools. Comment says *"Paid on every turn. Keep this truly universal and action-neutral"* — but it binds **everything** for a "broad Scope IDE agent."

### 4.3 Task-scoped posture — `src/agents/runtime_profile.py`
Classifies tasks into many capabilities (workspace_read, workspace_write, execution, verification, research, browser, delegation, mobile_app, desktop_app). Coding tasks get 5+ capabilities bound at once, pulling in more tool schemas every cycle.

### 4.4 Loop control — 20 iterations, cost budget OFF
From blueprint: *"iterations 20/20 imposed (production 45) cost leg OFF by default."* The only thing stopping the loop was the iteration cap. `src/bridge/turn_watchdog.py` measures silence (600s default), not cost.

### 4.5 Compaction rewrites instead of masking — `src/context/compaction.py`
`HistoryCompactor` prunes tool outputs with placeholders, drops old turns, and generates an LLM summary. But it **rewrites the prefix**, so the next cycle re-prefills the whole prompt at full price. Cache hit rate decays 53% → 46% → 39%.

### 4.6 Blind retry on tool failure
`read_terminal_output` failed on **all 7 prompts**, and the model was told "Tool failed: read_terminal_output" — no cause, so it retried. 30 results/prompt × ~3,000 tok ≈ 90,000 tokens per prompt wasted.

---

## 5. Consequences If You Copy CrusorAI's Design

| What you copy | Consequence |
|---|---|
| 13,660 fixed tokens/cycle | Every LLM call pays ~5–7× more than competitors before reading your request |
| 6,151-token persona re-sent every cycle | ~$0.098/session just for the system message on desktop |
| 7,509-token tool schemas re-sent every cycle | ~780,936 tokens over 104 cycles (~26% of every cycle) |
| Cost budget OFF + iteration cap at 20 | Prompts die mid-task at `iterations 20/20` after passing verification |
| Compaction rewrites prefix (not masks) | Cache hit rate decays 53% → 39%; every cycle re-prefills full price |
| Blind retry on failed tools | Model retries with no cause, wasting tokens per attempt |
| 68 tools bound, 36–48 sent per cycle | Up to ~90,000 tokens per prompt in tool result echoes |

**The "one cable" problem:** It's a series of cables. One misconfigured cable (cost budget OFF + iteration cap too small + rich persona re-sent every cycle) causes cascading failure: **84% of tokens discarded, $0.45 for 5 prompts, only 16% actual work.**

If you copy CrusorAI's design, you inherit the same waste.

---

## 6. Fix Order — By Money Recovered (from the blueprint)

| # | Fix | Recovers | Pipeline |
|---|---|---|---|
| 1 | Give the agent its own budget (45) and make `AGENT_COST_BUDGET` the binding leg | the 84% currently thrown away | 8 loop control |
| 2 | Mask instead of rewrite on compaction (OpenHands condenser) | cache hit 39% → 80%+; ~17% of every prompt | 4 context |
| 3 | Trim the tool preamble: 36–48 schemas = 7,509 tok/cycle | ~26% of every cycle, ×104 | 5 model call |
| 4 | Cap tool results in tokens, not 12,000 chars | up to ~90k tokens per prompt | 7 tools |
| 5 | One stuck detector instead of three guards | runaway cycles | 8 loop control |

---

## 7. What the Best Repos Do Differently

| | Aider | OpenCode | Void | CrusorAI (what not to copy) |
|---|---|---|---|---|
| System message | 1,265 tok | 333 tok | 1,400 tok | 6,151 tok |
| Tool schemas | 0 tok | 2,483 tok | 497 tok | 7,509 tok |
| Fixed / cycle | 2,289 tok | 2,816 tok | 1,897 tok | 13,660 tok |
| Repo map | tree-sitter + PageRank | LSP + file reads | file tree in system msg | none (describes in words) |
| Compaction | masks old observations in place | clip 2,000 chars per end | edits applied in-editor | rewrites prefix |
| Tools sent | ZERO (text edit formats) | 19 | 15 | 36–48 |

**Key lesson:** The lever is the encoding of tool definitions (208 tok/tool for CrusorAI vs 33 for Void's XML prose) and the prompt contract (6,151 vs 189–1,265), not the model.

---

## 8. Files to Check Before Changing Anything

- `docs/ref_blueprints.html` — competitor comparison
- `docs/agent_core_blueprint.html` — CrusorAI's own measured waste
- `src/prompts/claude_persona.py` — the 6,151-token persona
- `src/tools/toolsets.py` — the always-on tool waist (36 tools)
- `src/agents/runtime_profile.py` — capability classification
- `src/context/compaction.py` — compaction that rewrites prefix
- `src/bridge/turn_watchdog.py` — silence-based watchdog (600s), not cost
- `src/config/settings.py` — `PROVIDER_SAFE_LIMIT`, `LLM_MODEL`, `LLM_PROVIDER`
- `src/context/model_budgets.py` — context window resolution (256K default fallback)
- `src/context/token_budget.py` — token counting and trimming

---

**Remember:** Before fixing, check why it was implemented this way. One cable is not set up correctly — it's bad news. Fix the cable, don't copy the broken design.
