# CrusorAI - Latest Handoff

**Handoff date:** 2026-11-10
**Branch:** `feat/prompt-cache-stabilization`
**HEAD:** `604605b2a02b3b1b6960f7959f4c122aeeed8bd4`
**Origin:** matches HEAD
**Current phase:** Product qualification: scope fidelity fixed; first live Velona
Electron coding task COMPLETED/VERIFIED; production readiness not claimed

> The prior handoff (Phase 3.2 closeout) is archived at
> `docs/handoffs/HISTORY/2026-11-09_phase-3.2-closeout.md`.
> This handoff records uncommitted working-tree work; HEAD is unchanged.

---

## 1. Where the project stands

- Production hardening phases 0–1.4 remain **WINDOWS SECURITY QUALIFIED**.
- Phase 2 r1/r2 remain `DESKTOP_PARTIAL` (light-theme and headed-GUI gaps).
- Phase 3.1/3.2 remain PASS (bounded).
- The Agent Runtime migration from `docs/ARCHITECTURE.md` §14 is implemented in
  the working tree:
  - **Increment 1:** LangGraph is the sole interactive owner; engineering is a
    delegated graph node; B-DESK-001 compaction exports repaired; graph direct
    mutations fail closed.
  - **Increment 2:** one context bundle, one model gateway, explicit tool
    side-effect policy, digest-bound approvals, broker-mediated graph writes.
  - **Increment 3:** one canonical `TurnReceipt`, one FinOps invocation ledger,
    precondition-bound approval tokens, B-DESK-006 fixed, direct bridge
    orchestrator route removed.
- Electron Agent pane now opens. The real UI was driven through chat,
  engineering diff approval + broker write + report, denial and cancellation
  (provider-free deterministic model). Remote debugging is on port **9222**.
  Full TurnReceipt field rendering and live providers remain open.
- **Product qualification:** two scope leaks were fixed (explicit `.md`
  requests were treated as SOURCE; “Do not create tests” became a TEST
  requirement). A live Velona Electron task created exactly `hello.md`,
  verified, one approval/mutation, one provider invocation (3013 in/38 out),
  ₹0.014704. Five bounded live calls total ₹0.092942. Evidence:
  `QUALIFICATION_REPORT.md`, `logs/live-e2e4/`.
- Nothing from these increments has been committed or pushed.

## 2. What changed (uncommitted)

Runtime:
- `src/runtime/turn_receipt.py` (new)
- `src/llm/gateway.py` (new), `src/llm/factory.py`
- `src/graphs/tool_policy.py` (new), `chat_graph.py`, `state.py`
- `src/context/context_engine.py`
- `src/orchestration/{orchestrator,model_adapter,approval_gateway,implementation_engine,models}.py`
- `src/workspace/{risk_policy,mutation_broker,approval_digest,approval_context}.py`
- `src/tools/file_tools.py`
- `src/bridge/__main__.py`
- `src/finops/invocation_context.py`
- `src/agents/sub_agent.py`

Desktop:
- `desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRendererService.ts`
- compiled `desktop/vscode/out/vs/workbench/contrib/crusorai/**`

Tests/evidence:
- new `test_canonical_runtime_increment3.py`; updated increment/wiring tests
- `bench-results/phase-3.3-canonical-runtime/{EVIDENCE,INCREMENT2_EVIDENCE,INCREMENT3_EVIDENCE}.md`
- probes/logs/screenshots under `.../logs/`

## 3. Verification (provider-free)

Run from repo root with an isolated `USERPROFILE` and
`MEMORY_NUDGE_INTERVAL=0`, `CRUSORAI_TEST_MODE=1`:

```powershell
# core runtime (Phase 3.1/3.2/11.6/compaction/bridge/Inc1/Inc2/Inc3)
.\.venv\Scripts\python.exe -m pytest src/tests/test_orchestrator_approval_integration.py `
  src/tests/test_contract_assignment_reliability.py `
  src/tests/test_phase_11_6_autonomous_execution.py `
  src/tests/test_eager_history_compaction.py `
  src/tests/test_bridge_protocol_v2.py `
  src/tests/test_bridge_orchestrator_protocol.py `
  src/tests/test_bridge_transport.py `
  src/tests/test_canonical_runtime_engineering_delegation.py `
  src/tests/test_canonical_runtime_increment2.py `
  src/tests/test_canonical_runtime_increment3.py -q

# security containment
.\.venv\Scripts\python.exe -m pytest src/tests/test_security_containment.py -q

# real bridge sidecar
.\.venv\Scripts\python.exe -m pytest src/tests/test_bridge.py -q
```

Recorded results (2026-11-10):
- core: **155 passed**
- security: **232 passed, 3 skipped**
- bridge sidecar: **38 passed, 1 pre-existing failure**
- eval/P0 batch: **49 passed, 5 pre-existing failures**
- restart replay: approve `COMPLETED`, deny `DENIED`, cancel `CANCELLED`; same
  receipt id after restart; workspace empty on deny/cancel
- stale-approval adversarial tests: pass

Pre-existing failures: three `test_autonomous_runtime_contract.py` cases
(fuse/system-message), P0.3 pre-canonical frame expectation, P0.4
`TurnCancelledError` uncertainty contradiction, bridge autotitler signature.

## 4. Runtime contracts

- `stream_agent(canonical_runtime=True)` is the only interactive lifecycle.
- `EngineeringTaskRequest` → `DeliveryContract`; context bundle is the graph's
  bounded `ContextEngine` output.
- Approval token binds task/session/turn/workspace/path/operation/content
  digest/workspace precondition/expiry and is single-use. The broker recomputes
  digest + precondition before applying.
- `TurnReceipt` is persisted in the checkpoint and emitted as `receipt` on
  `turn_done`; statuses: `COMPLETED|FAILED|CANCELLED|DENIED|PARTIAL|NOT_VERIFIED`.
- One FinOps JSONL per workspace with attempts, tokens, latency, known/unknown
  cost and invocation/task/session/daily reports.

## 5. Working tree / preservation

- Status at handoff: **239 entries**, preserved; external snapshot at
  `C:\Users\Administrator\AppData\Local\Temp\opencode\crusor-snapshot-20261110`.
- Pre-existing user work is preserved: apps, diagnostics, benches, generated
  modules, uncommitted broker wiring.
- `src/tools/file_tools.py` at HEAD still bypasses the broker; the working copy
  is fixed and must not be described as shipped.
- `docs/` itself is untracked.
- Do not clean/reset/revert/stash. No commit or push was authorized.

## 6. Open risks and next actions

1. **Desktop completeness:** render every canonical `TurnReceipt` field in the
   pane, add focused workbench/extension activation tests, and run a full
   headed qualification. The provider-free Agent flow itself passed.
2. **Live provider acceptance/cost:** requires explicit paid-call authorization;
   unknown costs must stay unknown.
3. **Full-suite baseline:** run and classify all failures (B-006).
4. **Working-tree disposition:** commit the runtime + desktop repair + memory
   layer, or keep explicitly uncommitted.
5. **24-hour cloud readiness:** no deployment/uptime/recovery/monitoring evidence.
6. Do not claim Agent Core production-ready from these increments alone.
7. Live output quality: `hello.md` contained emoji mojibake; investigate
   provider/encoding before quality claims.
8. Invocation-id consistency: the last live call had different gateway/ledger
   ids; the adapter now adopts the gateway id, but this fix was not
   re-verified live because the 5-call cap was reached.

## 7. Landmines

- The bridge route is now single-owner; do not reintroduce a mode/env-selected
  orchestrator path.
- `_GRAPH_MUTATION_BLOCKED` still disables shell, opaque MCP/host calls and
  unproven writes; do not enable them without broker/diff/precondition parity.
- Approval persistence: terminal frames can be emitted while the graph is live;
  only explicit success/denial paths persist receipts (`persist=False` for the
  generic terminal wrapper).
- The desktop workbench compile takes ~5 minutes; `out/` artifacts are tracked.
