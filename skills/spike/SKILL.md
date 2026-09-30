---
name: spike
description: "Throwaway experiments to validate an idea before build."
version: 1.1.0
author: Hermes Agent (adapted from gsd-build/get-shit-done), ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [spike, prototype, experiment, feasibility, throwaway, exploration, research, planning, mvp, proof-of-concept]
    related_skills: [grill-me, subagent-driven-development]
---

**Triggers:** spike, prototype, proof of concept, poc, feasibility, is this possible, is this even possible, quick experiment, try an idea, compare approaches, validate an idea

# Spike

Use when the user wants to **feel out an idea** before committing to a real build — validating feasibility, comparing approaches, or surfacing unknowns. Spikes are disposable by design. Throw them away once they've paid their debt.

Load when the user says "let me try this", "I want to see if X works", "spike this out", "before I commit to Y", "quick prototype of Z", "is this even possible?", "compare A vs B".

## When NOT to use

- The answer is knowable from docs or reading code — do research, don't build
- The work is the production path — plan and TDD instead
- The idea is already validated — jump straight to implementation

## Core method

```
decompose → research → build → verdict
    ↑__________iterate___________↓
```

### 1. Decompose

Break the idea into **2–5 independent feasibility questions**. One question = one spike. Present as a table:

| # | Spike | Validates (Given/When/Then) | Risk |
|---|-------|----------------------------|------|
| 001 | websocket-streaming | Given a WS connection, when the model streams tokens, then chunks arrive < 100ms | High |
| 002a | pdf-parse-pdfjs | Given a multi-page PDF, when parsed with pdfjs, then structured text is extractable | Medium |
| 002b | pdf-parse-camelot | Same question, competing approach (comparison spike) | Medium |

Good spike questions: specific feasibility with observable output. Bad: too broad, no observable output, "read the docs about X". **Order by risk — the spike most likely to kill the idea runs first.**

### 2. Align

Show the table. Ask: "Build all in this order, or adjust?" Let the user drop/reorder before code. Skip only if the user already specified exactly what to spike.

### 3. Research (per spike, before building)

Brief it (2–3 sentences), surface competing approaches if there's real choice, pick one and say why. Use `web_search` + `read_file` for docs; `run_terminal("pip show <pkg>")` to check what's installed.

### 4. Build

One standalone directory per spike, in the workspace:

```
spikes/
├── 001-websocket-streaming/   (README.md + main.py)
├── 002a-pdf-parse-pdfjs/      (README.md + parse.js)
└── 002b-pdf-parse-camelot/    (README.md + parse.py)
```

**Bias toward something the user can interact with:** a runnable CLI > a minimal HTML page > a one-endpoint server > a test with recognizable assertions. Hardcode everything — no build tools, Docker, env files, config systems.

**Depth over speed.** Never declare "it works" after one happy-path run. Test edge cases; follow surprising findings.

### 5. Verdict

Report per spike: **PROMISING / NOT PROMISING / INCONCLUSIVE**, evidence (numbers, timings, failure modes), and a recommendation ("websocket streaming holds at p95 40ms — proceed to build; camelot failed on scanned PDFs — drop 002b"). Then ASK: keep iterating, or throw the spikes away and start the real build (with TDD)?

## Invariants

- Spikes live under `spikes/` and are never wired into production code.
- Never claim a spike proves more than it measured.
- Throwaway means throwaway: no commits of spike code without the user asking.
