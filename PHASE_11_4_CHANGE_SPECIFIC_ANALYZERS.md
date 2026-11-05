# PHASE 11.4 CHANGE-SPECIFIC ANALYZERS REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.4 Change Impact Analysis  

---

## 1. DOMAIN-SPECIFIC EVALUATIONS

`ChangeSpecificAnalyzer` (`src/impact/change_analyzers.py`) provides specialized analysis across 7 categories:
1. **Functions:** Inspects callers, argument lists, return behavior, and auth criticality.
2. **Classes & Interfaces:** Inspects subclasses, interface implementations, and instantiations.
3. **APIs:** Inspects HTTP methods, route paths, endpoint consumers, and public contracts.
4. **Database & Models:** Evaluates tables, ORM models, migration requirements, and backup needs.
5. **Configuration:** Inspects environment variables, startup implications, and security sensitivity.
6. **Dependencies:** Analyzes external packages and repository-wide consuming modules.
7. **UI Components:** Evaluates shared components, parent views, and rendering hierarchy.
