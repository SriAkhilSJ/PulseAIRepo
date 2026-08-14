# Retest-3 v2 — ✅ PASS

**Date:** 2026-08-14  
**Provider/model:** Sarvam custom endpoint / `sarvam-105b-conversations`  
**Thread:** `lab-test3-scaffold-fix`  
**Verdict:** **PASS — real scaffold, dependencies, byte-identical component delivery, and clean TypeScript verification.**

## Cost controls

- `AGENT_ITERATION_BUDGET=10`
- `PROVIDER_SAFE_LIMIT=6000`
- Auxiliary summarizer disabled (custom-provider aux would use the same 105B model)
- 30-second watchdog
- Kill on three identical calls, 60 seconds without events, missing deliverables after 180 seconds, or 240-second hard cap

The watchdog did not kill this run. Process exited normally with code 0.

## Monitoring

| Time | Events | Tool calls | hero | demo |
|---:|---:|---:|---:|---:|
| 30s | 1 | 0 | missing | missing |
| 61s | 16 | 5 | missing | missing |
| 91s | 16 | 5 | missing | missing |
| 121s | 26 | 7 | present | present |
| 151s | 45 | 10 | present | present |
| Final | 58 | 12 | present | present |

## Result

- Wall time: **148.56 seconds**
- Provider calls: **12**
- Prompt tokens: **115,625**
- Completion tokens: **1,020**
- Total tokens: **116,645**
- Engine-estimated cost: **$0.116645**
- Recovery attempts: **0**
- Replans: **0**
- Recorded failures: **0**

## Deliverables

| Requirement | Result | Evidence |
|---|---|---|
| Next.js project at workspace root | ✅ | `package.json`, `src/app`, `tsconfig.json`; no workspace/workspace nesting |
| TypeScript + Tailwind | ✅ | generated Next.js 16.3.1 TypeScript/Tailwind scaffold |
| Required dependencies | ✅ | `three`, `@react-three/drei`, `@react-three/fiber` in dependencies |
| `src/components/ui/hero-futuristic.tsx` | ✅ | 7,025 bytes; byte-identical to `_provided` |
| `src/components/ui/demo.tsx` | ✅ | 6,468 bytes; byte-identical to `_provided` |
| TypeScript verification | ✅ | final `typecheck_workspace`: `tsc --noEmit passed with 0 errors` |
| Honest completion | ✅ | task status `completed`, 7/7 plan steps, no failures |

Hashes/identity:

```text
hero-futuristic.tsx: f66c4f9cc10f4e1b… — identical
 demo.tsx:           cf8e41c97ef8df52… — identical
```

## Actual tool flow

```text
list_files + parallel read_file x2
think
scaffold_nextjs(packages=[three, drei, fiber])
copy_file x2
initial typecheck_workspace (found generated LayoutProps error)
read_file src/app/layout.tsx
edit_file minimal generated-layout fix
final typecheck_workspace (0 errors)
verify
final response
```

## Why this run passed

The reusable `scaffold_nextjs` tool eliminated both previous failure paths:

- no `create-next-app .` conflict with `_provided`;
- no `<workspace>/<workspace>` nesting;
- generated in a temporary sibling with `--skip-install`;
- merged at the actual workspace root;
- `_provided` preserved;
- dependencies installed once.

The model then used real `copy_file` calls and repaired one genuine generated-project type error before re-running the compiler.

## No test-data hardcoding

Production code did not contain either component name, component body, expected hash, test workspace, thread ID, or forced PASS result. The harness supplied real source files; the agent chose and executed tools; the evaluator independently compared bytes and inspected the final compiler output.

## Caveat

This run proves component placement, project setup, dependency installation, and TypeScript correctness. It did not perform browser/render verification because the Retest-3 task's explicit verification requirement was `typecheck_workspace`; no browser call was needed to satisfy the stated benchmark.
