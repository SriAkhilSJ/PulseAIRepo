# P0.6.9 — Provider Invocation Inventory

Inspected at `a2e654c6` (local == origin). Every site that can reach a model is
listed with its real accounting state. "Governed" means a FinOps reservation is
created before the wire call, authentic usage is captured and the reservation is
settled; the invocation ledger records attribution.

## 1. Invocation paths

| # | Subsystem | Entry point | Provider / model | Type | Accounting before P0.6.9 | P0.6.9 state |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Engineering implementation | `src/orchestration/model_adapter.py::_dispatch_code_prompt` | task provider/model (`z-ai/glm-5.3-flash`) | task | reserve → invoke → usage → cost → commit (task governor) | **GOVERNED** + invocation record + reservation scope |
| 2 | Engineering repair | same method (`purpose=repair_*`) | task model | task | same as #1 | **GOVERNED** + record (`operation_type=repair`) |
| 3 | Session auto-title | `src/bridge/__main__.py::_maybe_autotitle_session` → `src/finops/governed.py` | auxiliary (`cheap` → `qwen/qwen3.7-flash`) | auxiliary | `RetryLLMProxy` counted by the acceptance guard only; **no reservation** (P0.6.8 failure) | **GOVERNED** (session-scoped governor, 1 attempt, ledger `subsystem=session_titling`) |
| 4 | Desktop chat/agent graph (legacy `CRUSORAI_ORCHESTRATOR_ENGINE=legacy` or chat mode) | `src/graphs/chat_graph.py` `get_llm` + `ai_node`/`call_llm.invoke` (2268, 2272, 2630, 2741, 4620, 5093, 7644) | task model / auxiliary summarizer | conversation | proxy retries; no FinOps reservation | **NOT GOVERNED**; fails closed in acceptance via the proxy scope check; not used by the orchestrator desktop path |
| 5 | Conversation summarizer | `src/context/summarizer.py:353` | auxiliary LLM | background | none | **NOT GOVERNED**; fails closed in acceptance; normal chat only |
| 6 | Context compaction | `src/context/compaction.py:432,777` | task/aux LLM | background | none | **NOT GOVERNED**; fails closed in acceptance |
| 7 | Self-curation | `src/context/self_curation.py:152,161` | auxiliary LLM | background | none | **NOT GOVERNED**; fails closed in acceptance |
| 8 | Agent planner helpers | `src/agents/planner.py:177,240,345,453` | task model | planning | none | **NOT GOVERNED**; management lane outside orchestrator |
| 9 | One-shot prompt runner | `src/prompts/oneshot.py:237` | auxiliary LLM | auxiliary | none | **NOT GOVERNED**; bounded invoke |
| 10 | Inline completions | `src/tools/inline_completions.py:190` | task model | UI assist | none | **NOT GOVERNED**; user-triggered tool |
| 11 | Basic graph demo | `src/graphs/basic_graph.py:26,32` | task model | demo | none | **NOT GOVERNED**; not production |
| 12 | Tool test harness | `src/tool_test.py:8,15` | task model | developer tool | none | **NOT GOVERNED**; not production |
| 13 | Embeddings | `src/llm/factory.py::EmbeddingFactory` | local SentenceTransformer by default | background | n/a (local; no provider bill) | local-only default; provider embeddings not configured |
| 14 | Retry/failover | `src/llm/factory.py::RetryLLMProxy.invoke` | wrapper around every client | transport | proxy claims per physical request; acceptance clamps to 1 | task/auxiliary callers pin 1 attempt; legacy paths clamp only in acceptance |

## 2. Physical request boundary

`RetryLLMProxy.invoke` is the single point every LangChain client passes
through. P0.6.9 adds the financial boundary there:

```python
from src.finops.invocation_context import assert_governed_for_acceptance
assert_governed_for_acceptance()
```

In acceptance mode a request with no reservation scope raises
`UnaccountedProviderCall` **before** request preparation. Task and auxiliary
calls set a scope around the actual `invoke`, so a claim without a reservation
is structurally impossible on the accepted path.

## 3. Accounting primitives reused (no second financial system)

- `OrchestrationFinOpsGovernor` (reserve / mark_in_flight / commit /
  mark_uncertain / release) and the canonical `BudgetGovernor`.
- `PricingRegistry` verified pricing; unknown pricing fails closed.
- `estimate_prompt_token_upper_bound` + `calculate_max_request_cost`
  (conservative maximum).
- `extract_provider_token_usage` (authentic receipts only).
- SQLite (`sessions.db`) and per-task JSON FinOps state remain authoritative.
- New `provider_invocations.jsonl` is an **attribution ledger** whose records
  reference the reservation/settlement ids; it does not replace cost truth.

## 4. Risks and controls

| Risk | Control |
| --- | --- |
| Auxiliary call unaccounted | Governed gateway (reserve → settle) + ledger + session report |
| Provider call without reservation in acceptance | Proxy scope check fails closed before wire |
| Retry multiplies a single reservation | Task/auxiliary clients pinned to 1 attempt; acceptance clamps every proxy |
| Unknown model pricing | `AuxiliaryAccountingError` / `UnknownModelPricingError`; no dispatch |
| Missing usage receipt | Reservation retained as uncertain; recorded; never free |
| Double settle | Governor idempotency by reservation id (P0.6.6) |
| Legacy background lanes (summarizer, compaction, self-curation, chat graph) | Fails closed in acceptance; **outside acceptance they still lack FinOps reservations** — documented remaining defect |

## 5. Inventory conclusion

The **desktop orchestrator acceptance path** (engineering + repair + automatic
session titling) is fully governed and instrumented. Legacy/management lanes
that remain on the LangChain chat graph are inventoried, are blocked from
executing inside an acceptance run without a reservation, and still require
their own accounting lane for full production coverage. That gap is stated, not
hidden.
