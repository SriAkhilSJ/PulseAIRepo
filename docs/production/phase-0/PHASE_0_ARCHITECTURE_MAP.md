# Phase 0 — Architecture Map

**Method:** plain-text inspection of the desktop contribution, bridge, runtime,
FinOps and evidence code. No module was imported or executed.

---

## 1. System shape

```text
┌──────────────────────────────────────────────────────────────────────┐
│ CrusorAI.exe (Electron 42.8.1, VS Code fork)                         │
│  workbench + contrib/crusorai (TypeScript)                          │
│   ├ renderer service (chat, cards, plan, tool rows, status)          │
│   └ worker utility process (crusorAIWorkerProcessService.ts:156)    │
│        spawn(<venv python>, ['-m','src.bridge'], env={...process.env})│
└──────────────────────────────┬───────────────────────────────────────┘
                               │ stdio JSON-RPC, protocol v2
┌──────────────────────────────▼───────────────────────────────────────┐
│ Python engine — src/bridge/__main__.py (single process, 166 KB)      │
│  ├ session / turn / submission guard                                 │
│  ├ orchestration: planner, contract, task_validation                 │
│  ├ context engine: budget, compaction, history, memory               │
│  ├ tools + WorkspaceMutationBroker                                   │
│  ├ provider gateway: governed reserve → invoke → usage → settle      │
│  └ FinOps: reservations, invocation ledger, recovery                 │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
        ┌──────────────────────┼─────────────────────────┐
        ▼                      ▼                         ▼
  <workspace>/.crusorai/   CRUSORAI_HOME/          evidence dir
  submissions/, finops/,   sessions.db, evidence/  (immutable run package)
  journals/, test_reports/ runtime_events.db
```

---

## 2. Desktop-to-bridge protocol

- Version: **v2** (`src/bridge/protocol.py:7`, `SUPPORTED_PROTOCOL_VERSIONS = {1, 2}`).
- Schema: `src/bridge/protocol_v2.json` is the source; the TypeScript surface is
  generated (`desktop/.../common/crusorAIProtocol.generated.ts`,
  `scripts/generate_bridge_protocol.py`) — a genuine strength.
- Client methods include `hello`, `session_create`, `session_load`,
  `session_delete`, `prompt`, `cancel`, `safety_reply`, `shutdown`.
- Server frames include:
  `hello`, `session_info`, `session_messages`, `session_deleted`,
  `turn_started`, `turn_lifecycle`, `token`, `token_retract`, `reasoning`,
  `plan_updated`, `tool_call_start`, `tool_call_args`, `tool_call_progress`,
  `tool_call_end`, `tool_output`, `safety_request`, `clarify_request`,
  `todo_updated`, `verification_updated`, `subagent_updated`, `telemetry`,
  `checkpoint_event`, `turn_done`, `turn_failed`, `runtime_degraded`,
  `context_status`, `events_replay`, `workspace.bound`, `llm.request`,
  `llm.response`, `error`.
- Every frame carries `CrusorIdentity` (run/session/turn/workspace) for
  correlation.
- Worker spawn preserves `process.env` (`crusorAIWorkerProcessService.ts:158`),
  which is how `CRUSORAI_AUTOTITLE=off` and budget variables reach Python.

**Risk.** The protocol is hand-written JSON + a generator, not a schema
validator on both ends at runtime. Drift is caught by tests, not by a wire-level
contract check.

---

## 3. Exactly-once submission lifecycle

`src/runtime/submission_ledger.py`

```text
session_create  → accepted
prompt claim    → running      (atomic, one winner)
terminal        → completed | failed | cancelled
```

- Durable file: `<workspace>/.crusorai/submissions/submissions.json` plus an
  append-only `submissions.jsonl` event stream.
- Stable `submission_id`; prompt SHA-256 association.
- `claim_prompt` (`:218-263`) rejects replay, a non-accepted state, and a
  session mismatch.
- `mark_terminal` (`:264+`) is idempotent; repeated terminal marks are no-ops.
- `find_recent_completed` (`:158-173`) is the legacy replay fallback for frames
  without an ID, bounded by a window.
- Startup reconciliation marks abandoned `running` submissions `failed`
  (`src/finops/recovery.py:95-109`), so a reconnect cannot replay them.

**Risk.** The renderer also keeps a pending prompt; a second different prompt
while `session_create` is in flight can still race (audited as a non-blocking
edge defect for a one-gesture run).

---

## 4. Financial lifecycle

`src/orchestration/finops_governor.py`, `src/finops/governed.py`,
`src/finops/recovery.py`

```text
reserve (budget + token ceiling)
  → in_flight (persisted immediately before wire dispatch)
  → settled   (authentic usage + calculated cost, once)
  → uncertain (timeout / post-dispatch ambiguity; hold retained)
  → released  (provably never dispatched)
```

- Reservation status union: `reserved`, `in_flight`, `reconciled`, `released`,
  `uncertain` (`finops_governor.py:67`).
- `mark_in_flight` persists synchronously (`:589-600`).
- `mark_uncertain` retains the hold and persists (`:602-626`).
- `reconcile_orphaned_reservations` (`:776-837`) maps
  `in_flight → uncertain`, `reserved → released`.
- Shutdown uses `force=True` to sweep the whole workspace
  (`src/bridge/__main__.py:590-613`).
- Canonical settlement uses the canonical reservation ID and is idempotent;
  missing usage is fail-closed.

**Risk.** Several money surfaces exist: canonical
`financial_reservations`, the invocation ledger (`provider_invocations.jsonl`),
per-task `*_finops.json`, and the workspace aggregate. They are reconciled, but
there is no single transactional store. Reconciliation is time-heuristic
(`_PROCESS_START`, `force=True`), not lease/fencing-token based.

---

## 5. Context engine and token economics

- `src/context/context_engine.py` is a facade over
  `src/context/core/context_engine.py`, state, builder, layer policy, compaction,
  history shaper, summarizer, memory and repo map.
- `src/context/token_budget.py` trims messages; `context/engine.py` defines the
  ABC and `sanitize_memory_context`.
- `docs/AGENT_CORE_FULL_AUDIT_2026-11-01.md` records real long-session evidence:
  turns at **716,050 / 925,941 tokens** with 20–33 calls, then budget CUT.
- `docs/AGENT_CORE_HARDENING_SLICE.md` measured durable-evidence reduction
  (−99.64% payload, −99.11% SQLite) and deterministic context selection, and
  explicitly does **not** claim provider-token reduction.

**Risk.** Token economics are still dominated by long turns. The ₹50 benchmark
ceiling can be consumed by a few heavy turns. No 24-hour soak exists.

---

## 6. Completion and verification

- `src/graphs/task_validation.py` defines verdicts
  `COMPLETED / PARTIALLY_COMPLETED / FAILED / CANCELLED / BLOCKED`, a structured
  receipt, file hashing and test-output binding.
- The bridge emits `verification_updated` and `turn_done`; the desktop renders
  the status.
- P0.6.9 historical verdict: **`P0.6.9_ACCEPTANCE_FAILED`**.
- The LIVE12 harness adds independent smoke tests and in-turn test evidence for
  the duration task.

**Risk.** The acceptance harness is hardcoded to `src/duration.py` and
`tests/test_duration.py` (`live_acceptance.py:562-563`) and requires a plan with
exactly two work units (`:668`). It cannot verify a different task shape.

---

## 7. UI streaming and tool rendering

- `crusorAIRendererService.ts` handles `token`, `reasoning`, `plan_updated`,
  `tool_call_start/args/progress/end`, `tool_output`, `verification_updated`,
  `turn_done`.
- Tool rows use `.crusorai-tool-row`, `.crusorai-tool-summary`,
  `.crusorai-tool-state`, `.is-running/.is-passed/.is-failed`.
- Live11 screenshots show plan/Thinking and a final response, but **no
  tool-call card**.
- LIVE12 added bounded mid-turn DOM counts + screenshots, but the repaired
  launch has not been re-tested, so visual proof is still absent.

**Risk.** Backend tool events are not proof of visible rendering. The DOM/class
contract is not covered by a component-level visual test.

---

## 8. Evidence architecture

- Every acceptance writes a run directory with `evidence.json`, stage gates,
  screenshots, provider ledger, DB copies and checksums.
- Correlation keys `(run_id, session_id, turn_id)` join the layers.
- Historical evidence is checksummed; the audit did not rewrite it.

**Strength.** This is the strongest part of the system: a failing run still
leaves a usable, traceable package.

---

## 9. Audit-area map

| # | Area | Primary files | Verdict |
|---|---|---|---|
| 1 | Repo/branch state | `git` | Baseline matched |
| 2 | Electron/native bindings | `desktop/vscode/.build`, `node_modules` | Repaired, launch unproven |
| 3 | Desktop build/startup | `out/.../BUILD_INFO.json`, launch logs | Compile PROVEN; launch FAILED then repaired |
| 4 | Desktop→bridge protocol | `src/bridge/protocol.py`, `crusorAIProtocol.generated.ts` | Implemented, tested offline |
| 5 | Exactly-once | `src/runtime/submission_ledger.py` | Code PROVEN; live UNPROVEN |
| 6 | Financial accounting | `finops_governor.py`, `recovery.py` | Code PROVEN; live UNPROVEN |
| 7 | Context/token economics | `src/context/*`, audit docs | Implemented; 24h UNKNOWN |
| 8 | Completion/verification | `task_validation.py`, harness | Implemented; P0.6.9 FAILED |
| 9 | UI streaming/tool rendering | `crusorAIRendererService.ts` | Streaming code; visual UNPROVEN |
| 10 | CI/tests/live evidence | `.github/workflows`, diagnostics | 366 slice PASS; full/live gaps |

---

## 10. Architectural verdict

**Strong spines:** protocol generation, exactly-once ledger, fail-closed money,
evidence-first runs, process isolation.

**Weak spines:** import-time Windows security mutations (P0), task-specific
acceptance, multiple money stores, time-based reconciliation, monolithic bridge,
non-hermetic packaging, unproven visual layer, no 24-hour evidence.

```text
ARCHITECTURE_VERDICT: STRONG_BONES_PARTIAL_PROOF
```
