# Phase 3.1 — Active orchestrator approval integration: verdict

**PHASE 3.1: PASS (bounded scope).**

The default `EngineeringExecutionOrchestrator` no longer auto-approves. It asks
the existing session-scoped `ApprovalQueue`, publishes the existing Protocol v2
`safety_request`, waits for the desktop's `safety_reply`, validates the reply
against session and request, issues a single-use `RiskApprovalGate` token bound
to task/workspace/path/operation, and the mutation broker verifies and consumes
it before writing.

This is not Agent Core production readiness. The known graph import defect
(B-DESK-001) and the pre-existing planner failures remain out of scope.

## Acceptance evidence

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Default orchestrator no longer auto-approves | **PASS** | stage-9 now calls the gateway; no `grant_approval(..., "APPROVE")` on the approval-channel path; probes: files absent until reply |
| 2 | Actual desktop approval response controls execution | **PASS** | Electron smoke: dock from orchestrator, clicked Allow once twice, files then created (`desktop-smoke.txt`, screenshots 04/05) |
| 3 | Denial and cancellation prevent the mutation | **PASS** | deny/timeout/cancel probes: `turn_done cancelled=true`, no files; unit tests |
| 4 | Authorization scoped and validated at the mutation boundary | **PASS** | `APPV-` token bound to task/workspace/path/op; broker consumes once; wrong-resource and replay tests |
| 5 | Provider-free integration tests pass | **PASS** | 9/9 new; 112 passed, 3 deselected pre-existing (`tests.txt`) |
| 6 | Existing regression coverage preserved | **PASS (touched areas)** | 11.3 discipline 36, p0_3 7, bridge orchestrator 4, transport 15, protocol 9, approval testimony 3 |

## What changed

- `src/orchestration/approval_gateway.py` (new): policy-aware
  (`ask`/`workspace_session`/`session`), publishes to `event_bus`, waits on the
  shared queue with cancellation wake-up, issues scoped risk tokens.
- `orchestrator.py`: stage 9 asks the gateway per target; tokens map
  `(node_id, path)` → token and are passed into execution. Headless callers
  without `approval_channel` keep the historical supervision path.
- `model_adapter.py` / `implementation_engine.py` path: token travels to
  `broker.create_file/modify_file`, which verifies and consumes it.
- `event_bus.py`: `resolve()` refuses non-pending (duplicate/stale) replies;
  `wait_for_decision(should_stop=...)` wakes on turn Stop.
- `bridge/__main__.py`: constructs the orchestrator with
  `approval_channel=True`, the computed policy, session id and cancellation
  predicate; maps `ApprovalDenied` to a cancelled terminal; adds
  `CRUSORAI_ORCHESTRATOR_MOCK=1` for provider-free smoke.
- `evidence_capture.py`: orchestrator/approval/echo turns record trace/report as
  `not_applicable` (no false yellow banner); executed turns stay strict.

## Scenario matrix

| Scenario | Result |
|---|---|
| Approval requested | PASS — `safety_request` with task/session/workspace/path/operation/reason |
| User approves | PASS — exact file written, token verified |
| User denies | PASS — no file, cancelled terminal |
| Timeout (configured) | PASS — no file, cancelled terminal |
| Turn cancel | PASS — wait wakes, no file, cancelled terminal |
| Wrong-session reply | PASS — refused, correct reply still works |
| Stale/duplicate reply | PASS — refused, cannot re-authorize |
| Different resource | PASS — token bound to path/op; verification fails |
| Low-risk under `workspace_session` | PASS — silent; high risk still asks |

## Limitations / not proven

1. **Real provider/graph pipeline** not used: B-DESK-001 still breaks
   `stream_agent`. The orchestrator path is the one repaired here and it runs
   the deterministic local generator in the smoke.
2. **Desktop denial click** was not re-shot; the deny path is proven at the
   bridge/queue level and uses the same `safety_reply` handler.
3. **Approvals are requested at stage 9**, before code generation, so the dock
   has no file diff body (`Review change` is absent). Resource/operation/reason
   are present. Moving the ask to mutation time would be a follow-up.
4. **Pre-existing red tests** remain: 8 planner/contract failures in
   `test_phase_11_6`, `test_plan_approval.py` import failure, 3 POSIX/echo
   evidence tests, and one terminal message-text mismatch. None are in files
   touched here.
5. Not whole-product production readiness; no model tournaments.

## Provider calls

Zero. Every run used `CRUSORAI_ORCHESTRATOR_MOCK=1`; probe sequences contain no
`llm.request`/`llm.response` frames; no live-agent flag, no paid API.
