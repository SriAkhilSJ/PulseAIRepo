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
    └── react-testing-architect/SKILL.md
```

## Rules

- One directory = one skill; the directory name **is** the skill name (Agent
  Skills spec), and every leaf ends in `-architect`.
- A container without `SKILL.md` is structure only and is never injected.
- Each `SKILL.md` answers decisions, boundaries, failure modes and verification
  receipts — not "how to write the code".
- Every skill carries `metadata.crusor-domain`, `crusor-path`, `crusor-origin`,
  `crusor-sources`, `crusor-verified-on`.
