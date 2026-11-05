# PHASE 11.0 REPOSITORY DISCOVERY CAPABILITIES

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Module:** `src/intelligence/discovery.py`  

---

## 1. CAPABILITIES
- **Language Profiling:** Identifies all source languages with file counts, byte totals, and percentages.
- **Manifest Extraction:** Parses `package.json`, `pyproject.toml`, `requirements.txt`, `Cargo.toml`, etc.
- **Framework Discovery:** Identifies backend (FastAPI, Flask, Django, Express), frontend (React, Next.js, Vue), desktop (Electron, Tauri), testing (pytest, vitest, jest), and AI agent (LangGraph, LangChain) frameworks.
- **Entry-Point Identification:** Detects Python main scripts (`main.py`, `app.py`, `server.py`, `if __name__ == '__main__':`) and JS/TS entrypoints (`index.ts`, `main.ts`).
- **Build / Test Commands:** Automatically extracts commands from manifest script sections.
- **API Endpoints:** Discovers HTTP routes from FastAPI/Flask decorators.
- **Zero-Leak Environment Variable Discovery:** Scans code and `.env.example` for variable names only; never reads or stores `.env` secret values.
