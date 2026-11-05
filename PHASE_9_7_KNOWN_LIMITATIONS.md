# PHASE 9.7 KNOWN LIMITATIONS & UNRESOLVED RISKS

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 9.7 FinOps  

1. **External Provider Pricing Latency:**
   Dynamic pricing catalog fetching relies on provider `/models` endpoints; network partitions fall back to local cached rates.
2. **Forex Rate Volatility:**
   Standard USD to INR rate is configured via `CRUSORAI_USD_INR` (default 86.0); live forex API updates require an external exchange-rate provider.
3. **Local Models Zero-Cost Accounting:**
   Local Ollama / vLLM models report $0.00 cost but consume host compute (CPU/GPU); future phases could incorporate kilowatt-hour energy attribution.
