# Phase 0 — Production Baseline

**Project:** Crusor AI IDE
**Repository:** `SriAkhilSJ/PulseAIRepo`
**Branch:** `feat/prompt-cache-stabilization`
**Expected baseline:** `27b17f108f232cb5f8524ce4ecc18c02d65dc68d`
**Audit date:** 2026-11-08
**Mode:** read-only with respect to product source

---

## 1. Repository state

| Item | Observed |
|---|---|
| Current branch | `feat/prompt-cache-stabilization` |
| Current HEAD | `27b17f108f232cb5f8524ce4ecc18c02d65dc68d` |
| Expected HEAD | identical |
| Origin HEAD | identical (`local == origin`) |
| Baseline ancestor | yes (same commit) |
| Working tree | **175 pre-existing entries** (modified + untracked) |

Dirty-entry distribution (pre-existing user work, not created by this audit):

| Area | Entries |
|---|---:|
| `diagnostics/` | 64 |
| repository root | 62 |
| `apps/` | 27 |
| `src/` | 15 |
| `desktop/` | 4 |
| `scripts/` | 3 |

Phase 0 staged only the five audit documents under
`docs/production/phase-0/`. No product source, evidence, database or artifact
was modified, staged or committed.

## 2. Artifact baseline

| Item | Value |
|---|---|
| Electron version | `42.8.1` |
| `CrusorAI.exe` | `49486b2ef4d940bdbf9985811a8ed2c808551d6e1353d1b3cf3a4c5b8c4fd6d4` |
| Executable size | 221,944,832 bytes |
| Desktop `BUILD_INFO.json` | source commit `7d4a4cc5`, built 2026-11-08T15:15:00Z |
| Contribution source hash | `465a6bb15486775bb643684173b2dbb626d6e936c3e1797488c77d25a0c476a5` (50 files) |
| Native `.node` files present | 70 |
| `vsda` native package | **unresolved** (JS wrapper absent; `.node` only) |

The executable and contribution bundle predate the harness-only and audit-only
commits; they remain byte-identical to the qualified provenance recorded in
`diagnostics/live12_final_readiness/ARTIFACT_PROVENANCE.md`.

## 3. Launch state (important)

The first authorized live acceptance attempt (`diagnostics/live12_run_20261108_085953/`)
launched `CrusorAI.exe` but the main process crashed before the workbench:

```text
Could not locate the bindings file
  @vscode/policy-watcher/build/Release/vscode-policy-watcher.node
```

Cause: the dependency tree had been restored with `npm ci --ignore-scripts`,
which skipped native builds. Eight native modules were subsequently restored
offline from the local Microsoft VS Code installation. That repair is **not
yet proven by a successful launch**. `vsda` remains unresolved and is lazily
imported by the sign service, not the early startup path.

## 4. Historical evidence inventory

| Manifest | Result |
|---|---|
| `diagnostics/p0_6_9/SHA256SUMS.txt` | 41/41 |
| Live11 run manifest | 48/48 |
| `diagnostics/live11_repair/SHA256SUMS.txt` | 16/19 — three documented source/artifact deltas |
| `diagnostics/live12_acceptance/SHA256SUMS.txt` | 14/14 |
| `diagnostics/live12_final_readiness/SHA256SUMS.txt` | 28/28 |
| `diagnostics/live12_run_20261108_085953/CHECKSUMS.sha256` | 19/19 |

The historical reservation `res_d7990e4d3dc3` remains `in_flight`,
₹0.167204, with no usage, invocation or settlement. It was not touched.

## 5. Phase 0 method and constraints

Performed:

- Git state and ancestry checks.
- Plain-text inspection of the four named security files.
- Plain-text inspection of supporting modules, scripts, workflows, tests and
  evidence documents.
- Filesystem inspection of the Electron runtime and native bindings.
- Read-only reads of prior evidence logs.

Intentionally **not** performed:

- Python imports of application modules.
- `pytest` or the agent-core checkup.
- Electron / CrusorAI launch.
- Dependency installation or removal.
- Provider calls, reservations or spend.
- Database or ledger writes.
- Permission or ACL changes.
- Any repair or executable run.

## 6. Baseline verdict

```text
BASELINE_MATCHED
AUDIT_MODE_READ_ONLY
PRODUCT_SOURCE_UNCHANGED_BY_PHASE_0
```

The baseline is the expected commit. The checkout is not clean because of
pre-existing user work; that work was preserved. The desktop executable is
qualified by hash but its launch is not currently proven after the native
module repair.
