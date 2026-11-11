# CrusorAI - Project Master

**Document type:** durable project definition (source of truth for "what this is")
**Repository:** `SriAkhilSJ/PulseAIRepo`
**Branch:** `feat/prompt-cache-stabilization`
**Snapshot date:** 2026-11-08
**Snapshot HEAD:** `b72d04c57fd7b807df78234923e2a8b51cdce042`

> This document defines the project. It does not claim that every feature is
> complete. Status lives in `docs/CURRENT_STATE.md`; architecture lives in
> `docs/ARCHITECTURE.md`; verified phase evidence lives in
> `docs/phases/PHASE_TRACKER.md`.

---

## 1. Vision

CrusorAI IDE is a desktop AI coding environment built as a Code OSS (VS Code)
fork with a first-party autonomous coding agent named **Crusor**. The product
combines:

- a real IDE workbench (editor, files, terminal, extensions, diagnostics), and
- a Python agent runtime that can plan, edit, execute, verify, and report on
  engineering work inside the user's opened workspace.

The stated direction in the repository is "CrusorAI 2.0 Hardened Core":
production-hardened agent behaviour, measurable reliability, OS-level execution
containment, and evidence-backed completion rather than model self-certification.
See `README.md` and `core.md` for the narrative history.

## 2. Objectives

### Product objectives

1. Give the user a single right-side agent surface inside a familiar IDE.
2. Let the agent perform real work: read/write files, run commands, browse,
   verify, and build multi-platform targets.
3. Keep the user in control: explicit execution modes, approval gates,
   workspace binding, cancellation, and replayable session state.
4. Make completion honest: distinguish "the model said it is done" from
   "the runtime verified the work".

### Engineering objectives

1. Keep the desktop shell and Python engine separable over a versioned protocol.
2. Bound cost, tokens, retries, and process lifetime.
3. Contain risky execution at the OS level where the platform allows it.
4. Pin behaviour with tests and evidence, including adversarial tests.
5. Preserve upstream Code OSS integrity (the fork's "invariant 7").

## 3. Users and primary use cases

| User | Use case |
|---|---|
| Developer | Open a project in the IDE and delegate scoped coding tasks to Crusor. |
| Developer | Use Agent / Plan / Debug / Ask modes to control how much the agent executes. |
| Operator/benchmark author | Run headless agent turns through the bridge and grade evidence. |
| Maintainer | Audit security boundaries, provider cost, and regression status. |
| Builder | Ask the agent to detect, build, and verify web, desktop, mobile, or backend targets. |

The repository does not contain a verified external customer list or pricing
model. Do not infer one.

## 4. Product surface

| Area | What exists (verified paths) |
|---|---|
| Desktop IDE | `desktop/vscode/` - vendored Code OSS 1.134.0, Electron 42.8.1, branded as CrusorAI. |
| Crusor workbench contribution | `desktop/vscode/src/vs/workbench/contrib/crusorai/` - view pane, renderer, session controller, manager, preview, skills hub, account menu, inline completions, next-edit provider. |
| Agent runtime | `src/` - LangGraph graph, tools, context engine, providers, security, verification, FinOps, orchestration. |
| Desktop bridge | `src/bridge/` - newline-delimited JSON over stdio, protocol v2. |
| AG-UI / CopilotKit surface | `src/server.py` (FastAPI + `ag-ui-langgraph`), `src/agui/`, `src/a2ui_schemas/`, `.copilotkit/`. |
| Dashboard API | `src/dashboard_server.py` (Flask, local dashboard). |
| Preview proxy | `src/preview/` - local web/device preview window. |
| Multi-platform targets | `src/targets/` - Android, iOS, Flutter, React Native, Electron, Tauri, web. |
| Engineering intelligence | `src/intelligence/`, `src/orchestration/`, `src/verification/`, `src/production/`. |
| Identity / RBAC | `src/identity/` (implemented; wiring status is tracked in `docs/BUGS_AND_LIMITATIONS.md`). |
| Skills | `skills/` plus `src/agents/skill_manager.py`, `src/agents/skills_hub.py`. |
| Tests | `src/tests/` (334 `test_*.py` modules), `tests/e2e/`, target/preview/webview tests. |
| CI | `.github/workflows/` - agent-core checkup, security guard, host compatibility, diagnosability, e2e, long session, provider key. |

## 5. Requirements sources

There is no single machine-readable requirements file. Requirements are spread
across:

- `docs/requirements/PERSONAL_FINANCE_SPECIFICATION.md` (sample app specification),
- `docs/production/phase-*` (production hardening requirements and evidence),
- `docs/THE_UNIVERSAL_AGENTIC_MATRIX_100_SCENARIOS.md`,
- `docs/P2-roadmap.md`, `docs/MCP_NEXT_PLAN.md`, `docs/CRUSORAI_2_1_*.md`,
- phase documents at the repository root (`PHASE_*.md`),
- `README.md` current-behaviour section.

When a requirement matters, cite the document and the source file that
implements it. Do not treat a root-level `PHASE_*.md` file as proof by itself;
check the code and the recorded evidence.

## 6. Scope

### In scope

- Desktop IDE fork, Crusor contribution, and desktop build/packaging.
- Python agent runtime, bridge, providers, tools, context, verification.
- Security boundaries: approval, mutation broker, execution broker, OS sandbox.
- Multi-platform build/verify targets.
- Local persistence (SQLite, JSONL, workspace `.crusorai/`).
- Tests, CI, evidence documents, and this project-memory system.

### Out of scope / not claimed

- A hosted multi-tenant SaaS control plane (identity models exist, but no
  deployed service is verified here).
- Guaranteed live-provider availability; live runs depend on external keys,
  credit, and network.
- A completed GUI acceptance on a headless automation host (recorded as not
  verified).
- Any claim that uncommitted working-tree changes are part of the shipped
  product.

## 7. Definition of success

A task is only "done" when all of the following are true:

1. The change is in a known commit, not only in the working tree.
2. The relevant tests were run and their exit codes recorded.
3. The evidence document names the command, platform, result, and commit.
4. Known limitations are updated rather than hidden.
5. No unrelated dirty work was staged, reset, or overwritten.

The phase tracker applies this definition per phase.

## 8. System at a glance

```text
CrusorAI.exe (Code OSS fork, Electron)
  workbench + contrib/crusorai (TypeScript)
        |
        | stdio, newline-delimited JSON, protocol v2
        v
Python engine (src/bridge/__main__.py)
  sessions -> orchestration -> LangGraph graph -> tools -> providers
        |
        +-- workspace/.crusorai/   (submissions, finops, journals, evidence)
        +-- ~/.crusorai/           (sessions.db, traces, memories)
        +-- local preview proxy    (127.0.0.1)
```

## 9. Documentation map

| Question | Read |
|---|---|
| What is the project? | `docs/PROJECT_MASTER.md` (this file) |
| What is true right now? | `docs/CURRENT_STATE.md` |
| How is it built? | `docs/ARCHITECTURE.md` |
| Why was it built this way? | `docs/DECISIONS.md` |
| What is broken or limited? | `docs/BUGS_AND_LIMITATIONS.md` |
| What ships next? | `docs/ROADMAP.md` |
| Which phases passed? | `docs/phases/PHASE_TRACKER.md` |
| How do I continue work? | `docs/handoffs/LATEST_HANDOFF.md` and `AGENTS.md` |
| Deep historical evidence | `docs/production/`, root `PHASE_*.md`, `diagnostics/` |

## 10. Change control

- Application code is changed only under an explicit task.
- Project-memory documents are updated after every verified change.
- No document may claim a task complete without a commit SHA, a command, a
  result, and (for CI) a run or job ID.
- Documents are append-only in spirit: correct facts in place, but preserve
  historical evidence and note superseded claims explicitly.
