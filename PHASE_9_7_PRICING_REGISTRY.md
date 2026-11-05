# PHASE 9.7 PROVIDER PRICING REGISTRY DOCUMENTATION

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Module:** `src/finops/pricing_registry.py`  

## 1. DESIGN SPECIFICATION

The `ModelPricingRegistry` provides a unified, audited price book across all supported LLM providers and models:
1. **Configurable Rate Cards:** Input, output, cached input, and reasoning token rates per 1,000,000 tokens.
2. **Verification Provenance:** Every rate entry is stamped with a `VerificationStatus`:
   - `VERIFIED`: Official provider documentation or live catalog API.
   - `ESTIMATED`: Computed via family tier baseline.
   - `UNVERIFIED`: Preliminary or user-provided rate card.
   - `UNKNOWN`: Unrated model; costs are marked as honestly unknown (never fabricated).
3. **Multi-Currency Normalization:** Native support for USD and INR, with canonical conversion formulas:
   $$\text{INR} = \text{USD} \times 86.0 \times 1.005 \times 1.07$$

## 2. STANDARD PRICE BOOK CATALOG (SAMPLE)

| Provider | Model Identifier | Input / 1M | Output / 1M | Cached / 1M | Reasoning / 1M | Currency | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **OpenAI** | `gpt-4o` | $2.50 | $10.00 | $1.25 | $10.00 | USD | `VERIFIED` |
| **OpenAI** | `gpt-4o-mini` | $0.15 | $0.60 | $0.075 | $0.60 | USD | `VERIFIED` |
| **OpenAI** | `o1` | $15.00 | $60.00 | $7.50 | $60.00 | USD | `VERIFIED` |
| **OpenAI** | `o3-mini` | $1.10 | $4.40 | $0.55 | $4.40 | USD | `VERIFIED` |
| **Anthropic** | `claude-3-5-sonnet` | $3.00 | $15.00 | $0.30 | $15.00 | USD | `VERIFIED` |
| **Anthropic** | `claude-3-5-haiku` | $0.80 | $4.00 | $0.08 | $4.00 | USD | `VERIFIED` |
| **Anthropic** | `claude-3-opus` | $15.00 | $75.00 | $1.50 | $75.00 | USD | `VERIFIED` |
| **Google** | `gemini-1.5-pro` | $1.25 | $5.00 | $0.3125 | N/A | USD | `VERIFIED` |
| **Google** | `gemini-1.5-flash` | $0.075 | $0.30 | $0.01875 | N/A | USD | `VERIFIED` |
| **DeepSeek** | `deepseek-chat` | $0.14 | $0.28 | $0.014 | N/A | USD | `VERIFIED` |
| **DeepSeek** | `deepseek-reasoner`| $0.55 | $2.19 | $0.14 | $2.19 | USD | `VERIFIED` |
| **Velona** | `velona-pro` | ₹45.00 | ₹180.00 | ₹15.00 | N/A | INR | `VERIFIED` |
| **Velona** | `velona-flash` | ₹4.50 | ₹18.00 | ₹1.50 | N/A | INR | `VERIFIED` |
