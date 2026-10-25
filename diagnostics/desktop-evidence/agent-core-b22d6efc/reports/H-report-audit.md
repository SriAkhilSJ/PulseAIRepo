# Cross-Report Audit (Scenario H)

## Audit Matrix

| Scenario | Session ID | Authoritative Task Verdict | Verification Status | Executed Tools | Failed Steps | Proposals | Denominator | Cache Treatment | Inherited Contamination |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| A | `session-9b39ac231f68492a9ee0244c6df1fb47` | `completed` | `unverified` | 1 | 0 | 1 | `/ 100` | N/A (unreported excluded) | None |
| B | `session-38657324147f4b21909c9b086389affa` | `completed` | `unverified` | 1 | 0 | 1 | `/ 100` | N/A (unreported excluded) | None |
| C | `session-bd8c6488f6aa48248554c4102d7159f9` | `unverified` | `unverified` | 2 | 0 | 2 | `/ 100` | N/A (unreported excluded) | None (hello cleanly omitted) |
| D | `session-d0a8dac2821a404eaafcde13383ea18a` | `completed` | `unverified` | 1 | 1 | 1 | `/ 100` | N/A (unreported excluded) | None |
| E | `session-7101b65fcf214d53986e24b5f8232426` | `completed` | `unverified` | 1 | 0 | 1 | `/ 100` | N/A (unreported excluded) | None (no zero mutation finding) |
| F | `session-5119b1d86d664021bd1b2d92529466a3` | `in_progress` | `unverified` | 1 | 0 | 2 | `/ 100` | N/A (unreported excluded) | None (isolated from D) |

## Audit Observations
- **Authoritative task verdicts:** All finalized reports clearly state explicit task verdicts (`completed`, `unverified`, or `in_progress`).
- **No proposal inflation:** AI proposals are marked with `proposed` and not counted as executed tool successes.
- **Unified score denominator:** Every report uses `/ 100` denominator (never `/ 25`).
- **Turn isolation verified:** Reports do not inherit previous sessions' terminal receipts, exit codes, or user asks.
- **Cache reporting:** Unreported cache telemetry is excluded without penalty.
