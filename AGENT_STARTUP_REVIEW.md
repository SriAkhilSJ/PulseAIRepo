# PulseAI Agent — Startup-Focused Technical Review

**Review date:** 2026-08-13  
**Scope:** Agent backend and supporting dashboard API. The VS Code/Desktop fork was intentionally excluded.

## Executive verdict

PulseAI is an **ambitious and technically credible agent-runtime prototype**, not yet a production startup product.

- **Agent/runtime engineering:** 7.5/10
- **Automated correctness evidence:** 7/10
- **Maintainability:** 5/10
- **Security / multi-user production readiness:** 2.5/10
- **Overall startup beta readiness:** 5.5/10

The backend is substantially stronger than typical “LLM + tools” demos. It has a real LangGraph state machine, bounded recovery, verification gates, context retrieval, checkpointing, tool-call repair, session persistence, parallel execution controls, and a large regression suite. However, its product shell overclaims readiness: dashboard authentication and tenant isolation are absent, approval and rollback APIs are incomplete, seven tests currently fail on Linux, and the central graph/context modules are too large to change safely at startup speed.

**Recommendation:** Keep the agent engine, freeze new features, and spend the next milestone on convergence: one supported platform, one dependable model/provider configuration, a green test suite, real end-to-end benchmarks, secure local-only/dashboard operation, and simplification of the graph.

## What was inspected

- `src/graphs/` — core LangGraph workflow, progress, gates, parallel tools, state and budgets
- `src/context/` — context assembly, chunk retrieval, memory, caching, compaction and safety
- `src/tools/` — file, terminal, web, browser and programmatic tool calling
- `src/agents/` — planner, cost router, skills and sub-agents
- `src/llm/` and `src/providers/` — provider construction, retries and request sanitation
- `src/dashboard_server.py` and `src/dashboard/`
- Tests, project configuration, README, lab reports and architecture audits

## Measured result

The README command is Windows-specific (`D:\pytest-tmp`, PowerShell, and `.venv\Scripts\python.exe`). In this Linux review environment I ran its behaviorally equivalent command: the same test directory, the same `--no-header`, the exact `--ignore=src/tests/test_session_engines.py`, and a pytest temp directory outside the git repository.

```bash
mkdir -p /home/user/pytest-tmp
uv run python -m pytest src/tests -q --no-header \
  --ignore=src/tests/test_session_engines.py \
  --basetemp=/home/user/pytest-tmp
```

Initial result on Linux / Python 3.14 was 558 passed / 7 failed. The review fixes then addressed all seven issues: tree-sitter now provides a declared-dependency TS/TSX syntax fallback, path/timeout regressions are platform-neutral, and fixed tool-count assertions were replaced with capability invariants.

Current result using the README-equivalent selection:

- **569 tests collected**
- **589 passed**
- **1 dependency deprecation warning**
- Runtime: about **1m 51s**

The README count has been updated accordingly.

## What is genuinely strong

### 1. The agent is a real state machine

`src/graphs/chat_graph.py` is not a toy loop. It implements task management, planning, plan approval/revision, tool execution, progress tracking, replanning, recovery limits, environment pivots, finish gates and persistent checkpoints.

### 2. Good correctness and durability mechanisms

Notable engineering includes:

- Finish gates that distinguish real deliverables from shell activity
- Verification/evidence tracking before declaring execution work complete
- Tool-call ID repair and request sanitation
- Provider failover and retry logic
- Per-session context-engine registry
- SQLite LangGraph checkpoint persistence
- Shadow checkpoints before workspace mutation
- Concurrent-tool conflict detection and deterministic sequential fallback
- Stale-write protection for concurrent agents
- Bounded sub-agent depth and batch size
- Output, iteration and retry budgets

These are valuable foundations for a coding agent startup.

### 3. Context and retrieval are above average

The repository includes AST/tree-sitter extraction, repo maps, chunk indexing, BM25/vector fusion, semantic deduplication, context budgets, compaction and persistent memory. This is more credible than simply loading entire files into every prompt.

### 4. The project is unusually honest about failures

The lab reports and CTO audit document failed runs and root causes instead of showing only curated demos. That is a positive engineering culture signal.

## Main risks

### P0 — Dashboard is unsafe outside a trusted local machine

`src/dashboard_server.py`:

- binds to `0.0.0.0`;
- enables unrestricted `CORS(app)`;
- has no authentication or authorization;
- accepts requests that can ultimately cause file changes and shell commands.

Anyone who can reach the port can potentially operate the agent against its workspace. Do not call this “Production Streaming” or deploy it on a shared/network-accessible host in the current form.

### P0 — Session/event isolation is incomplete

`EventBus` broadcasts every event and replays global history to every SSE subscriber. It does not filter subscriptions by `thread_id`. This can leak prompts, tool arguments, diffs and analytics between users/sessions.

Global `cost_router`, skill state and some analytics counters also make multi-user metrics unreliable.

### P0 — Claimed dashboard approval flow is not actually wired end-to-end

The dashboard has `/api/approve` and an `ApprovalQueue`, but `SafeToolNode` does not request or wait on that queue. The `auto_approve` branch in `/api/chat` is a `pass`. Interactive unsafe operations return an AI text message rather than a durable pending approval that can resume the exact tool call.

This is a product correctness gap because README claims manual approve/deny behavior.

### P0 — Rollback and diff review APIs overstate behavior

`/api/rollback` emits a status event but does not reset a LangGraph checkpoint or restore files. The code itself says this would be done “in production.” The “shadow git” diff endpoints store decisions in memory but do not apply accepted chunks to the filesystem.

These should be either fully implemented or clearly labeled UI prototypes.

### P1 — Central modules are too large

- `src/graphs/chat_graph.py`: about **2,620 lines**
- `src/context/context_engine.py`: about **1,647 lines**

`chat_graph.py` also contains duplicate definitions of `_zero_token_usage` and `_merge_token_usage`, which is a concrete sign of merge/patch accumulation. The project has extracted some modules, but the core remains a god-file with import-time graph, memory and SQLite initialization.

This raises regression risk and makes onboarding difficult.

### P1 — Verification is partly fail-open

The TypeScript syntax receipt returns success when Node/esbuild is unavailable. That may be acceptable as graceful degradation, but it must not then be presented as a guaranteed syntax gate. Either vendor/declare the parser dependency or mark the operation unverified when the parser is missing.

`typecheck_workspace` also reports a skip when TypeScript is unavailable. The finish gate must distinguish “passed” from “could not run.”

### P1 — Live quality remains model-dependent and insufficiently benchmarked

The architecture can execute parallel tools, but it cannot force a weak model to choose correct tools, batch calls, avoid loops, or follow verification instructions. Existing internal audits already identify model/provider behavior as a dominant latency and quality variable.

A large unit suite validates machinery, not coding-agent success. The startup needs repeatable end-to-end tasks with:

- completion rate;
- human interventions;
- wall time;
- model calls;
- input/output/cache tokens;
- cost;
- files changed;
- tests/runtime proof;
- false-success rate.

### P1 — Packaging and operator experience need work

`src/main.py` is an import-time interactive loop rather than a clean `main()`/Typer entry point. The project declares no console script in `pyproject.toml`. Runtime state is created under `~/.pulseai` during module import. These choices make embedding, testing, service operation and clean shutdown harder.

## Desktop folder decision

There is **no tracked `desktop/` directory in the current repository HEAD**. It has already been removed/deferred and `.gitignore` contains `desktop/`.

No deletion was necessary. The README still contains a stale project-tree line describing `desktop/`; that documentation should be removed or marked as deferred. Historical audit references can remain because they explain the decision.

## Recommended startup plan

### Week 1: Make claims match reality

1. Get all tests green on the officially supported OS.
2. Declare the supported Python and OS matrix.
3. Fix the esbuild dependency/gate so syntax verification cannot silently disappear.
4. Remove or label incomplete approval, rollback and diff-review claims.
5. Update README test counts and remove the stale desktop tree entry.

### Week 2: Secure the dashboard

1. Default-bind to `127.0.0.1`, not `0.0.0.0`.
2. Replace wildcard CORS with an explicit local origin.
3. Add authentication before any remote/shared deployment.
4. Scope SSE history and subscriptions by authenticated session/thread.
5. Add request concurrency/rate limits and workspace authorization.

### Week 3: Converge the engine

1. Split `chat_graph.py` into node modules: task, planning, execution, recovery, finalization and session runtime.
2. Move graph/checkpointer construction into an application factory.
3. Remove duplicate helpers and reduce broad silent exception handling.
4. Introduce typed result states for `passed`, `failed`, `skipped` and `unavailable` verification.

### Week 4: Prove one marketable workflow

Choose one narrow startup promise, for example:

> “Given an existing Python repository, fix a failing test and return a verified patch.”

Run 30–50 fixed benchmark tasks on one pinned provider/model. Do not add features until the workflow meets explicit success, latency, cost and false-success targets.

## Final assessment

**Is the agent good?** Yes—as an advanced prototype and agent-runtime research base. It contains several pieces worth preserving and commercializing.

**Is it ready for startup customers?** Not yet. It is too complex, the web control plane is not secure or isolated, some advertised controls are placeholders, the suite is not green cross-platform, and end-to-end coding quality is not yet proven with a stable benchmark.

**Best next move:** stop expanding the feature surface. Turn the strongest existing path into a small, secure, measurable product. The project’s biggest risk is no longer lack of capability; it is failure to converge.
