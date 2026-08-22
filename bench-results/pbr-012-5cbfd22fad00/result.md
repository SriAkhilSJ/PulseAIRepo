# Pulse Reliability Benchmark - PBR-012
- **Task:** Cancel a turn during bounded context preparation
- **Checks coverable on this lane:** 2

- **Run:** `pbr-012-5cbfd22fad00`
- **Pulse commit:** `e1927c0c2ac0d25459eb0e2c0275018fd3244c95`
- **Outcome:** `failed_functional`

## Checks

| Check | Classification | Summary |
|---|---|---|
| cancelled-ui | failed_new | no dom observation for .pulseai-turn-receipt.is-cancelled |
| cancelled-protocol | passed | final frame ok |
| no-post-cancel-model-call | passed | 0 event(s) after cancel |
| no-worker-growth | failed_new | missing observation 'additional_workers' |

## Claims

- `unverified` - turn cancelled cleanly

## Timing / usage

- startup 1787411603731 ms, first progress 1787411603891 ms, first token 0 ms, completion 1787411604044 ms
- model calls 0, tool calls 0, tokens in/out 0/0
