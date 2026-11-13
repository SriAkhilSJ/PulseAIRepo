# Crusor Agent Core — Engineering Qualification Baseline (Phase 0–1)

**Date:** 2026-11-12
**Branch / HEAD:** `feat/prompt-cache-stabilization` · `fb5bd528b40933346c4004a1490154683dc0d40e` (unchanged)
**Working tree:** 247 entries, 173 untracked, **0 deletions**. Nothing reset, cleaned or checked out.
**Status of this document:** baseline + audit + plan. Paid qualification (Phase 5) has **not** run; it requires a new spending cap.

---

## 1. Architecture map (verified against source, not docs)

| Stage | Implementation | State |
|---|---|---|
| Request ingestion | Electron panel → `desktop/.../crusorAIRendererService.ts` → bridge NDJSON | **Implemented, tested** (provider-free Electron) |
| Bridge turn owner | `src/bridge/__main__.py` `_run_turn` | **Implemented, tested**; one terminal frame per turn |
| LangGraph lifecycle | `src/graphs/chat_graph.py` `stream_agent` / `ai_node` | **Implemented, tested**; canonical owner |
| Model gateway | `src/llm/gateway.py` `invoke_model` | **Implemented, tested** (unit + loopback SSE); real-provider **unproven** |
| Provider stack | `src/llm/factory.py` `get_llm` → `ReasoningAwareOpenAI` → `RetryLLMProxy` | **Implemented**; custom/velona path configured |
| Context management | `src/context/*` (ContextEngine, windows, compaction) | **Implemented**; window probe verified (`1,048,576` for glm-5.3-flash) |
| Engineering adapter | `src/orchestration/model_adapter.py` `_dispatch_code_prompt` | **Implemented**; single paid dispatch, pricing fail-closed |
| Engineering orchestrator | `src/orchestration/orchestrator.py` `run_task_request` | **Implemented**; contract → plan → schedule → verify → receipt |
| Tool registry | `src/tools/*` (file, terminal, code_exec, plan, clarify, MCP…) | **Implemented for chat**; **not bound on the engineering path** |
| Mutation broker | `src/workspace/mutation_broker.py` | **Implemented, tested**; the adapter routes mutations through it |
| Approval gateway | `src/orchestration/approval_gateway.py` + bridge queue | **Implemented, enforced, tested** (deny/cancel paths) |
| Execution environment | AppContainer/Job Object (`src/security/*`) | **Implemented**; fallback mode documented, network bound is loopback-only |
| Verification | `src/verification/*`, `IndependentVerificationEngine` | **Implemented, tested** (evidence-based verdicts) |
| TurnReceipt | `src/runtime/turn_receipt.py` | **Implemented, tested** |
| FinOps ledger | `src/finops/{invocation_context,governed,pricing_registry}.py` + governor | **Implemented, tested**; reserve→settle verified |
| Event journal | `src/runtime/event_journal.py` (hash-chained, terminal rows) | **Implemented, tested** |
| Checkpoints / replay | LangGraph checkpointer + `session_messages` + journal | **Implemented, tested** (provider-free) |

## 2. The decisive gap: engineering is generation, not tool use

`rg` over `orchestrator.py` and `model_adapter.py` finds **no** `bind_tools`, no tool registry, no tool-call loop. The only tool-adjacent call is `self.authorizer.authorize_tool_call` before a mutation (`model_adapter.py:843`). The chat path binds tools (`chat_graph.py:2322,2675,2786`), the engineering path does not.

Consequence: engineering can write files and run a verification pass, but it cannot *list, read, search, run commands or read outputs* as part of its own reasoning. That is the root cause of "file generation instead of engineering". It also explains why the UI needed cards at all: there are no tool events to render on this path.

## 3. Other verified weaknesses

1. **Contract gate could reject valid phrasing** (fixed in P0): `parse_prompt_contract` now accepts name-first forms.
2. **Ledger latency was null** — fixed in this pass: `_dispatch_code_prompt` now records measured `latency_ms` from the dispatch gate to the response/failure.
3. **Turn identity mismatch** (`turn_turn-…` in ledger `task_id`) — `chat_graph.py:5389` builds `task_id = f"turn_{turn_id}"`; the ledger stores it verbatim. Needs a reconciliation test before renaming (renaming changes task-scoped storage paths, so it must not break resume).
4. **RBAC is not enforced on the live tool path** (documented limitation): `tool_authorizer` exists, but the engineering path only authorizes the mutation, not each capability.
5. **Real-provider execution is unproven**: the only live run spent ₹0.143 on two calls and completed no task (contract gate, then stopped).
6. **Retries are disabled for engineering** by design (`_max_attempts = 1`); bounded generation recoveries are separate paid dispatches.
7. **Full-suite baseline is not clean** (pre-existing card-type drift + one stale cancellation test); this is tracked, not hidden.

## 4. Change made in this pass

| File | Change | Test |
|---|---|---|
| `src/orchestration/model_adapter.py` | `_ledger_record` writes measured `latency_ms` (dispatch gate → response/failure) instead of null | `test_model_adapter_qualification` + `test_invocation_reconciliation`: **18 passed** |

No architecture change, no tool-loop change, no frontend change.

## 5. Phase 2 proposal (not implemented — needs the paid qualification first)

A bounded tool loop requires: (a) binding the existing LangChain tool set to the engineering model, (b) executing each tool through the existing broker/terminal sandbox, (c) feeding bounded structured results back, (d) capping steps/tokens, (e) keeping `EngineeringExecutionOrchestrator` as the owner. That is a **design-and-build phase**, not a switch; it should not be attempted blind before the current generation path is proven against a real provider.

## 6. Phase 5 plan and cost (requires authorization)

Three bounded tasks in a disposable fixture (mini_math), through the real Electron app → bridge → graph → orchestrator → gateway → configured provider:

| Test | Scope | Expected calls |
|---|---|---|
| A | add `divide()` + tests + README, run suite | 4–8 |
| B | multi-file `clamp()` + imports + tests | 5–10 |
| C | controlled `multiply()` regression, diagnose, repair, rerun | 3–8 (+ repairs) |

Estimate: **20–35 requests**, ~350–500k input, ~25–40k output.
At verified pricing (glm-5.3-flash: $0.05/M in, $0.20/M out, USD→INR 86): **≈ ₹2–4 central**, **≈ ₹10 bounded worst case** with retries/recoveries.

The previous ₹50 authorization was closed after the failed run (₹0.143 spent). A new cap must be confirmed before the first paid call.

## 7. Git status

```
HEAD:        fb5bd528 (no commit/reset/clean/checkout)
dirty:       247 entries; 173 untracked; 0 deletions
changed now: src/orchestration/model_adapter.py (latency_ms)
             CRUSOR_AGENT_CORE_ENGINEERING_QUALIFICATION.md (this file)
```
