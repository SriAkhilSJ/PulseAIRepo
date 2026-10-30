# The Architect library

Internally managed skills for Crusor. Each domain is a tree of shelves; each
shelf holds books, and the agent takes the books its task needs.

```
skills/
├── website-architect/     the web product, end to end
├── mobile-architect/      iOS, Android, React Native, Flutter, release
├── desktop-architect/     Electron, Tauri, native, distribution
└── …                      (process skills: flat, one directory per skill)
```

## Rules

1. **One directory = one skill.** A directory with a `SKILL.md` is a skill; the
   frontmatter `name` must equal the directory name (Agent Skills spec).
2. **Containers carry structure only.** A directory without `SKILL.md` is a
   shelf, never injected.
3. **Every domain has a crown skill** — `skills/<domain>/SKILL.md` — so an agent
   landing on a domain always has an entry point.
4. **Everything ends in `-architect`** inside the architecture domains.
5. **Metadata is the spec's free-form `metadata` map:**
   `crusor-domain`, `crusor-path` (path from `skills/`), `crusor-origin`
   (`adapted` | `original`), `crusor-sources`, `crusor-triggers`,
   `crusor-verified-on`.
6. **Architect skills are planning instruments.** They are injected while a
   plan or todo list is being written, never mid-execution; during execution the
   model pulls them deliberately.
7. **Bodies stay under the injection cap** (6000 chars). Longer material belongs
   in `references/`, not the body.

## Taking a book

```
skills_list()                                  # shelves at the root
skills_list(shelf="website-architect/api-development-architect")
skill_view("rest-architect, graphql-architect")   # one, or several
```

## Domains

| Domain | Skills | Covers |
|---|---|---|
| `website-architect/` | 76 | frontend, backend, data, API, UI implementation, security, delivery |
| `mobile-architect/` | 6 | platform choice, iOS, Android, React Native, Flutter, stores and rollout |
| `desktop-architect/` | 5 | runtime choice, Electron, Tauri, native, signing and updates |

See `website-architect/VERIFICATION.md` for the current conformance audit.
