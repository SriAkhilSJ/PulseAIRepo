# PHASE 11.4 REMAINING LIMITATIONS & ROADMAP

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.4 Change Impact Analysis  

---

## 1. IDENTIFIED LIMITATIONS & MITIGATIONS

1. **Dynamic Metaprogramming in Python (`getattr`, `eval`):** Dynamic function dispatch cannot always be discovered statically. The system records `HEURISTIC` provenance and `UNKNOWN` confidence rather than fabricating relationships.
2. **Cross-Language RPC Calls (Microservices):** Network calls across independent repositories are modeled at `APPLICATION` level with heuristic endpoint matching.
3. **Large Monorepos (>100,000 files):** Incremental hash invalidation prevents full rescans, but initial scan time is bounded by skipping build and dependency caches (`node_modules`, `.venv`, `dist`, `.git`).
