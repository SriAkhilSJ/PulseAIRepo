# The Architect library

Internally managed skills for Crusor. Each domain is a tree of shelves; each
shelf holds books, and the agent takes the books its task needs.

```
skills/
├── website-architect/     the web product, end to end
├── mobile-architect/      iOS, Android, RN, Flutter, offline, security, perf, testing, a11y, release
├── desktop-architect/     Electron, Tauri, native, IPC, storage, security, update, distribution
├── cloud-and-devops-architect/  7 shelves: providers, identity, networking, compute,
│                            data services, IaC, platform, operations
├── ai-ml-architect/       LLM apps, RAG, evals, serving, MLOps, agents
├── data-engineering-architect/  batch, streaming, warehouse, orchestration, quality, dbt
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
| `mobile-architect/` | 13 | platform choice, iOS/SwiftUI, Android/Compose, RN, Flutter, offline sync, security, performance, testing, accessibility, release |
| `desktop-architect/` | 9 | runtime choice, Electron, Tauri, native, IPC, local storage, security, updates, distribution |
| `cloud-and-devops-architect/` | 36 | providers (AWS/GCP/Azure/Cloudflare), IAM, VPC/DNS, EC2/ECS/Lambda/K8s, storage/DB/messaging/cache, Terraform/Pulumi/CFN/Ansible, Helm/GitOps/mesh/K8s-security/IDP, reliability/cost/observability/chaos/DR/incident |
| `ai-ml-architect/` | 7 | model boundary, LLM apps, RAG, evals, inference serving, MLOps, agents |
| `data-engineering-architect/` | 7 | topology, batch, streaming, warehouse modelling, orchestration, quality, dbt |

See `website-architect/VERIFICATION.md` for the current conformance audit.
