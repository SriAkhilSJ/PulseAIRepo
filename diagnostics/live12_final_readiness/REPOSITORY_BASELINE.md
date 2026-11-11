# Repository Baseline

| Item | Value |
|---|---|
| Expected baseline | `f12995255ad72204de5e1172054d1f62508287a9` |
| Actual local HEAD at preflight | `f12995255ad72204de5e1172054d1f62508287a9` |
| Final source repair commit | `7d4a4cc587bde12d7fc89d5c0714d2ef4ac406ee` |
| Origin branch HEAD | `f12995255ad72204de5e1172054d1f62508287a9` |
| local == origin | yes |
| Baseline ancestor of HEAD | yes (same commit) |
| Branch | `feat/prompt-cache-stabilization` |
| Commits after baseline | none at preflight start |

The working tree contains many pre-existing unrelated changes (personal-finance
app, root reports, etc.). No reset, clean, stash or overwrite was performed; they
are not part of this task's commit.

Historical evidence at baseline:

| Manifest | Result |
|---|---|
| `diagnostics/p0_6_9/SHA256SUMS.txt` | 41/41 |
| Live11 run manifest | 48/48 |
| `diagnostics/live11_repair/SHA256SUMS.txt` | 19/19 at preflight; **16/19 after this repair** (3 intentional source/artifact deltas, see `HISTORICAL_MANIFEST_DELTAS.md`) |
| `diagnostics/live12_acceptance/SHA256SUMS.txt` | 14/14 |

Relevant commits:

```text
f1299525 docs(live12): provider-free preflight and acceptance procedure
128fbc56 fix(bridge): exactly-once submissions and orphaned reservation recovery
6959c862 docs(generation-boundary): record live acceptance run and failure
563f5cc2 fix(orchestration): bounded regeneration when generation is truncated
```

The Live11 run executed `563f5cc2` (engine build line
`563f5cc2 2026-11-07 23:56:02 -0800`). The repair commit `128fbc56` is present.
No relevant intervening commit was skipped.
