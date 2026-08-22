# Pulse Reliability Benchmark - PBR-003
- **Task:** Require explicit selection in a multi-root workspace
- **Checks coverable on this lane:** 2

- **Run:** `pbr-003-72dc8b329db0`
- **Pulse commit:** `e1927c0c2ac0d25459eb0e2c0275018fd3244c95`
- **Outcome:** `failed_functional`

## Checks

| Check | Classification | Summary |
|---|---|---|
| selection-required | failed_new | dom visible=False != expected True |
| blocked-before-selection | passed | 0 prompt(s) before selection |
| chosen-root-retained | failed_new | no workspace.bound events recorded |

## Claims

- `unverified` - selection flow observed; prompt-after-selection pending live engine

## Timing / usage

- startup 1787411612024 ms, first progress 0 ms, first token 0 ms, completion 0 ms
- model calls 0, tool calls 0, tokens in/out 0/0
