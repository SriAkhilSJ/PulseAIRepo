# PHASE 9.7 EXISTING-VERSUS-MISSING CAPABILITY MATRIX

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 9.7 FinOps  

| Capability Domain | Existing Implementation | Identified Deficiencies (Pre-9.7) | Phase 9.7 Delivered Solution | Verification Scenario |
| :--- | :--- | :--- | :--- | :--- |
| **Price Book Metadata** | `telemetry/pricing.py` | Missing verification flags; heuristic fallback could misrepresent estimated costs as exact. | Configurable `ModelPricingMetadata` with explicit `VerificationStatus` (`VERIFIED`, `ESTIMATED`, `UNKNOWN`). | `SCENARIO-01`, `SCENARIO-04` |
| **Forex & Multi-Currency** | House USD->INR multiplier (`86.0 * 1.005 * 1.07`) | Hardcoded in `cost_governance.py`; no dynamic currency normalization. | Centralized bidirectional `usd_to_inr` and `inr_to_usd` with micro-currency quantization (`0.000001`). | `SCENARIO-02` |
| **Cached & Reasoning Rates** | Rudimentary cache token tracking in `token_tracker.py` | No differentiated pricing for cached reads vs reasoning token volumes. | First-class `cached_input_price_per_1m` and `reasoning_price_per_1m` rate card evaluation. | `SCENARIO-03` |
| **Provider Receipt Precedence** | Overridden by local estimate in some paths | Lacked explicit priority for provider-reported usage receipts. | Provider-reported exact costs override local estimation as absolute ground truth. | `SCENARIO-05` |
| **Accounting Idempotency** | Event deduplication in `FinancialStore` | No memory-tier deduplication; retries could inflate token tallies during in-flight retries. | Deterministic SHA-256 event keys in `TokenAccountingEngine`; duplicate calls return cached record. | `SCENARIO-06` |
| **Stream Chunk Deduplication** | Chunks passed directly to stdout | Risk of counting each chunk as an independent call. | `track_stream_chunk` accumulates characters; emits single usage event on `is_final=True`. | `SCENARIO-07` |
| **Retry Accounting** | Retries treated as independent turns | Distorted cost attribution when multiple retries occurred. | Explicit `retry_count` attribute tracking failed vs recovered attempts without double-counting. | `SCENARIO-08` |
| **Multi-Level Attribution** | Session-only spend | No aggregation by workspace, project, or task. | `CostAttributionEngine`: multi-level slices by task, workspace, project, provider, and model. | `SCENARIO-09` |
| **Time-Bucket Aggregations** | Monthly-only JSONL files (`calls-YYYY-MM.jsonl`) | No daily or hourly spend trend analysis. | `attribute_by_time_bucket`: daily, hourly, and monthly calendar bucket aggregations. | `SCENARIO-10` |
| **Cost Optimization Routing** | Static routing | Always dispatched configured model regardless of task triviality. | `IntelligentModelRouter`: routes simple tasks to cheap tier (`gpt-4o-mini`, `haiku`, `flash`). | `SCENARIO-13` |
| **User Pin Protection** | Pinned model could be overridden | Risk of silent downgrade or unexpected model swap. | Absolute user-pin inviolability: router NEVER overrides explicit user preference. | `SCENARIO-14` |
| **Budget Concurrency** | Global thread lock in `CostGovernor` | Race condition between multiple threads reserving simultaneous budget slots. | `BudgetGovernor`: atomic reservation ledger with hard ceiling and remaining headroom checks. | `SCENARIO-15`, `SCENARIO-16` |
| **Early Warning Watermark** | No warning until limit hit | Sudden execution halt with no prior notification. | 80% watermark warning threshold triggers proactive advisory telemetry. | `SCENARIO-17` |
| **Context Token Pruning** | SmartCompressor | Mutation payloads in tool history repeatedly consumed input tokens. | `ContextCostOptimizer`: redacts duplicate blocks and compresses historical file mutation args. | `SCENARIO-18` |
| **Credit Ledger & Reversals** | External link only | No in-IDE ledger for credit consumption or crash refunds. | `CreditAccountingEngine`: atomic debit (1 USD = 1000 Diamonds) and refund reversal handling. | `SCENARIO-19` |
| **Telemetry & Observability** | Plain text logs | Sensitive API keys or tokens could leak in spend logs. | `FinOpsObservabilityTracer`: distributed tracing + zero-leak `SecretRedactor` sanitization. | `SCENARIO-20` |
