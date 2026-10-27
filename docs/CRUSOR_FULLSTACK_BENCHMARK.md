# Crusor full-stack benchmark

**Date:** 2026-10-27

**Task:** Build a complete SprintBoard website with a Python standard-library REST backend, SQLite persistence, and a responsive HTML/CSS/JavaScript frontend.

**Model:** `z-ai/glm-5.3-flash` through the existing generic custom-provider path

## Outcome

No website was accepted or committed. The first two bounded attempts created no application file. The third began with `write_file` and produced substantial partial output, but still omitted a required file and failed two acceptance tests. After deliverable reconciliation was added, one newly authorized evidence run produced every required file and passed four of five tests, but the independent suite still failed on SQLite persistence. The immutable-test hash, allowlist, credential scan, completion gate, and grade gate remained active throughout; no test was weakened and no result was fabricated.

| Measure | First attempt | Corrected-harness retry | Post-fix validation | Reconciliation evidence run |
|---|---:|---:|---:|---:|
| Actions run | [40491108367](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40491108367) | [40491628045](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40491628045) | [40498309113](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40498309113) | [40576857348](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40576857348) |
| Provider calls | 12 / 12 | 12 / 12 | 12 / 12 | 12 / 12 |
| Runtime | 58 s | 54 s | 136 s | 104 s |
| Final reserve | Observed; evidence not ready | Observed; evidence not ready | Observed; evidence not ready | Observed; evidence not ready |
| Turn verdict | `turn_done`, `completed=false` | `turn_done`, `completed=false` | `turn_done`, `completed=false` | `turn_done`, `completed=false` |
| Application bytes | 0 | 0 | 24,991 | 27,162 |
| Independent tests | Not runnable | Not runnable | 5 ran; 2 failed | 5 ran; 4 passed, 1 error |
| Required files | Missing | Missing | At least one missing | All five present |
| Tests immutable | Yes | Yes | Yes | Yes |
| Credential persisted | No | No | No | No |
| Token telemetry | 206,710; token breaker fired | 111,177; within retry ceiling | 161,228; within ceiling | Observed and within ceiling; exact value not retained in the retrievable annotation |
| Tool trajectory | `read_file → run_terminal ×10` | `list_files ×2 → read_file ×2 → terminal ×7` | `write_file ×6 → edit_file → write_file → terminal ×5` | 15 completed tools; full sanitized sequence was collected but its single CI annotation was truncated |

The second run corrected the benchmark’s acceptance-test placement, reduced the exposed tool menu, and removed the token-stop confounder. It still produced no `write_file` call, proving the remaining zero-file failure was in Agent Core’s routing contract rather than the grader. The third run proved forced first delivery. The fourth proved deliverable reconciliation—all five outputs landed—but did **not** prove end-to-end success: the benchmark remained failed.

## Root cause of the zero-file attempts

Two general rules interacted badly before the first provider request:

1. `_begin_diagnostic_turn` asks `StepTracker` to create `diagnostics/traces/...` inside the active workspace. `_workspace_is_effectively_empty` counted that Agent Core-owned evidence as user project content, so a genuinely fresh build did not enter the structural forced-delivery phase.
2. The deterministic interest classifier gave any phrase matching “do not modify” global precedence. A normal scoped constraint—“build the application; do not modify the immutable tests”—therefore changed the whole turn to `change_policy=no_changes`, removing mutation tools even though the same instruction explicitly requested a build.

This explains the observed read/terminal-only trajectories and why the final evidence predicate remained false.

## Provider-free fix

| Before | After | Optimization — why |
|---|---|---|
| Runtime `diagnostics/` made a new workspace look populated. | Runtime-owned `diagnostics/` and dot-prefixed fixtures are ignored by the empty-workspace signal. | Agent evidence must not disable Agent Core’s own fresh-delivery guard. |
| “Do not modify the tests” cancelled “build the app.” | An independent positive mutation request wins while the protected artifact remains a recorded constraint. | Scoped immutability is not a global no-change instruction. |
| First turn exposed reads and terminals without a deliverable. | The exact benchmark entry state resolves to `forced_delivery` with only `write_file`. | File delivery becomes structurally available before exploration or verification. |
| Failed build could have been described as successful. | Call 12 remained tool-free, evidence readiness was false, and both runs ended `completed=false`. | Completion discipline remained honest under a harder failure mode. |
| The desktop `terminal` alias was classified like `run_terminal`, but failed aliases did not enter recovery, clear recovery, or count identical retries. | Both terminal names now share recovery and repeated-command accounting. | A provider/tool dialect cannot bypass bounded failure recovery. |
| Fuzzy tool-name repair ran only after safety and permission checks. | Names are canonicalized before phase, permission, and safety policy; incomplete provider responses are still rejected before any execution lookup. | A typo cannot be treated as unknown/default-safe and become a real shell or file tool after policy has already run. |
| Execution phases published a mutation-count field that no executor consumed. | The ghost field is removed; the real bind-time and execution-time allowlists remain the policy contract. | Monitoring now describes enforceable behavior, while legal same-phase batching stays available. |

Explicit no-change commands such as “run the tests without changing code” remain `no_changes`; the fixes do not weaken read-only requests.

## Renewed current-source comparison

The whole control path was rechecked against current source rather than product descriptions:

| Repository | Source inspected | Relevant executable behavior |
|---|---|---|
| OpenCode | [`caebbcc0`](https://github.com/anomalyco/opencode/tree/caebbcc0807e630629725f320f35a09aa4a427be) | Tool calls retain completed/error/unfinished status and duration; at the max-step boundary tools are disabled and the model must report completed and remaining work. |
| OpenHands SDK | [`ded5fa5e`](https://github.com/OpenHands/software-agent-sdk/tree/ded5fa5e76ff9b7b4ff622a8df2ed20335e10652) | The goal controller judges the objective against transcript evidence after each run, distinguishes completion from a capped run, continues with the missing-work finding, and conservatively treats an invalid verdict as incomplete. |
| Gemini CLI | [`8080ea70`](https://github.com/google-gemini/gemini-cli/tree/8080ea70a54cda947b6c4f38293f195241e45968) | Current core retains bounded session turns and structural policy/tool activation rather than relying on prompt-only compliance. |
| Cline | [`775d0398`](https://github.com/cline/cline/tree/775d0398039977ca5447ed39c1a7f178df69aa87) | Terminal completion tools, optional required-completion policy, bounded reminders, and per-tool/wildcard policy keep completion and permission explicit. |
| Codex | [`b6ad8ea1`](https://github.com/openai/codex/tree/b6ad8ea1fcd5562a7d3003887930be7d84824307) | Policy-filtered tool specs execute and resample; only an assistant response without pending tool work completes the turn. |

The common source-level pattern is structural policy plus deterministic result continuation and bounded completion recovery. Crusor now applies that pattern through forced first delivery, bind/execution allowlists, pending-call dispatch before budget closure, evidence-gated finish recovery, repeated-trajectory termination, and an inclusive tool-free final slot. No SprintBoard file name, expected answer, provider, or model is present in those controls.

## Bounded post-fix live receipt

Run [40498309113](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40498309113) was the first authorized key-backed validation. Its sanitized check annotation records:

- the first tool was `write_file`;
- 12 provider requests and 13 tool executions completed in 136 seconds;
- 24,991 bytes of expected application content existed at grading time;
- the tool path was `write_file ×6 → edit_file → write_file → terminal ×5`;
- all five independent tests ran, with two failures;
- at least one required application file was absent;
- tests remained byte-for-byte unchanged, no unexpected file or symlink appeared, and the provider secret was absent from generated files;
- telemetry was present at 161,228 input tokens, below the 250,000 ceiling, and no external budget stop fired;
- the reserved final request observed `completion_evidence_ready=false`, so the turn correctly ended `completed=false`; and
- the independent grade failed, so the site commit step was skipped.

The detailed Actions log archive was unavailable through the permitted results endpoint; only the sanitized check annotation and step conclusions were retrievable. The exact two failing test names are therefore not guessed. The immutable result was sufficient for that acceptance decision: the site failed, so no site was committed or previewed. A later, separately authorized evidence run is documented below.

## Post-failure Agent Core reconciliation

The 24,991-byte receipt proves substantial activity, not complete delivery. Agent Core extracted path-shaped outputs and non-code root artifacts, but deliberately ignored bare code filenames in ordinary prose to avoid treating framework names such as `Next.js` as files. That conservative rule also discarded unambiguous root filenames when the user placed them in an explicit required-files list. Because the missing file never entered the on-disk obligation ledger, the verification reserve activated and structurally exposed terminal checks. Five terminal calls then consumed the remaining bounded actions; a later repair phase permitted edits after a failed check, but did not require returning to the still-unknown missing output.

| Before | After | Optimization — why |
|---|---|---|
| Bare code filenames were ignored even when each was an exact bullet under a required-files/deliverables heading. | Raw line structure is retained for a context-aware file ledger; exact root entries are enforced while prose and technology-stack `Next.js` mentions remain ignored. | Deliverable provenance resolves the ambiguity without globally weakening the historical false-positive guard. |
| Verification reserve could become terminal-only while an explicit file was absent; later repair merely allowed mutation. | Autonomous runs enter `missing_delivery` first, with file-producing and targeted local-read tools; terminal/check tools remain unavailable until every explicit file exists on disk. | Verification cannot prove an output that was never delivered. Generated project directories stay on the normal terminal/toolchain path, so this does not deadlock app generators. |
| `outcome.json` retained aggregate frame counts, leaving the decisive per-tool results and provider latency boundary hidden. | It now stores capped ordered request receipts and tool outcomes with success/failure/skipped/unfinished status, observed duration, aggregate p50/p95 timing, and short redacted result summaries. | A future failed path shows where time and failure accumulated without persisting prompts, arguments, commands, file bodies, full results, or credential values. |

These controls are task-, provider-, and model-independent. No benchmark filename, expected assertion, SprintBoard content, provider name, or model name is encoded in extraction, routing, or monitoring.

## Reconciliation evidence run and verification repair

Run [40576857348](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40576857348) was explicitly authorized to test the current controls rather than infer success from provider-free regressions. It **failed** and therefore does not validate Agent Core end to end.

The positive evidence is narrow but real: all five required outputs landed, the first tool was `write_file`, 27,162 application bytes were produced, four of five acceptance tests passed, all 12 provider requests returned, and the turn remained honestly incomplete (`completed=false`, `completion_evidence_ready=false`). The exact remaining failure was `test_04_crud_stats_and_sqlite_persistence`: after the API created a task, the acceptance database named by `SPRINTBOARD_DB` had no `tasks` table. This proves persisted CRUD did not target the required environment-selected database. The grader also detected an unexpected top-level file, but the retrievable annotation did not preserve its name, so it is not guessed.

Monitoring collection itself passed every immutable check: schema v2 was present; all 12 request receipts and all 15 tool outcomes had matching timing records; no provider secret appeared in generated files or `outcome.json`; and request latency totaled 88.023 seconds inside a 104-second run (p50 2.865 seconds, p95 31.566 seconds). Monitoring publication exposed a separate defect: one 4,096-character GitHub annotation truncated the tool-ledger tail, while the Actions log archive again returned `EOF`. The full sanitized sequence existed in ephemeral `outcome.json`, but it was not retrievable afterward and is therefore not claimed as observed.

| Before | After | Optimization — why |
|---|---|---|
| Fresh delivery guidance explicitly deferred additional files to later iterations. | Independent named files are now requested as batched `write_file` calls in the same response, both at first delivery and missing-delivery reconciliation. | Preserve bounded calls for verification and repair instead of deliberately serializing obvious outputs. |
| A failed executable check created no durable obligation; a different weaker green check could overwrite static status. | Failed non-environment checks create identity-scoped debt that survives edits and can be cleared only by the exact failed check passing. | A narrow health test cannot erase a failed full acceptance suite. |
| Verification repair exposed mutation and terminal tools together. | The graph alternates structurally: failed check → mutation-only repair → exact-check-only revalidation. | A run cannot repeatedly check unchanged code or skip directly to a weaker verifier. |
| CI published the complete monitoring ledger as one annotation. | The runner emits independently parseable, defensively redacted summary/request/tool annotation batches below GitHub’s hard size limit. | Evidence remains retrievable even when Actions logs are unavailable. |

These follow-up controls are provider-free tested only. No additional key-backed rerun has been made after them, so benchmark success remains unproven.

## Local evidence

- edited modules and regressions compile with Python 3.11;
- the affected repair/routing/annotation files pass **33/33**; an earlier broader completion/routing/progress/runner gate passed **181/181**;
- current full provider-free result: **2,796 passed, 30 failed, 26 skipped, 1 xfailed**; the same exact 30 generated-desktop/environment baseline failures remain, and no changed Agent Core or runner test failed;
- every current gate, routing, runner-receipt, progress, budget, and completion regression passed;
- a fuzzy terminal alias carrying a recursive-delete command is stopped by `SafetyGuard` before execution, and the protected file remains unchanged;
- the desktop `terminal` alias now enters recovery, clears same-command recovery, and receives the same third-identical-failure nudge as `run_terminal`;
- Python compilation, scoped whitespace, credential, and diff-aware Ruff checks pass with **0 new findings**;
- the exact state containing runtime diagnostics plus a hidden immutable test still binds only `write_file`;
- no provider-specific branch, prompt answer, expected application content, or model name is hardcoded in Agent Core.

The latest authorized live run is complete and failed; no further provider-backed retry was made. Its temporary workflow was removed in cleanup commit `d31a5cf0`. No generated site, pull request, merge, preview, or deployment was created.
