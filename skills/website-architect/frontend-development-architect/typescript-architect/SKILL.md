---
name: typescript-architect
description: Architect-level TypeScript guidance — where types belong (boundary vs domain vs UI), structural modelling with discriminated unions, strictness settings that pay for themselves, schema-derived types, and the escape hatches that must stay exceptional. Use when designing module contracts or fixing a codebase where types do not survive refactors.
license: MIT
compatibility: TypeScript 5.x; strict mode
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect
  crusor-origin: original
  crusor-sources: "typescriptlang.org handbook; Zod/valibot docs"
  crusor-triggers: "typescript, types, generics, discriminated-union, zod, schema, strict, tsconfig, type-safety"
  crusor-verified-on: "2026-10-30"
---

# TypeScript Architecture

Types are a **contract document that the compiler enforces**. If the types are
`any` at the boundary and elaborate inside, the document is fiction.

## When to use

- Defining module and API contracts.
- Modelling state that has mutually exclusive shapes (loading/success/error).
- A refactor keeps breaking call sites the compiler did not catch.
- Choosing where validation lives.

## When NOT to use

- Local implementation typing inside an already-typed contract.
- Cosmetic type golf that does not change a boundary.

## Decision 1 — Where types live

| Layer | Type strategy |
|---|---|
| External boundary (HTTP, storage, queue) | **schema-first** — parse, then infer the type |
| Module public API | explicit exported types; no inferred return types on public functions |
| Domain model | discriminated unions and branded primitives |
| UI props | narrow, closed sets; no `any`, no optional-everything |

Rule: **derive from the schema, not the reverse.** A hand-written interface next
to a runtime schema drifts on the first version bump.

## Decision 2 — Model states as unions, not booleans

```ts
type LoadState<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; error: AppError };
```

- `isLoading && !data && !error` triples are the bug factory this replaces.
- Exhaustive `switch` with `never` in the default branch: adding a state becomes
  a compile error, not a runtime hole.

## Decision 3 — Strictness that pays

- `strict: true`, plus `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`
  for new projects — they remove the two most common silent `undefined`s.
- `noImplicitAny` is non-negotiable at boundaries.
- `skipLibCheck: true` is fine; loosening `strictNullChecks` is not.
- One `tsconfig` base + per-package overrides; never per-file pragmas to escape
  strictness.

## Decision 4 — Escape hatches are exceptional

- `any` is banned at module boundaries; use `unknown` + parse.
- `as` assertions only where the runtime has already proven the shape, with a
  comment stating why.
- `@ts-expect-error` requires a linked issue and an expiry.
- `eslint` rules: `no-explicit-any`, `consistent-type-imports`,
  `no-floating-promises`.

## Decision 5 — Generics

- A generic is justified when it preserves a relation between inputs and
  outputs; otherwise it is ceremony.
- Constrain it (`<T extends Record<string, unknown>>`) so errors point at the
  caller.
- Avoid generic soup in React components; prefer concrete props and composition.

## Failure modes at scale

- Types generated per-layer (`DTO`, `Model`, `View`, `Entity`) with mappers that
  nobody keeps in sync.
- A `types.ts` barrel that every package imports, coupling the whole monorepo.
- `Partial<T>` everywhere, so the compiler cannot prove a field exists.
- Runtime validation only at the edge, but the edge is three services away from
  where the data is used.

## Verification receipts

1. `tsc --noEmit` clean under the agreed strict flags.
2. Boundary parse tests: malformed payload rejected, not cast.
3. Exhaustiveness proven by adding a variant and watching the build fail.
4. `grep` for `as `, `any`, `@ts-ignore` with a reviewable count per package.
