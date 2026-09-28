---
name: code-wiki
description: "Generate wiki docs + Mermaid diagrams for any codebase."
version: 0.2.0
author: Teknium (teknium1), Hermes Agent, ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [documentation, mermaid, architecture, diagrams, wiki, code-analysis, onboarding]
    related_skills: [codebase-inspection, codebase-map]
---

**Triggers:** wiki, document this codebase, architecture diagram, mermaid, generate docs, codebase documentation, onboarding docs, explain the architecture

# Code Wiki

Generate a wiki for any codebase — overview, architecture, per-module deep-dives, Mermaid class and sequence diagrams. Uses only existing Crusor tools (`run_terminal`, `read_file`, `search_files`, `write_file`); no Docker, no external services, no extra dependencies.

Produces **reference documentation** (what/how) — not strategic narrative (why), not single-function explanations (just answer inline).

## When to Use

- "Document this codebase", "generate a wiki", "make architecture diagrams"
- Onboarding to an unfamiliar repo as structured reference
- A stable markdown+Mermaid artifact is wanted that renders on GitHub

Do NOT use for: single-file/function docs (answer directly), repos the user is actively reshaping this session (answer as questions come).

## Quick Reference

| Step | Action |
|---|---|
| 1 | Resolve target — workspace root, given path, or `git clone --depth 50 <url>` to a temp dir |
| 2 | Scan structure — `ls`, `find -maxdepth 3`, manifest files, README |
| 3 | Pick 8–10 modules to document |
| 4 | Write `README.md` (overview + module map) |
| 5 | Write `architecture.md` with Mermaid flowchart |
| 6 | Write per-module docs in `modules/` |
| 7 | Write `diagrams/class-diagram.md` (Mermaid classDiagram) |
| 8 | Write `diagrams/sequences.md` (2–4 key workflow sequenceDiagrams) |
| 9 | Write `getting-started.md` (+ `api.md` if applicable) |
| 10 | Report paths to the user |

Default output: `~/.crusorai/wikis/<repo-name>/`. Write INTO the repo (`docs/wiki/`) only when the user explicitly requests it.

## Procedure

```bash
REPO_SHA=$(git rev-parse HEAD 2>/dev/null || echo "uncommitted")
OUTPUT_DIR="$HOME/.crusorai/wikis/$(basename $PWD)"
mkdir -p "$OUTPUT_DIR/modules" "$OUTPUT_DIR/diagrams"
```

Scan with `run_terminal` (`find . -maxdepth 3 -type f | grep -v node_modules | head -80`), read READMEs and entrypoints with `read_file`, map structure with `search_files`. Record the commit SHA in the wiki header — docs rot, the SHA dates them.

## Quality Bars

- **Modules are mental units** (runtime, bridge, ui), not folder dumps; say what each module is FOR in one sentence before any detail.
- **Mermaid diagrams must render**: keep node labels quoted, no raw `-->` inside labels, one diagram per concern. If a diagram is >15 nodes, split it.
- Sequence diagrams follow REAL call paths you verified in code — file:line references in the doc body, not in the diagram.
- Every claim about behavior cites a file you actually read this session.
- Prefer tables for inventories (endpoints, commands, config keys); prose only for relationships.

## Invariants

- Never modify source code while generating a wiki (read-only task, `write_file` only into the output dir).
- One session = one repo; if the target changes, restart the wiki.
- Report output paths at the end; offer `getting-started.md` as the entry point.
