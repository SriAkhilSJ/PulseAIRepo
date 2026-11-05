# PHASE 11.1 INTELLIGENT CLARIFICATION ENGINE

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.1 Requirement Understanding & Discovery  

---

## 1. OVERVIEW & QUESTION POLICIES

The Clarification Engine (`src/intelligence/clarification.py`) asks questions only when a decision materially impacts the software outcome.

### Core Principles:
1. **Material Impact Only:** Questions must explain *why* the decision matters.
2. **Unnecessary Question Suppression:** Never asks micro-implementation trivia (e.g., "Should I use functions?", "Should I create components?", "Should I use a service layer?").
3. **Repository Grounding:** If repository inspection reveals that FastAPI or PostgreSQL is already used, the system never asks the user what framework or database to use.
4. **Safe Defaults & Skip:** Every clarification question includes a `default_choice`, allowing non-blocking progress if the user does not respond.
5. **Memory & Deduplication:** Answers are cached in persistent decision history and never asked repeatedly.
