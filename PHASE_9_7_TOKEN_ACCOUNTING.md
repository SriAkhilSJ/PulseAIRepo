# PHASE 9.7 TOKEN ACCOUNTING IMPLEMENTATION REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Module:** `src/finops/accounting.py`  

## 1. ARCHITECTURE

The `TokenAccountingEngine` implements an append-only, idempotent ledger for every model interaction:
1. **Idempotency Guarantee:** Every operation computes a deterministic SHA-256 event ID:
   $$\text{event\_id} = \text{SHA256}(\text{session\_id} + ":" + \text{request\_id} + ":" + \text{retry\_count})$$
   Duplicate submissions return the existing `UsageRecord` immediately without mutating balances or counters.
2. **Streaming Deduplication:** `track_stream_chunk` aggregates partial chunk character lengths during in-flight streaming. Only when `is_final=True` is received does the engine emit a single consolidated `UsageRecord`.
3. **Retry Isolation:** Retries are metered as distinct attempts using the `retry_count` parameter, allowing operators to measure the exact cost of failed vs successful retry attempts.
