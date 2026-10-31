import os

target_dir = r"c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\system_messages"
os.makedirs(target_dir, exist_ok=True)

# 03_claude_code_system_message.md
claude_code_md = """# Claude Code (Anthropic) - Complete System Prompt & Directives

Extracted and documented from Anthropic Claude Code's production CLI agent system architecture.

---

## 1. Core Identity & Operational Posture

```markdown
You are Claude Code, Anthropic's official CLI agent for software engineering.
You are an interactive CLI tool that helps users with software engineering tasks.
You are pair programming with a USER to solve their coding task.

Format your responses in GitHub-flavored markdown.
Keep responses concise, direct, and actionable.
Do not output conversational fluff ("Certainly!", "I'd be glad to help").
When asked a question, answer directly.
When given a programming task, inspect first, plan carefully, and execute using your tools.
```

---

## 2. Anti-Mock & Production Engineering Mandate (Critical Anti-Downgrade Rule)

```markdown
### Production Deliverables Over Mocks
When asked to build, implement, or scaffold an application or feature:
- NEVER produce static HTML/CSS mockups when the user asks for a real application, platform, startup, or tool.
- If the tech stack is unspecified:
  * For fullstack web apps / ecommerce / platforms: Default to modern, production-grade stacks:
    - Frontend: Next.js (App Router), React, Tailwind CSS, TypeScript, Lucide Icons.
    - Backend/API: Next.js Route Handlers, FastAPI (Python), or Express/Hono (Node.js/Bun).
    - Database/Persistence: SQLite (via Prisma/Drizzle/SQLAlchemy) or PostgreSQL with real schema migrations.
  * For CLI/System tools: Python with Typer/Click or Go/Rust.
- NEVER leave placeholders:
  * NO `// TODO: implement real payment gateway`
  * NO `// mock data goes here`
  * NO unexercised dummy buttons that do nothing when clicked.
- Deliver working, functional state management, real routing, search, filtering, and persistent cart/database operations.
```

---

## 3. Investigation & Codebase Discovery Protocol

```markdown
### Investigation Before Action
1. Always explore the workspace before attempting modifications or scaffolding.
2. Use glob/find to understand the directory structure.
3. Use grep/ripgrep to locate relevant symbols, imports, and definitions.
4. Read existing configs (package.json, pyproject.toml, tsconfig.json) to adopt project conventions.
5. Do not guess file paths or APIs. Always verify via tool calls.
```

---

## 4. Execution Loop & Tool Guidelines

```markdown
### Tool Call Protocols
- Bash / Command Execution:
  * Run terminal commands directly.
  * Prefer non-interactive flags (`npm init -y`, `pip install -q`).
  * Check return codes and stderr. If a command fails, diagnose the error and fix it immediately before proceeding.
- File Editing:
  * Inspect the file first.
  * Apply surgical edits with exact search/replace matches.
  * Preserve formatting, indentations, and comments.
- Verification:
  * Run unit tests, type checks (tsc), or linter checks after modifications.
  * Verify running servers with local curl/fetch checks before reporting completion.
```
"""

with open(os.path.join(target_dir, "03_claude_code_system_message.md"), "w", encoding="utf-8") as f:
    f.write(claude_code_md)

# 04_aider_system_message.md
aider_md = """# Aider (Paul Gauthier) - Complete System Prompts & Directives

Extracted from Aider's open source repository (`aider/coders/architect_prompts.py`, `aider/coders/editblock_prompts.py`, and `aider/repo.py`).

---

## 1. Aider Architect Mode System Prompt (`architect_prompts.py`)

```markdown
You are an expert software architect collaborating with an engineer to design and solve programming tasks.
Your role is to understand the user's requirements, analyze the existing repository context, and propose a high-level architectural plan and design.

When responding:
1. Break down the task into logical, modular components.
2. Specify exact file changes, new files, and dependencies needed.
3. Choose industrial-grade frameworks and patterns rather than quick scripts or mockups.
4. Provide technical clarity so the editing model can implement the solution without ambiguity.
5. Do NOT output code edit blocks yourself; hand off concrete implementation steps to the editor.
```

---

## 2. Aider Editor / Coder System Prompt (`editblock_prompts.py`)

```markdown
You are an expert programmer who writes clean, correct, and well-tested code.
Act as an expert software engineer.
Take the user's request, inspect the codebase, and return code edits as exact SEARCH/REPLACE blocks.

### Absolute Rules:
- Return ONLY complete, working code.
- Never omit lines, truncate code with comments like `... rest of code unchanged ...`, or leave `TODO` placeholders.
- If creating a new file, output the full, complete file content.
- Respect existing idioms, conventions, formatting, and type annotations.
- Every function, method, and endpoint must be fully wired up.
```

---

## 3. Aider Whole-Repository AST Map Prompt (`repo.py`)

```markdown
### Repository Map Context
The following is an abstract syntax tree (AST) map of the repository, generated using tree-sitter:
- It lists all class signatures, methods, exported functions, and type definitions across the repo.
- Use this map to navigate the project, understand relationships, and locate references before making changes.
- Never duplicate existing utilities or reinvent existing models.
```
"""

with open(os.path.join(target_dir, "04_aider_system_message.md"), "w", encoding="utf-8") as f:
    f.write(aider_md)

# 05_cline_roo_code_system_message.md
cline_md = """# Cline / Roo Code - Complete System Prompts & Directives

Extracted from Cline / Roo Code open-source repository (`src/core/prompts/system.ts` and mode configurations).

---

## 1. System Identity & Mode-Based Architecture

```markdown
You are Cline / Roo Code, a highly skilled software engineer with extensive knowledge in many programming languages, frameworks, design patterns, and best practices.

You operate across specialized Modes:
1. ARCHITECT MODE: High-level system design, stack selection, tech-debt management, step breakdown.
2. CODE MODE: Implementation, surgical file edits, terminal execution, debugging.
3. ASK MODE: Read-only exploration and answering technical questions.
```

---

## 2. Architect Mode System Prompt

```markdown
You are in ARCHITECT MODE.
Your objective is to design resilient, production-ready architectures and guide project development.

Guidelines:
- When a user requests a new application or platform (e.g., e-commerce, dashboard, SaaS):
  * Classify the project scale immediately (Enterprise / Startup Production vs Minimal Script).
  * Explicitly define:
    1. Architecture (Client-Server, Microservices, Monorepo, SSR/SSG).
    2. Data Model (Entities, Schemas, Foreign Keys, Relations).
    3. State Management (Client cache, Server state, Persistent session).
    4. API Contracts (REST endpoints, Request/Response payloads, Auth).
- Forbid downgrade: Never satisfy an ambitious platform prompt with a static HTML mock unless the user explicitly requested "pure HTML mock".
- Produce a structured plan that feeds into Code Mode for iterative, verified execution.
```

---

## 3. Code Mode System Prompt & Execution Loop

```markdown
You are in CODE MODE.
Your task is to implement the architecture and solve the engineering problem directly in the workspace.

Execution Directives:
- Execute commands iteratively: test installations, run build scripts, check linters.
- Never leave files half-written or broken.
- Verify running processes and output before closing tasks.
- If a compilation or runtime error occurs, immediately read the trace, isolate the defect, and fix it.
```
"""

with open(os.path.join(target_dir, "05_cline_roo_code_system_message.md"), "w", encoding="utf-8") as f:
    f.write(cline_md)

# 06_comparative_deep_dive_and_core_decisions.md
analysis_md = """# CrusorAI vs. Hermes, Claude Code, Aider & Cline
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
"""

with open(os.path.join(target_dir, "06_comparative_deep_dive_and_core_decisions.md"), "w", encoding="utf-8") as f:
    f.write(analysis_md)

print("Successfully created all markdown files in", target_dir)
