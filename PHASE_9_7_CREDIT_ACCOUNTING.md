# PHASE 9.7 CREDIT ACCOUNTING INTEGRATION REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Module:** `src/finops/credits.py`  

## 1. DIAMOND & CREDIT LEDGER

1. **External System Alignment:** Aligns with Crusor's user subscription boundary (`https://www.crusor.in/login`).
2. **Standard Conversion Rate:** 1 USD = 1,000 Diamonds ($0.001 per Diamond).
3. **Transactional Operations:**
   - `grant_credits`: Top-ups and subscription allocations.
   - `debit_usage`: Atomic deduction upon model completion.
   - `refund_credits`: Automatic reversal for aborted or failed turns.
4. **Idempotency Protection:** All credit mutations use idempotency keys preventing duplicate debits.
