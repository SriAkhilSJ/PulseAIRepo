# Crusor full-stack benchmark

**Date:** 2026-10-27

**Task:** Build a complete SprintBoard website with a Python standard-library REST backend, SQLite persistence, and a responsive HTML/CSS/JavaScript frontend.

**Model:** `z-ai/glm-5.3-flash` through the existing generic custom-provider path

## Outcome

No website was accepted or committed. Both bounded live attempts ended honestly as incomplete because Agent Core never created an application file. The independent suite, immutable-test hash, allowlist, credential scan, and completion gate all remained active; no test was weakened and no result was fabricated.

| Measure | First attempt | Corrected-harness retry |
|---|---:|---:|
| Actions run | [40491108367](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40491108367) | [40491628045](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/40491628045) |
| Provider calls | 12 / 12 | 12 / 12 |
| Runtime | 58 s | 54 s |
| Final reserve | Observed; evidence not ready | Observed; evidence not ready |
| Turn verdict | `turn_done`, `completed=false` | `turn_done`, `completed=false` |
| Application bytes | 0 | 0 |
| Tests immutable | Yes | Yes |
| Credential persisted | No | No |
| Token telemetry | 206,710; token breaker fired | 111,177; within retry ceiling |
| Tool trajectory | `read_file → run_terminal ×10` | `list_files ×2 → read_file ×2 → terminal ×7` |

The retry corrected the benchmark’s hidden-test placement, reduced the exposed tool menu, and removed the token-stop confounder. It still produced no `write_file` call, proving the remaining failure was in Agent Core’s routing contract rather than the grader.

## Root cause

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
| OpenCode | [`86976449`](https://github.com/anomalyco/opencode/tree/86976449c40d48f2731553a024f74552593d1764) | The max-step request keeps stable tool definitions but forces `toolChoice: "none"`; permission rules use deny precedence and an explicit ask/allow/deny table. |
| OpenHands SDK | [`d0d9d813`](https://github.com/OpenHands/software-agent-sdk/tree/d0d9d81324210414462fb676b377e0563a08a0cb) | Action batches stop at the first finish action; conversations enforce iteration/stuck bounds; the optional goal judge reopens work unless transcript evidence supports completion. |
| Gemini CLI | [`363a1311`](https://github.com/google-gemini/gemini-cli/tree/363a13119a57354f469732577518b9d6b319d1d6) | Pending tool calls deterministically return to the model inside a 100-turn bound; policy and tool activation are structural. |
| Cline | [`775d0398`](https://github.com/cline/cline/tree/775d0398039977ca5447ed39c1a7f178df69aa87) | Terminal completion tools, optional required-completion policy, bounded reminders, and per-tool/wildcard policy keep completion and permission explicit. |
| Codex | [`b6ad8ea1`](https://github.com/openai/codex/tree/b6ad8ea1fcd5562a7d3003887930be7d84824307) | Policy-filtered tool specs execute and resample; only an assistant response without pending tool work completes the turn. |

The common source-level pattern is structural policy plus deterministic result continuation and bounded completion recovery. Crusor now applies that pattern through forced first delivery, bind/execution allowlists, pending-call dispatch before budget closure, evidence-gated finish recovery, repeated-trajectory termination, and an inclusive tool-free final slot. No SprintBoard file name, expected answer, provider, or model is present in those controls.

## Local evidence

- edited modules and regressions compile with Python 3.11;
- focused progress, policy, autonomous-runtime, routing, and completion gate: **133 passed**;
- full provider-free suite: **2,784 passed, 30 failed, 26 skipped, 1 xfailed**;
- all 30 failures match the documented unrelated generated-desktop/environment baseline; the prior transient LSP timeout did not recur;
- a fuzzy terminal alias carrying a recursive-delete command is stopped by `SafetyGuard` before execution, and the protected file remains unchanged;
- the desktop `terminal` alias now enters recovery, clears same-command recovery, and receives the same third-identical-failure nudge as `run_terminal`;
- Python compilation, scoped whitespace, credential, and diff-aware Ruff checks pass with **0 new findings**;
- the exact state containing runtime diagnostics plus a hidden immutable test still binds only `write_file`;
- no provider-specific branch, prompt answer, expected application content, or model name is hardcoded in Agent Core.

At this provider-free checkpoint, no new live run or temporary workflow has been created. One strictly bounded key-backed run is authorized next; it must retain independent grading and be removed afterward. No pull request, merge, deployment, or failed site commit exists.
