---
name: ast-grep
description: "AST-aware structural code search and rewrite via ast-grep."
version: 1.1.0
author: Yeongyu Kim (code-yeongyu), adapted by Hermes Agent, ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ast, codemod, refactoring, structural-search, code-search, rewrite, tree-sitter]
    related_skills: [simplify-code, systematic-debugging]
---

**Triggers:** ast-grep, ast grep, codemod, structural search, structural replace, rewrite all, rewrite every, find all functions, every call site, code shape, sg run

# ast-grep

`ast-grep` (binary `sg`; on Linux prefer `ast-grep` — `sg` collides with `setgroups`) is an **AST-aware search and rewrite tool** across ~25 languages. It parses your pattern as code and matches structurally. Right tool whenever the question depends on **code shape**, not text bytes. Install: `run_terminal("npm i -g @ast-grep/cli")` or `cargo install ast-grep` / `pip install ast-grep-py`. Check with `sg --version`.

## When to use (vs search_files)

- "Find every function that takes a `Request` parameter." → ast-grep
- "Rewrite every `console.log(x)` to `logger.info(x)`." → ast-grep
- "Migrate `Optional[X]` to `X | None`." / "Strip every `as any`." → ast-grep
- String contents, comments, file names, cross-language regex → `search_files` / `rg`

Ask: "does the answer depend on the syntax tree, or just the file's bytes?"

## Three things to internalize

### 1. ast-grep is NOT regex

Wildcards are `$VAR` (one AST node) and `$$$` (zero or more nodes). Regex syntax fails silently: `foo|bar`, `.*foo`, `\w+`, `[a-z]` are NOT patterns — run two searches, use `$VAR`, or switch to search_files.

### 2. Patterns must be valid code

`def $FN($$$):` fails (trailing `:` incomplete) → `def $FN($$$): $$$` with a body or `def $FN($$$)` for signature matching. `function $NAME` fails → `function $NAME($$$) { $$$ }`.

### 3. `--update-all` and `--json` are mutually exclusive (silently)

To preview AND apply, run two passes:

```bash
sg run -p 'PATTERN' -r 'REWRITE' --json=compact .   # pass 1: preview
sg run -p 'PATTERN' -r 'REWRITE' --update-all .     # pass 2: apply
```

## Core commands (through `run_terminal`, single-quote every pattern)

```bash
# Search
sg run -p 'console.log($MSG)' --lang ts src/
# Search with JSON for scripting
sg run -p 'console.log($MSG)' --lang ts --json=compact src/
# Rewrite — ALWAYS dry-run first
sg run -p 'console.log($MSG)' -r 'logger.info($MSG)' --lang ts --json=compact src/
# Then apply, then review blast radius
sg run -p 'console.log($MSG)' -r 'logger.info($MSG)' --lang ts --update-all src/
git diff --stat
# YAML lint rules (reusable rules in sgconfig.yml)
sg scan src/
```

`--lang` is required when piping via `--stdin` (no extension to infer). Use `tsx` for `.tsx` files — `--lang ts` will not parse JSX.

## Rewriting discipline

1. Search to confirm matches. 2. Dry-run rewrite (`--json=compact`). 3. Inspect: match count, files affected, per-location preview. 4. Wrong → refine, go to 1. 5. Right → `--update-all`, then `git diff --stat` before finishing. **Report the number of files affected, not just matches — users care about blast radius.** In Crusor, bulk rewrites are a mutation: surface the dry-run summary and get approval before `--update-all` when the mutation gate asks.

## 0 matches but the code is there?

1. Check the pattern for regex leakage (`\w`, `.*`, `|`)
2. Check `--lang` (ts vs tsx)
3. Debug-parse: `echo '<sample>' | sg run -p '<pattern>' --lang ts --debug-query=ast --stdin` — `ERROR` nodes mean a malformed pattern
4. Inspect the target AST: `sg run -p '$_' --lang ts --debug-query=cst file.ts | head -40` to find the kind to match

## Inline pattern vs YAML rules

Inline `-p` for one-off, simple, exploratory queries. YAML rules (under `rules/`, `sg scan`) for reused lint rules, constraints/transforms, auto-fix, snapshot tests.
