# P0.6.9 — Baseline

Inspected at `a2e654c6` (local == origin), branch
`feat/prompt-cache-stabilization`.

## 1. The P0.6.8 accounting failure, exactly

Live run `p0_6_5_20261107T211727_fa1f0117`:

| Invocation | Model | Claim | Reservation | Settlement |
| --- | --- | ---: | ---: | ---: |
| Engineering source | `z-ai/glm-5.3-flash` | 1 | yes | yes (`node_task_duration`) |
| Engineering tests | `z-ai/glm-5.3-flash` | 1 | yes | yes (`node_task_tests_test_duration`) |
| Session auto-title | `qwen/qwen3.7-flash` | 1 | **no** | **no** |

The task itself passed: 10/10 tests, contract/cross-file clean. The acceptance
failed only because the auxiliary title call reached the provider outside the
task FinOps governor. `RetryLLMProxy` counted it (the acceptance guard is at the
transport boundary), but counting is not accounting.

The P0.6.8 mitigation (`CRUSORAI_AUTOTITLE=off` + blanket refusal in acceptance)
was a temporary suppression, not governance. P0.6.9 removes it.

## 2. Why a single proxy is not enough

`RetryLLMProxy` is the physical request boundary for every LangChain client, but
it has no financial context: no workspace, no governor, no reservation id, no
attribution. The task governor lives in the orchestrator, far above the proxy.
Auxiliary services (titling, summarizer, curation, compaction) construct clients
directly and call `invoke`, so they passed through the proxy without ever seeing
FinOps.

## 3. P0.6.9 architecture (smallest reliable coverage)

1. **Invocation context** (`src/finops/invocation_context.py`):
   a context scope carries subsystem, reservation id, provider, model and task;
   a workspace-level `provider_invocations.jsonl` records one line per physical
   call with run/session/turn/workspace ids, reservation/settlement ids, usage,
   cost and status.
2. **Governed gateway** (`src/finops/governed.py`): the shared accounting path
   for auxiliary/background calls — verified pricing → conservative bound →
   reserve → one attempt → authentic usage → actual cost → settle. Unpriced,
   unauthorized or ceiling-incapable calls never dispatch; they are recorded as
   `blocked`/`released`. Uncertain calls retain the hold and are recorded as
   `uncertain`.
3. **Task path**: the orchestrator adapter keeps its existing reserve/settle
   logic and now runs the wire call inside the invocation scope and writes the
   same ledger record (`subsystem=engineering`).
4. **Proxy boundary**: inside acceptance mode, `RetryLLMProxy.invoke` refuses to
   run without an active reservation scope. A hidden call cannot reach the
   network.
5. **Session titling**: enabled (no `CRUSORAI_AUTOTITLE=off`), routed through
   the gateway with a session-scoped governor and one attempt; synchronous
   before `turn_done` during acceptance so evidence exists before shutdown. If
   accounting is refused, an explicit local fallback is used and no provider
   call occurs.
6. **Acceptance guard/report**: the harness reads the invocation ledger and all
   FinOps files, requiring every physical claim to equal a settled invocation,
   at least one settled auxiliary invocation, a non-empty session title, and
   task+auxiliary cost equal to the aggregate session cost.

## 4. Lifecycle enforced

`ACCOUNTING_CONTEXT_RESOLVED` (scope/identity) → `COST_ESTIMATED` → `RESERVATION_CREATED` → `PROVIDER_INVOKED` → `USAGE_CAPTURED` → `ACTUAL_COST_CALCULATED` → `SETTLEMENT_COMMITTED` → `RECONCILED` (ledger + FinOps + SQLite).

A failed reservation, unknown price or unenforceable ceiling prevents the call.

## 5. Attribution model

- **Task**: `subsystem=engineering`, `task_id=turn_<id>`, operation
  `implementation` or `repair`; cost remains in the task FinOps state.
- **Auxiliary**: `subsystem=session_titling`, `task_id=aux_session_titling_<session>`;
  cost in its own FinOps state, never charged to the engineering task.
- **Session**: sum of invocation records and all FinOps files; the ledger's
  cost fields must equal the aggregate of settled reservations.

## 6. Scope and limits

- The accepted desktop path is fully governed: engineering, repair, and session
  titling.
- Legacy conversation/background lanes (chat graph, summarizer, compaction,
  self-curation, planner helpers) are inventoried. They are refused in
  acceptance without a reservation; **outside acceptance they still lack FinOps
  coverage**. This is a documented remaining defect, not a claim of universal
  production coverage.
- No OS-level network sandbox; provider keys are scrubbed from test subprocesses
  (P0.6.7), not from the bridge process.
