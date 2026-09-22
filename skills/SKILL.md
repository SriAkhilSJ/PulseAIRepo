# Crusor Skills — Enterprise IDE Agent Skills

> Like Hermes `skills/` — each folder is a skill. A skill is ONE `SKILL.md` with triggers + instructions.
> The agent loads it via `SkillManager.get_relevant_skills(task)` → injected into context.

## Bundled skills (enterprise AI IDE)

- **mcp** — use MCP servers as tools (`filesystem`, `github`, `postgres`, `puppeteer`)
- **github-connector** — GitHub via MCP/ghq (PRs, issues, search)
- **browser-connector** — control Chrome via CDP / browser MCP
- **db-connector** — Postgres/SQLite via MCP
- **terminal-connector** — safe shell via `run_terminal`
- **repo-map** — codebase intelligence (PageRank signatures)

Create your own: `skills/my-skill/SKILL.md` — no code, just markdown.

See each folder's `SKILL.md`.
