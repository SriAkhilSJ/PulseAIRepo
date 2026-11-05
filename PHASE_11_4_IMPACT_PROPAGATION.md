# PHASE 11.4 IMPACT PROPAGATION ENGINE REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.4 Change Impact Analysis  

---

## 1. DIRECTION-AWARE REVERSE TRAVERSAL

`ImpactPropagator` (`src/impact/propagator.py`) computes downstream consequences:
- Traversal direction: Reverse queries (`get_dependents`) — discovering who depends on the changed component.
- Coupling weights: `INHERITS` (1.0), `CALLS` (0.9), `EXPOSES` (0.85), `IMPORTS` (0.5), `TESTS` (0.4).
- Decay factor: `0.85 ** (depth + 1)` dampens distant transitive effects.

---

## 2. BOUNDARY RULES

- **Public vs. Private:** Modifying private symbols (starting with `_`) limits propagation unless explicit external callers exist.
- **Runtime vs. Test:** Test nodes are recorded as affected tests, but traversal **never propagates from test nodes back into production code**.
- **Cycle Prevention:** A strict visited set prevents infinite loops in recursive or circular dependencies.
