# CrusorAI vs. Hermes, Claude Code, Aider & Cline
## Deep Comparative Analysis & Core Upgrade Decisions

---

## 1. Executive Summary

| Agent | Architecture Style | System Message Size | Handling of Ambitious ("Startup") Prompts | Fallback to HTML/CSS Risk | Execution Gating |
|---|---|---|---|---|---|
| **CrusorAI (Before Fix)** | 3-tier prefix cache + 220 Skills | ~88KB total | Treated "Startup Ecommerce" with generic 3-8 step plan budget | **High** (Fell back to static HTML/CSS due to 12-step planner cap) | Implicit skill selection |
| **Hermes Agent** | 3-tier prefix cache (`stable` -> `context` -> `volatile`) | ~47KB code | Explicit `CODING_AGENT_GUIDANCE` + Bounded git probe | Medium (Relies on model discernment) | Live git & project facts probe |
| **Claude Code** | Tool-centric single system prompt | ~15KB prompt | Strict **Anti-Mock Mandate**; defaults to Next.js/Tailwind/FastAPI/SQLite | **Zero** (Explicit directive forbids static mockups) | Tool execution loop with compiler verification |
| **Aider** | Two-phase Architect + Coder | ~12KB prompt | Architect plans dependencies; Coder executes AST/unified diffs | **Zero** (Strict anti-placeholder, complete code rule) | Tree-sitter repo map verification |
| **Cline / Roo Code** | Explicit Mode-switched System Prompts | ~25KB prompt | Architect mode locks database, state & stack before Code mode runs | **Zero** (Mode contract forbids downgrading platforms to static HTML) | Step-by-step tool confirmation |

---

## 2. Root Cause Analysis: Why CrusorAI Fell Back to HTML/CSS

When given the prompt:
> *"Build a amazon like Ecommerce website for my startup"*

Three compounding factors caused CrusorAI to downgrade to static HTML/CSS:

1. **The Planner Step-Budget Ceiling (`src/prompts/planner_prompt.py`)**:
   - The planner prompt stated: *"Keep plans concise: usually 3-8 steps, rarely more than 12"* and *"Prefer small, safe steps over large risky ones"*.
   - A real modern full-stack e-commerce app (Next.js/React + Tailwind + SQLite/Prisma + Cart State + Product Search + Checkout) requires **14-22 distinct steps**.
   - Because the planner was instructed never to exceed 12 steps, it artificially downscaled the architecture into a single-file HTML/CSS/JS mock that fit within 4 steps.

2. **Lack of a "Project Tier Classifier" in System Message**:
   - The agent lacked an explicit classification rule for high-ambition keywords (`"startup"`, `"enterprise"`, `"production"`, `"amazon-like"`, `"platform"`).
   - Without this, the agent defaulted to the lowest complexity budget.

3. **Missing Anti-Mock / Anti-Downgrade Gate in `website-architect` Skill**:
   - The skill listed general web architecture patterns, but lacked an ironclad constraint: *"Never build a static HTML/CSS page when the user specifies a platform, startup, or e-commerce system."*

---

## 3. Core Upgrade Decisions Implemented

### Decision 1: Project Tier Classifier in Planner Prompt (`src/prompts/planner_prompt.py`)
- Added **Tier 3 (Platform / Startup Tier)** with an expanded step budget of **14-25 steps**.
- Keyword detection: when prompt contains `"startup"`, `"ecommerce"`, `"platform"`, `"saas"`, or `"amazon-like"`, Tier 3 is mandated.

### Decision 2: Hard Anti-Mock & Anti-Downgrade Mandate
- Borrowed directly from Claude Code and Cline Architect mode:
  ```markdown
  ANTI-DOWNGRADE DIRECTIVE:
  Never satisfy a platform, marketplace, or startup request with static HTML/CSS mocks.
  Default to a real fullstack stack: Next.js/React + Tailwind + SQLite/FastAPI + real state management.
  ```

### Decision 3: Skill Conformance & Guardrails
- Upgraded `website-architect` skill with Decision 0: Product Scale & Tech Stack Gating.
- Verified all 220 skills pass conformance tests (`220 clean, 0 violations`).
- Verified prompt dump parity and regression tests.

---

## 4. Location of Artifacts

All system prompts are saved as individual, fully readable markdown files:
- `PulseAIRepo/system_messages/01_crusorai_system_prompt.md`
- `PulseAIRepo/system_messages/02_hermes_agent_system_message.md`
- `PulseAIRepo/system_messages/03_claude_code_system_message.md`
- `PulseAIRepo/system_messages/04_aider_system_message.md`
- `PulseAIRepo/system_messages/05_cline_roo_code_system_message.md`
- `PulseAIRepo/system_messages/06_comparative_deep_dive_and_core_decisions.md`
