---
name: subagent-driven-development
description: "Execute plans via delegate_to_subagent subagents (2-stage review)."
version: 1.2.0
author: Hermes Agent (adapted from obra/superpowers), ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [delegation, subagent, implementation, workflow, parallel]
    related_skills: [requesting-code-review, test-driven-development]
---

**Triggers:** subagent, sub-agent, delegate, parallel agents, spawn agents, batch agents, delegate_to_subagent, fan out

# Subagent-Driven Development

## Overview

Execute an implementation plan by dispatching a fresh Crusor subagent per task with systematic two-stage review.

**Core principle:** fresh subagent per task + two-stage review (spec, then quality) = high quality, fast iteration. Crusor already ships `delegate_to_subagent` (single) and `delegate_to_subagent_batch` (parallel) — this skill is about driving them well.

## When to Use

- You have an implementation plan (Plan mode output or user requirements)
- Tasks are mostly independent
- Quality and spec compliance matter

**vs. manual execution:** fresh context per task (no confusion from accumulated state), automated review catches issues early, consistent quality checks. Child runs are isolated (`parentMap`), depth-guarded by `CRUSORAI_SUBAGENT_DEPTH`, and surface as clickable `taskToolCard`s — tell the user they can click through to each child.

## The Process

### 1. Read and Parse the Plan ONCE

Extract ALL tasks with their full text and context upfront. **Do not make subagents read the plan file — paste the full task text into each subagent's context.**

### 2. Per-Task Workflow

#### Step 1 — dispatch the implementer

Use `delegate_to_subagent` with complete, self-sufficient context:

```python
delegate_to_subagent(
    goal="Implement Task 1: Create User model with email and password_hash fields",
    context="""
    TASK FROM PLAN:
    - Create: src/models/user.py
    - User class with email (str) and password_hash (str); bcrypt hashing

    FOLLOW TDD (test-driven-development skill):
    1. Write failing test in tests/models/test_user.py
    2. Run: pytest tests/models/test_user.py -v   (verify FAIL)
    3. Minimal implementation
    4. Run: pytest tests/models/test_user.py -v   (verify PASS)
    5. Run: pytest tests/ -q                      (no regressions)

    PROJECT CONTEXT: Python 3.12, app in src/, pytest from project root.
    """,
)
```

#### Step 2 — spec-compliance reviewer

After the implementer completes, dispatch a fresh subagent that checks ONLY against the original spec:

```text
CHECK: all spec requirements implemented? file paths/signatures match?
behavior matches? nothing extra added (no scope creep)?
OUTPUT: PASS, or a list of specific spec gaps to fix.
```

If gaps: fix, then re-run the spec review. Continue only when spec-compliant.

#### Step 3 — code-quality reviewer

```text
CHECK: project conventions? error handling? clear names? test coverage?
obvious bugs/edge cases? security issues?
OUTPUT: Critical / Important / Minor issues + verdict APPROVED or REQUEST_CHANGES.
```

If issues: fix, re-review. Continue only when approved.

#### Step 4 — mark the task complete and move to the next

### 3. Parallelize Independent Tasks

Independent tasks (different files, no interface coupling) go through `delegate_to_subagent_batch` in ONE call. Dependencies stay serial: never dispatch a task whose inputs another subagent is still producing.

### 4. Final Integration Review

After ALL tasks complete, dispatch one final reviewer: do the components work together? inconsistencies between tasks? all tests passing? ready for hand-off?

## Invariants

- Fresh subagent per task and per review — never ask the implementer to review itself.
- Reviews read files only; fixes go back through an implementer dispatch.
- Never commit without the user's approval flow (Crusor mutation gates).
- If a subagent fails twice on the same task, stop and escalate to the user instead of retrying blindly.
