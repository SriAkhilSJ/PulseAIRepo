# Agent Core — Independent Verification (2026-10-30)

**Scope:** verify, from the code that actually runs (not from the existing
audit documents), what the Agentic Core is, how one turn executes, which
completion invariants are mechanically enforced, and what state the suite is
in on this commit.

**Base commit:** `3e376c80` (`main`), branch `arena/173f9f1b-pulseairepo`.

**Method:** static read of every core module; live import + graph compile;
execution of the real test suite; targeted reproductions of every claimed
invariant that could be exercised without a provider key.

> **Honesty note.** This is provider-free verification. No live model turn was
> run, so nothing here re-validates the GatePulse 16/16 benchmark claims, and
> nothing here should be read as an end-to-end pass.

---

## 1. What the Agentic Core actually is

One sentence: **a deterministic LangGraph supervisor that surrounds a
non-deterministic model with state-derived routing, a tool waist, a safety
gate, and evidence-based completion gates — the model proposes, the graph
decides.**

| Layer | Real implementation | Verified fact |
|---|---|---|
| Transport | `src/bridge/__main__.py` (`BridgeServer`, l.94), `src/bridge/protocol.py` | NDJSON over stdio/binary; protocol v2; **33 client methods, 39 server events**; 1 MiB frame cap; `type` required on every frame |
| Serving (IDE/AG-UI) | `src/server.py` | `LangGraphAGUIAgent` over FastAPI; same compiled graph |
| Headless harness | `scripts/run_bridge_turn.py` | `--timeout-s 5400`, `--max-llm-calls 60`, `--max-no-delivery-calls 12`; returns exit 0 only on `turn_done` |
| Orchestration | `src/graphs/chat_graph.py` (7,960 lines), `gates.py`, `budget.py`, `state.py`, `loop_guards.py`, `parallel_tools.py` | **14 nodes**, compiled with a persistent `SqliteSaver` |
| State | `src/graphs/state.py` | `AgentState(CopilotKitState)`; ~50 channels: budget, plan, verification, revision, diagnostics, user-interest |
| Context | `src/context/` (`context_engine.py`, `layer_policy.py`, compaction/memory modules) | **17 ordered layer builders + `git_context` volatile tail = 18 layers**; per-session engine (LRU 128), not a global singleton |
| LLM | `src/llm/` (`factory.py`, `preflight.py`, `output_budget.py`, `repetition_guard.py`) | Provider-agnostic adapter, dynamic window discovery, output-cap clamp, degenerate-output guard |
| Tools | `src/tools/` (registry) | **63 known tool names**, narrowed per turn by runtime profile |
| Tool execution | `SafeToolNode` (`chat_graph.py:5975`), `src/runtime/tool_middleware.py:84` | Single durable chokepoint for direct/parallel/PTC calls; intent→result ordering; redacted projection |
| Safety | `src/context/safety_guard.py`, permissions in `chat_graph.py:264` | Path containment, critical-path veto, dangerous-command taxonomy, one rule per path per tool (tool switching is not a bypass) |
| Verification | `src/graphs/gates.py`, `src/runtime/verification_ledger.py`, `status_contract.py`, `workspace_controller.py` | Hashed failed-check debt, 4-state receipts, tri-dimensional status contract, monotonic revision ledger |
| Observability | `src/runtime/event_journal.py`, `otel_tracing.py`, `step_tracker.py`, `src/dashboard/event_bus.py` | Session-scoped SSE events, replay with newest-state retention, OTel spans off by default |

### Graph topology (read from the compiled graph, not the docs)

```
START → task_manager
task_manager → ai | planner | plan_reviser | plan_cancelled | approval_without_plan
planner     → ai | plan_preview          plan_reviser → plan_preview → END
ai          → tools | finish_gate | finalize
tools       → progress
progress    → ai | pivot | recovery_limit | tool_cycle_limit | finish_gate | finalize
finish_gate → ai                          pivot → ai
recovery_limit / tool_cycle_limit / finalize → END
```

Nodes: `task_manager, planner, plan_preview, plan_reviser, plan_cancelled,
approval_without_plan, ai, tools, progress, finish_gate, pivot,
recovery_limit, tool_cycle_limit, finalize`.

**Doc drift found:** `CRUSORAI_AGENT_CORE_ARCHITECTURE_AUDIT.md` lists
`verification_repair` and `verification_recheck` as *nodes*. They are not
nodes — they are state-derived `ExecutionPhase`s (allowlists + guidance)
computed in `_resolve_bound_tools` (`chat_graph.py:1586`, phases at
l.1819/1837) and persisted into `config.configurable`. The behaviour is real;
the topology description is wrong.

---

## 2. One turn, mechanically

1. **Bind.** Session must carry an absolute workspace; `BridgeServer` rejects
   unbound commands (`NO_WORKSPACE_ERROR`). Turn-scoped state is reset
   (`_turn_scoped_resets`, `chat_graph.py:1930`) even on checkpoint resume.
2. **Classify.** `task_manager_node` resolves `UserInterest`
   (objective / latest instruction / constraints / `act` vs `answer` /
   `no_changes`). A plan-mode or approval-without-plan path can exit before
   any model work.
3. **Assemble.** `ai_node` (`chat_graph.py:2096`) asks the session's
   `ContextEngine` for messages: deterministic layer order
   (`layer_policy.BUILDER_ORDER`), budget-driven selection, prune-first
   compaction, and a single volatile tail so the byte-stable prefix survives
   provider prompt caching.
4. **Narrow tools.** `_resolve_bound_tools` maps the runtime profile to an
   allowlist, then applies state-driven phases in priority order: forced
   delivery → missing delivery → failed-check repair → exact recheck →
   verification reserve. The allowlist is written into the tool-node config,
   so a repaired/renamed tool call cannot escape it.
5. **Model.** Streamed through `_AgentTokenPump`; provider metadata, usage,
   reasoning deltas, and partial tool arguments are normalised. Output-cap
   truncation becomes a bounded continuation, not a silent stop.
6. **Execute.** `SafeToolNode` checks cancellation, repairs tool names,
   enforces permissions/approvals (fail-closed), runs calls (parallel with
   conflict detection), records the mutation, and emits a `ToolMessage`.
7. **Route.** `should_continue` (`gates.py:822`) decides the next hop from
   *behaviour and state only*: cancellation, degenerate repetition,
   truncated-response continuation, ask-mode end, wrap lap, no-tool streak
   (`NO_TOOL_TURN_LIMIT = 3`), stall continuation, pending tool calls
   (always dispatched), budget grace, missing deliverables, unsatisfied
   verification.
8. **Gate.** `finish_gate_node` (`gates.py:1388`) fires at most bounded
   times per counter and picks the matching nudge (delivery, verification,
   activity, continuation).
9. **Finalize.** `finalize_node` (`chat_graph.py:2938`) re-derives the truth:
   workspace revision, 4-state verification receipt, deliverable presence,
   trailing failures, mid-task ending → `synthesize_status_contract`
   (`status_contract.py:92`). Completion is **derived**, never claimed:

```python
completed = run_outcome == "completed"
        and verification_status in {"verified", "not_required"}
        and specification_status == "complete"
# and "not_required" is rewritten to "unverified" if code was produced
```

### Bounds that actually bind (verified constants)

| Bound | Value | Source |
|---|---|---|
| Provider calls / turn | default 45, clamp 60 | `budget.py:29-30, 81-84` |
| LangGraph recursion backstop | `max(200, budget*4 + 40)` | `budget.py:141` |
| Turn token budget | 600k default, clamp 2M | `budget.py` (`_TOKEN_BUDGET_*`) |
| Verification reserve | 30k tokens / 6 iterations | `budget.py` (`_VERIFICATION_*_RESERVE`) |
| No-tool assistant streak | 3 | `loop_guards.NO_TOOL_TURN_LIMIT` |
| Stall re-prompts | 2 / turn | `should_continue` |
| Finish / verify nudges | 2 each | `gates._FINISH_NUDGE_BUDGET`, `_VERIFY_NUDGE_BUDGET` |
| Checkpoint DB | `~/.crusorai/sessions.db`, WAL, busy_timeout 10 s | `chat_graph.py:7360-7380` |
| Context engines | 128 per process (LRU, per thread) | `chat_graph.py:_ENGINES_MAX` |

---

## 3. Completion integrity — what is actually enforced

This is the part of the core that matters most, and it holds up under reading:

1. **Failed-check debt is identity-scoped.** `_verification_trace_key`
   (`gates.py:439`) hashes the canonical check; `_unresolved_failed_verification_checks`
   (`gates.py:457`) replays the trace, requires a *successful mutation* before
   a recheck is even offered, and clears debt only when the **same** check
   passes. A different, weaker green command cannot authorize completion.
2. **Repair and recheck are structurally separated.** Repair exposes
   inspection + mutation only; recheck exposes checks only. If a profile has no
   mutation tools, the graph does not fall through to an unchanged recheck.
3. **Verification receipts go stale on mutation.** `WorkspaceController`
   (`workspace_controller.py:53`) increments a monotonic revision on file
   writes and mutating shell commands; receipts are invalidated unless the
   change is documentation-only.
4. **Environment failures are not source debt.** Missing executables /
   PATH failures route to pivot, not to an arbitrary edit.
5. **Deliverable evidence is checked on disk** before a turn may finalize,
   and named targets are parsed from an explicit file ledger, not prose.
6. **Approvals fail closed.** Cross-session resolution is rejected; timeout
   means deny; sensitive/escaping/non-file operations cannot be auto-approved.
7. **Event isolation.** Session-scoped SSE delivery, bounded replay that keeps
   the newest state, dead-subscriber eviction, paired tool events after
   compaction (`src/tests/test_event_safety.py`, 21 passing contracts).

---

## 4. Verification evidence (run on this commit)

Environment: Python 3.11.2 venv (repo pins 3.14), pytest 9.2, core runtime
deps installed; **no** `sentence-transformers`, **no** pyright/TypeScript,
**no** provider keys. Numbers are therefore environment-shaped.

| Check | Result |
|---|---|
| `import src.graphs.chat_graph` + `graph.get_graph().nodes` | OK — exactly the 14 nodes above |
| `len(all_known_tool_names())` | 63 |
| `len(BUILDER_ORDER)` + volatile tail | 17 + 1 = 18 |
| Fuzzy edit strategies | 9 (`exact` → `context_aware`) |
| Focused core suites (lifecycle, contracts, ledger, phases, gates) | 79 collected → **78 passed, 1 failed** (the defect below) |
| Full suite `pytest src/tests` | **2989 collected → 2944 passed, 21 failed, 23 skipped, 1 xfailed in 288 s** |
| `test_scope_artifact_gates.py` after fix | **13/13 passed** |

`README.md`/`core.md` quote a 25-failure baseline from a different
environment; the 21 here are the same *class* (see §5.3), not a regression
from this branch.

---

## 5. Findings

### 5.1 Defect found and fixed — deliverable evidence was CWD-bound

**Where:** `src/graphs/gates.py::_deliverable_candidates` (l.717).

**What:** the candidate list for a named deliverable included a bare
`Path(target)`. That path resolves against the **engine process's working
directory**, not the bound workspace. So the completion gate could report a
required file as delivered when nothing had been written to the workspace,
simply because the directory the engine was launched from happened to contain
a same-named file (`README.md`, `index.html`, `package.json`, …).

**Reproduced** (workspace = fresh temp dir, task ledger lists `README.md`):

| Engine CWD | `_deliverables_missing_on_disk` |
|---|---|
| repo root (has `README.md`) | `['server.py']` ← false "README delivered" |
| `/tmp` (no `README.md`) | `['server.py', 'README.md']` |

Same state, same task, two different completion verdicts. In the field this
is both a false-positive completion surface and a workspace-containment hole
in evidence gathering.

**Fix:** every candidate is now rooted at the bound workspace. Absolute
targets still work (`ws / <absolute>` collapses to the absolute path). Added
`test_deliverable_evidence_is_workspace_bound_not_cwd_bound`, which chdirs
into a decoy directory and pins the workspace-bound answer in both
directions. 13/13 in that file; 273 passed / 2 pre-existing failures across
all 16 suites that import `gates`.

### 5.2 Documentation drift (behaviour is real, prose is wrong)

| Claim in existing docs | Code reality |
|---|---|
| `verification_repair` / `verification_recheck` are graph **nodes** | They are state-derived tool phases inside `_resolve_bound_tools` |
| "14 specialized nodes" (audit) | Correct — 14 is right |
| 3-tier prompt / "32 layers" (historical) | 17 ordered builders + 1 volatile tail = 18 layers |
| "9-strategy cascade" | Correct (verified list) |
| Universal AST gate (README 2026-10-29) | Correct — but it now also rejects **new** `.py` files with placeholder syntax, which an older test still expects to be allowed (see 5.3) |

### 5.3 The other 20 full-suite failures, triaged

Not caused by this branch; each is one of three kinds.

**Environment / missing artefacts (10):**
`test_api_contract_parity` (3 — missing `run_2_showcase/app.js` and two
`*_RESULTS.json`), `test_model_failure_reproduction` (2 — missing
`bench-results/gpt_4o_mini_logpulse_run_1_showcase/*`), `test_lsp_performance`
(pyright absent), `test_fusiontest_mcp` (no MCP server), `test_hermes_runtime_values`
(pipe/grandchild timing), `test_bridge_transport` (passes in isolation —
load-sensitive), `test_lab_fixes::terminal_timeout` (foreground timeout path
emits a different message than the legacy assertion).

**Stale tests against intentionally changed code (6):**
`test_scaffold_layout_normalization` imports `src.tools.scaffold_tools`, which
another test asserts was **deleted everywhere**;
`test_grace_summary_hermes_law` (2) greps `bridge/__main__.py` for
`turn_model_wall`, which the bridge no longer references;
`test_copilot_parity_permission_diff` and `test_hermes_activity_parity` assert
markup/test-ids that the renderer no longer emits;
`test_review_autopsy_fixes::d28` expects a brand-new skeleton `.py` with
placeholder syntax to be **allowed** while the universal AST gate now rejects it.

**Needs an owner decision (4):**
`test_finalize_chat_turn` (2) assert `task_completed is True` for a run that
"wrote" a file but never verified it — under the 2.0 triad that is correctly
`False`; either the tests or the triad semantics are stale.
`test_reasoning_effort_threading` (2) find no `reasoning_effort` kwarg in the
built request — either the adapter stopped threading it or the test targets a
retired payload shape. This one is worth a real look because it is a *silent*
capability loss rather than a cosmetic drift.

---

## 6. What is verified vs. what is not

**Verified here:** topology, state model, tool waist, safety paths, phase
narrowing, failed-check debt semantics, revision/staleness model, status
contract derivation, checkpoint durability settings, event isolation,
deliverable-evidence binding (after fix), suite health.

**Not verified here:** any live model behaviour, the GatePulse 16/16 claim,
desktop/TS surfaces (no node toolchain in this sandbox), embeddings/long-term
memory (not installed), and the 4 owner-decision failures above.

**Ready for the task.** The next change can be judged against this map:
routing decisions live in `gates.py`, phase/waist in `chat_graph._resolve_bound_tools`,
verification truth in `gates` + `runtime/verification_ledger.py` +
`runtime/workspace_controller.py`, and the final verdict in
`finalize_node` + `runtime/status_contract.py`.
