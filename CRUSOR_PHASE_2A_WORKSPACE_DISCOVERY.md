# Phase 2A — Real Workspace Discovery

**Date:** 2026-11-12
**Starting / final HEAD:** `fb5bd528b40933346c4004a1490154683dc0d40e` (no commit, no reset, no clean, no checkout)
**Branch:** `feat/prompt-cache-stabilization`
**Provider calls:** none intended. One repair dispatch was triggered accidentally by a mock-mode acceptance harness (details in §8) — total ₹0.0601.
**Status:** implemented and verified with deterministic tests; engineering still cannot edit intelligently (Phase 2B/2C remain).

---

## 1. Why this phase existed

The terminal qualification proved the engineering path was **generation + verification**, not engineering:

- Test B "completed" by creating `src/req_001_module.py`, `src/req_003_module.py`, `tests/test_req_001_module.py`.
- Nothing in the path listed, read or searched the workspace.
- `extract_contract` synthesised `src/<requirement_id>_module.py` whenever a requirement did not name a file.

Phase 2A makes the engine **discover the real project first**, then plan against real paths.

## 2. Architecture (implemented)

```
User request
   └─ LangGraph chat_graph.engineering_task_node        (unchanged owner)
        └─ EngineeringExecutionOrchestrator.run_task_request   (unchanged owner)
             ├─ STAGE 3 PROJECT_DISCOVERY
             │    ├─ PersistentProjectIntelligenceManager (existing)
             │    └─ STAGE 3b: WorkspaceDiscovery                  ← NEW
             │         ├─ workspace.list_files   (bounded walk)
             │         ├─ workspace.search       (bounded literal search)
             │         └─ workspace.read_file    (bounded excerpt reads)
             │              └─ WorkspaceEvidence (ranked, bounded) ← NEW
             ├─ STAGE 5.5 CONTRACT_EXTRACTION
             │    └─ extract_contract(..., workspace_evidence)     ← CHANGED
             │         target = explicit → requested pool → DISCOVERED file
             │         (synthesis only when discovery found no role candidate,
             │          named from the request, never from a requirement id)
             ├─ STAGE 6 ENGINEERING_PLAN
             │    └─ planner.build_plan(..., workspace_evidence)   ← CHANGED
             │         node.contract["workspace_evidence"] = target + neighbours
             ├─ STAGE 10 IMPLEMENTATION (unchanged)
             │    └─ mutation broker + approval gateway (unchanged)
             └─ DeliveryContract.workspace_discovery (paths only)  ← NEW FIELD
```

Everything else is untouched: LangGraph owns the turn, the orchestrator owns engineering, the model gateway is the only model boundary, mutations go through `WorkspaceMutationBroker`, approvals are unchanged, the journal is append-only, FinOps is unchanged.

## 3. Tools implemented

`src/workspace/discovery.py` — one narrow service, not a second agent registry.

| Tool | Bounds | Result |
|---|---|---|
| `workspace.list_files` | depth 8, 800 entries (caller-adjustable), ignore set, symlinks skipped | `entries[{path,kind,size,depth}]`, `truncated`, `truncated_reason`, `skipped_ignored`, `skipped_symlinks`, `visited_dirs` |
| `workspace.read_file` | 64 KB / 600 lines by default, 4 MB hard reject | `content`, `encoding`, `bytes_read`, `total_bytes`, `lines_returned`, `truncated` |
| `workspace.search` | 50 results, 600 files, 2 s (caller-adjustable), literal only | `matches[{path,line,column,excerpt}]`, `truncated`, `files_scanned` |

Reuse instead of duplication:

- Path containment/symlink/ADS/device-name protection: `src/workspace/path_safety.PathSafetyValidator` (existing, tested).
- Ignore policy: `src.context.repo_map.IGNORED_DIRS` (existing single source of truth).
- Contract/symbol parsing: `src.orchestration.contract.parse_prompt_contract` (existing).
- No shell is invoked anywhere; no command string is interpolated.

Every call produces a `ToolCall` record: `tool`, `tool_call_id`, `event_id`, `journal_event_id`, `session_id`, `turn_id`, `task_id`, `sequence`, `status`, `duration_ms`, `result_bytes`, `truncated`, `truncated_reason`, `error`. The orchestrator journals each as `WORKSPACE_TOOL_CALL` and the aggregate as `WORKSPACE_DISCOVERED`.

## 4. Evidence and planner integration

`src/workspace/evidence.py` performs one bounded pass:

1. list the workspace (800 entries),
2. probe package directories named by the request (`<term>`, `src/<term>`, `lib/<term>`, `app/<term>`, `packages/<term>`) so a large repository cannot truncate the package away,
3. literal search for up to 4 request terms (symbols, mentioned file stems, path-vocabulary words from the request and recent graph context),
4. read ≤4 bounded excerpts (best implementation, its test, documentation, second implementation),
5. rank by path/stem/content match, definition density and source-root location.

The contract now resolves targets in this order: explicit mention → user-requested pool → **discovered candidate** → synthesis. Synthesis is only reached when discovery found no candidate of that role, and it is named from the user's symbol/request (`src/divide.py`), never from a requirement id. `__init__.py` is treated as a package surface: it is chosen only for export/package requirements. Ambiguity (two equally-ranked candidates) is recorded and blocks the plan before dispatch instead of fabricating a file.

The plan node carries a bounded `workspace_evidence` digest (target + ≤3 neighbours with symbols and short excerpts); `ModelExecutionAdapter._contract_block` renders it so generation sees the real package surface. The target file's existing content is still appended by the existing adapter path.

## 5. Deterministic test results (no provider)

`src/tests/test_workspace_discovery_phase2a.py` — **9 passed in 52.1 s**.

| Test | Covers | Result |
|---|---|---|
| A | list the real fixture; ignored dirs excluded; identity fields complete | PASS |
| B | read exact source; line-bounded read reports truncation | PASS |
| C | search returns the correct file and line | PASS |
| D | `divide()` plan targets `src/mini_math/ops.py`, `tests/test_ops.py`, `src/mini_math/__init__.py`, `README.md`; evidence attached to nodes | PASS |
| E | `clamp()` plan invents no `req_*`/`*_module.py` target | PASS |
| — | ambiguous workspace blocks instead of fabricating | PASS |
| F | `../`, absolute, `..` inside path, drive-relative, NUL, symlink escape, 4.1 MB file, binary file, invalid UTF-8, ignored dirs, result truncation | PASS |
| G | cancellation mid-walk, entry cap, depth cap, unknown tool | PASS |
| H | **graph-level**: `stream_agent(canonical_runtime=True)` → journal shows `WORKSPACE_TOOL_CALL` ×N, then `WORKSPACE_DISCOVERED`, then `CONTRACT_EXTRACTED`/`PLAN_GENERATED`; contract targets are real files; delivery carries `workspace_discovery` | PASS |

Regression suites run:

| Suite | Result |
|---|---|
| `test_contract_assignment_reliability`, `test_p0_6_8_contract_first`, `test_planner_phatic_gate`, `test_planner_manual` | **76 passed** |
| `test_p0_6_6_execution_reliability`, `test_p0_6_7_autonomous_closure`, `test_phase_11_6_autonomous_execution`, `test_scope_fidelity`, `test_hermes_tool_name_parity` | **115 passed** |
| `test_phase_12_1_end_to_end_acceptance` | **5 passed** |
| `test_security_containment`, `test_desktop_workspace_boundary`, `test_workspace_isolation`, `test_agent_core_checkup` | **261 passed, 4 skipped** |
| `test_canonical_runtime_engineering_delegation`, `test_engineering_progress_events`, `test_canonical_runtime_increment2`, `test_p0_3_orchestrator_integration` | 54 passed, **1 pre-existing failure** (`turn_lifecycle`, see §8) |
| `test_contract_natural_language`, `test_bridge_orchestrator_protocol`, `test_attempt11_product_delivery_boundary` | passing |
| `test_autonomous_runtime_contract` | **3 pre-existing failures** (chat prompt assembly, see §8) |

## 6. Engine acceptance (deterministic mock, disposable fixture)

`%TEMP%\Phase2A_Acceptance\workspace\mini_math` (copy of the qualification fixture), `mock_mode=True`, `max_correction_attempts=0`:

- verdict `FAILED` (mock code does not implement `divide`; expected — Phase 2A does not change generation).
- `workspace_discovery.files_listed = 5`, 10 tool calls, selected = README, `tests/test_ops.py`, `src/mini_math/ops.py`, `src/mini_math/__init__.py`, `pyproject.toml`.
- journal order: `WORKSPACE_TOOL_CALL` ×9 → `WORKSPACE_DISCOVERED` → `CONTRACT_EXTRACTED` → `PLAN_VALIDATED` → `PLAN_GENERATED`.
- contract targets: `tests/test_ops.py` (TEST), `src/mini_math/ops.py` (SOURCE). No requirement-id paths.
- mutation receipts: the same two real files (through the existing broker/approval path).
- paid invocations in that fixture: **0** (with repairs disabled).

## 7. Performance

On the real Crusor repository (771 listed entries), steady-state discovery is **~1.65 s** (listing 447 ms, one search 632 ms, four bounded reads ~10 ms total). The first call in a process additionally pays the one-time import of the contract/intelligence modules (~12 s), which the orchestrator already pays on the first engineering turn.

## 8. Honest findings

1. **Accidental paid call.** The first acceptance harness ran with the default `max_correction_attempts=3`; the mock-generated code failed the fixture tests and the pre-existing repair loop dispatched a real provider call (`purpose=repair_task_ops`, 1,409 in / 2,901 out, ₹0.0601, settled). It mutated only the disposable fixture. Re-run with repairs disabled: 0 paid invocations. Programme spend is now **₹0.4808 of the ₹50 cap**. The repair loop is not gated by `mock_mode` — recorded as B-CORE-006.
2. **Pre-existing failures (not Phase 2A).**
   - `test_p0_3_orchestrator_integration::test_desktop_bridge_reaches_model_backed_executor` expects `turn_lifecycle`; the uncommitted bridge emits `turn_started`/`turn_done` (HEAD still maps `turn.started` → `turn_lifecycle`).
   - `test_autonomous_runtime_contract` (3 failures) asserts chat prompt-assembly block counts (`fused_system_blocks` 5 vs 6); the dirty prompt/runtime files are user work.
   Neither suite touches the files changed here.
3. **Discovery is fail-soft by design.** If discovery raises unexpectedly, the turn continues with request-only targeting and journals `WORKSPACE_DISCOVERY_FAILED`; the plan guard only rejects requirement-id targets when evidence exists. This avoids turning a discovery bug into a hard outage, at the cost of falling back to legacy behaviour.
4. **Ranking is lexical.** Discovery ranks by path/stem/content overlap and definition density. It cannot understand semantics; on large repositories an unrelated match can rank a documentation file first (role filters still keep SOURCE/TEST resolution honest). When no candidate is convincing, the contract reports ambiguity and blocks.
5. **No mutations, no command execution, no repair loop changes.** Phase 2B (targeted edits) and 2C (test-diagnose-repair) remain unimplemented.

## 9. Files

| File | Change |
|---|---|
| `src/workspace/discovery.py` | **new** — three bounded read-only tools + lifecycle records |
| `src/workspace/evidence.py` | **new** — ranked evidence, digests, journal-safe summary |
| `src/orchestration/contract.py` | discovery-first target resolution, ambiguity, requirement-id guard, request-derived synthesis |
| `src/orchestration/planner.py` | accepts evidence, attaches per-node workspace evidence |
| `src/orchestration/orchestrator.py` | STAGE 3b discovery, journaling, cancellation, contract/planner/validation wiring, delivery evidence |
| `src/orchestration/model_adapter.py` | renders discovered neighbours in the contract block |
| `src/orchestration/models.py` | `DeliveryContract.workspace_discovery` |
| `src/tests/test_workspace_discovery_phase2a.py` | **new** — tests A–H |

## 10. Git status

```
HEAD:        fb5bd528b40933346c4004a1490154683dc0d40e (unchanged)
branch:      feat/prompt-cache-stabilization
dirty:       254 entries (250 before this phase), 178 untracked, 0 deletions
new:         src/workspace/discovery.py, src/workspace/evidence.py,
             src/tests/test_workspace_discovery_phase2a.py
modified:    src/orchestration/{contract,planner,orchestrator,model_adapter,models}.py
```

Nothing reset, cleaned, checked out, committed or pushed. Pre-existing user changes are preserved.

## 11. Remaining limitations / next

- **2B:** targeted edits (patch existing files instead of regenerating them) through the broker; generate-then-mutate currently rewrites the whole file.
- **2C:** test-diagnose-repair loop driven by discovery evidence and executed tests.
- Required: a bounded format-recovery re-prompt on `SourceExtractionError` (B-CORE-002).
- Discovery evidence is not yet used by the verification/repair stages.
