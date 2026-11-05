# PHASE 11.1 REQUIREMENT CLASSIFICATION SYSTEM

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.1 Requirement Understanding & Discovery  

---

## 1. THE FOUR TAXONOMICAL CLASSIFICATIONS

Every extracted requirement is classified into one of four mutually exclusive categories:

1. **`EXPLICIT`:** Directly stated by the user (e.g., "use FastAPI and PostgreSQL", "modular monolith"). These are immutable constraints.
2. **`DISCOVERABLE`:** Established through repository inspection, existing manifests, package dependencies, or database schemas via Phase 11.0 `ProjectKnowledge`.
3. **`REASONABLE_DEFAULT`:** Standard, safe software engineering choices (e.g., UUID primary keys, bcrypt password hashing, pagination, environment variable secret isolation).
4. **`USER_DECISION_REQUIRED`:** High-impact business decisions, essential ambiguities, or irreversible choices that materially alter the outcome (e.g. single-vendor store vs multi-vendor marketplace).
