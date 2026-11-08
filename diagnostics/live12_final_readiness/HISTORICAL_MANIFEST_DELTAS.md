# Historical Manifest Deltas

`diagnostics/live11_repair/SHA256SUMS.txt` is a point-in-time snapshot of the
Live11 repair **source and evidence**. This task intentionally changes three
source/artifact files, so those three entries no longer match:

| File | Old | New | Reason |
|---|---|---|---|
| `src/finops/recovery.py` | `228f1368…` | `45124127…` | Lazy governor import: startup sweep no longer imports FinOps for a workspace with no FinOps files |
| `src/bridge/__main__.py` | `1138a2b7…` | `99f94e00…` | Build probe cached/bounded; `emit()` no longer spawns Git |
| `out/.../crusorAIRendererService.js` | `6c05c184…` | `e3bf434b…` | Rebuilt contribution bundle from the current source |

All **evidence** entries in that manifest (reports, JSON, DBs, screenshots)
remain valid; only the three source/artifact entries advanced by design.

The historical manifest itself was **not rewritten**. This is the expected
source-provenance delta between the Live11 repair commit and the LIVE12
readiness closure.

The current source/artifact hashes are recorded in
`diagnostics/live12_final_readiness/SHA256SUMS.txt` and `BUILD_MANIFEST.json`.

The actual Live9/Live10/Live11 acceptance evidence manifests remain intact:

```text
P0.6.9                          41/41
Live11 run                      48/48
Live12 preflight                14/14
```

`diagnostics/live12_final_readiness/SHA256SUMS.txt` is this task's own evidence
manifest. It is regenerated whenever readiness evidence is added, and every
entry verifies at the final commit.
