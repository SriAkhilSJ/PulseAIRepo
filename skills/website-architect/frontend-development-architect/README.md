# frontend-development-architect

Frontend architecture branch. Every language, framework and platform below has
its **own architect skill** (`SKILL.md`); this directory itself is also a skill
(`frontend-development-architect`) covering the branch-level decisions.

```
frontend-development-architect/
├── SKILL.md                              # branch architect: visual direction, tokens, budgets
├── html-css-architect/SKILL.md           # semantics, cascade, layout, responsive strategy
├── javascript-architect/SKILL.md         # module boundaries, async/error flow, runtime split
├── typescript-architect/SKILL.md         # contracts, unions, strictness, schema-derived types
├── vue-architect/SKILL.md                # Composition API, Pinia, Nuxt
├── angular-architect/SKILL.md            # standalone, signals vs RxJS, DI scopes
├── svelte-architect/SKILL.md             # runes, SvelteKit load/actions
├── astro-architect/SKILL.md              # islands, content collections, output modes
└── react-architect/
    ├── SKILL.md                          # React entry point: framework/shell/routing decisions
    ├── react-core-architect/SKILL.md     # component boundaries, composition, boundaries
    ├── nextjs-architect/SKILL.md         # App Router, rendering strategy, cache layers
    ├── react-router-architect/SKILL.md   # routing, loaders, guards (non-Next)
    ├── react-state-management-architect/SKILL.md
    ├── react-ui-libraries-architect/SKILL.md
    ├── react-testing-architect/SKILL.md
    ├── nodejs-architect/SKILL.md
    └── threejs-architect/SKILL.md
```

## Rules

- One directory = one skill; the directory name **is** the skill name (Agent
  Skills spec), and every leaf ends in `-architect`.
- A container without `SKILL.md` is structure only and is never injected.
- Each `SKILL.md` answers decisions, boundaries, failure modes and verification
  receipts — not "how to write the code".
- Every skill carries `metadata.crusor-domain`, `crusor-path`, `crusor-origin`,
  `crusor-sources`, `crusor-verified-on`.

## When the agent may take one

An Architect skill is a **planning instrument**, not an execution aid:

| Phase | Behaviour |
|---|---|
| planning / writing a plan or todo list | the branch and framework skills are injected and are meant to be read |
| executing | nothing is auto-injected; the model opens a skill deliberately with `skill_view(name)` only if the plan calls for it |

The loader records `phase="planning"` for every `*-architect` skill (override
with `metadata.crusor-phase`). `get_relevant_skills(task, phase=...)` refuses to
inject a planning skill while executing, so an architect skill can never drift
into a mid-run instruction.

## How many books at once

As many as the plan needs — `skill_view("fastapi-architect, django-architect")`
opens both, labelled and separated. A plan spanning several technologies reads
several skills; the only limits are mechanical: 6 books per call and a 60k-char
budget, after which the model is told what was left over so it can take the rest
in a second call.
