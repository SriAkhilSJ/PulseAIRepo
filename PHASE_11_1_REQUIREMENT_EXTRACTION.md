# PHASE 11.1 REQUIREMENT EXTRACTION ENGINE

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.1 Requirement Understanding & Discovery  

---

## 1. OVERVIEW

The Requirement Extraction Engine (`src/intelligence/requirement_extractor.py`) parses natural language prompts across technical, nontechnical, and hybrid communication styles.

### Core Capabilities:
- **Explicit Technology & Architecture Parsing:** Recognizes 25+ frontend/backend frameworks, databases, and architectural patterns (Modular Monolith, Microservices, Event-Driven, Serverless).
- **Communication Style Classification:** Identifies whether the prompt is `TECHNICAL`, `NON_TECHNICAL`, or `HYBRID`.
- **Domain Pattern Recognition:** Detects business domains (e.g. `ecommerce`, `saas`, `api_service`) and derives baseline functional requirements, default roles, and key workflows.
- **Explicit vs Inferred Separation:** Every extracted item explicitly cites its `evidence_source` (e.g. `User prompt: "use PostgreSQL"` vs `Inferred from domain "ecommerce"`).
