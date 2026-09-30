# Crusor Skills — Enterprise IDE Agent Skills

> Like Hermes `skills/` — each folder is a skill. A skill is ONE `SKILL.md` with triggers + instructions.
> The agent loads it via `SkillManager.get_relevant_skills(task)` → injected into context.

## Bundled skills (enterprise AI IDE)

### Connectors (external systems)
- **mcp** — use MCP servers as tools (`filesystem`, `github`, `postgres`, `puppeteer`)
- **github-connector** — GitHub via MCP/gh CLI (PRs, issues, search)
- **browser-connector** — control Chrome via CDP / browser MCP
- **db-connector** — Postgres/SQLite via MCP
- **terminal-connector** — safe shell via `run_terminal`

### Coding workflow (ported from Hermes `software-development`)
- **codebase-inspection** — codebase intelligence: LOC, languages, ratios (pygount)
- **test-driven-development** — RED-GREEN-REFACTOR; no production code without a failing test
- **systematic-debugging** — 4-phase root-cause debugging before fixing
- **requesting-code-review** — pre-commit review: security scan, quality gates
- **simplify-code** — parallel subagent cleanup of recent changes
- **subagent-driven-development** — drive `delegate_to_subagent(_batch)`: fresh subagent per task + 2-stage review
- **spike** — throwaway feasibility experiments: decompose → research → build → verdict
- **systematic tools**
  - **node-inspect-debugger** — Node via `node inspect` / V8 inspector / CDP
  - **python-debugpy** — Python via `breakpoint()`/pdb/debugpy (DAP)
  - **ast-grep** — AST-aware structural search & rewrite (`sg`), dry-run-first codemods
  - **rest-graphql-debug** — layer-by-layer HTTP API debugging with curl

### Thinking & docs
- **grill-me** — stress-test a plan with frontier-round adversarial questioning before code
- **code-wiki** — generate wiki docs + Mermaid diagrams for any codebase
- **skill-authoring** — author new `skills/<name>/SKILL.md` files (the self-improving loop)

### Media
- **media-sourcing** — search (Openverse/Wikimedia/Pexels), download and license-correctly wire real photos/videos into UI work via `media_search` + `media_download`

## Trigger mechanics

`SkillManager` derives triggers from (1) the `**Triggers:**` line, (2) frontmatter
`keywords`/`triggers`/`metadata.hermes.tags`, (3) folder-name fallback. A skill fires
when any trigger appears (substring) in the task; the skill BODY (frontmatter stripped)
is injected, capped at 6000 chars for bundled skills.

Create your own: `skills/my-skill/SKILL.md` — no code, just markdown. See **skill-authoring**.

See each folder's `SKILL.md`.
