# Pulse Reliability Benchmark - PBR-002
- **Task:** Route the exact opened workspace through every layer
- **Checks coverable on this lane:** 3

- **Run:** `pbr-002-e098834b7942`
- **Pulse commit:** `e1927c0c2ac0d25459eb0e2c0275018fd3244c95`
- **Outcome:** `failed_harness`

## Checks

| Check | Classification | Summary |
|---|---|---|
| workspace-hops | failed_environmental | no workspace.bound events recorded (environment) |
| proof-reaches-boundary | failed_environmental | no llm.request event containing 'workspace_proof.py' (environment) |
| turn-completes | failed_environmental | missing frame order ['turn_started', 'token', 'turn_done'] (environment) |

## Timing / usage

- startup 1787411645907 ms, first progress 0 ms, first token 0 ms, completion 0 ms
- model calls 0, tool calls 0, tokens in/out 0/0
