# PHASE 11.5 PERSISTENCE & OBSERVABILITY REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Verdict:** `REGRESSION PREVENTION VERIFIED`  

---

## 1. ISOLATED PERSISTENCE LAYOUT

All regression artifacts are isolated per tenant and workspace under:
`.crusorai/tenants/{tenant_id}/regression/`
- `baselines/baseline_{task_id}.json`
- `reports/report_{task_id}.json`
- `flaky_registry.json`

---

## 2. SECRET REDACTION

Before persisting any regression report or diagnostic dump to disk, `RegressionPersistence` (`src/regression/persistence.py`) passes all data through regex-based credential scrubbers:
- `sk-[a-zA-Z0-9]{20,}` (OpenAI / Anthropic API keys)
- `ghp_[a-zA-Z0-9]{20,}` (GitHub personal access tokens)
- `AIza[0-9A-Za-z-_]{35}` (Google API keys)
- Password and bearer token key-value pairs

Redacted fields are replaced with `[REDACTED_API_KEY]` or `[REDACTED_SECRET]`.
