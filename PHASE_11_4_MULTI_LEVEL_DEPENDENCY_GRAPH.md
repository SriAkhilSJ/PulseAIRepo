# PHASE 11.4 MULTI-LEVEL DEPENDENCY GRAPH REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.4 Change Impact Analysis  

---

## 1. GRAPH LEVELS & REPRESENTATIONS

The `MultiLevelDependencyGraph` (`src/impact/graph.py`) models dependencies across 5 abstraction levels:

1. **`REPOSITORY`:** Packages, applications, microservices, and major subsystems.
2. **`MODULE`:** Source files, libraries, internal packages, and external third-party dependencies.
3. **`SYMBOL`:** Functions, methods, classes, interfaces, types, and constants.
4. **`APPLICATION`:** API endpoints (`app:api:METHOD:/path`), database entities (`app:db:table`), configuration variables (`app:config:VAR`), and background event handlers.
5. **`TEST`:** Unit tests, integration tests, contract suites, fixtures, and coverage artifacts.

---

## 2. RELATIONSHIP TYPES & EVIDENCE PROVENANCE

The graph connects nodes using 14 strictly typed relationships:
`IMPORTS`, `CALLS`, `INHERITS`, `IMPLEMENTS`, `INSTANTIATES`, `READS`, `WRITES`, `EXPOSES`, `DEPENDS_ON`, `CONFIGURES`, `TESTS`, `MIGRATES`, `SERIALIZES`, `DESERIALIZES`.

Each edge records:
- `evidence_source`: `STATIC`, `RUNTIME_OBSERVED`, `HEURISTIC`, `UNKNOWN`
- `confidence`: `VERIFIED`, `INFERRED`, `UNKNOWN`
- `weight`: Coupling strength (0.0 to 1.0)
- `is_runtime`: Distinguishes production runtime dependencies from test-only dependencies.
