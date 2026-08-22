# Pulse Reliability Benchmark - PBR-001
- **Task:** Block prompts when no folder is open
- **Checks coverable on this lane:** 3

- **Run:** `pbr-001-4267236e0fb4`
- **Pulse commit:** `e1927c0c2ac0d25459eb0e2c0275018fd3244c95`
- **Outcome:** `failed_functional`

## Checks

| Check | Classification | Summary |
|---|---|---|
| composer-disabled | failed_new | dom enabled=True != expected False |
| no-workspace-hint | failed_new | dom text='Enter to sendShift+Enter for new line' != expected 'Open a folder to start a Pulse session.' |
| no-prompt-frame | passed | no forbidden frames |

## Claims

- `unverified` - prompts are blocked with no folder open

## Timing / usage

- startup 1787411604205 ms, first progress 0 ms, first token 0 ms, completion 0 ms
- model calls 0, tool calls 0, tokens in/out 0/0
