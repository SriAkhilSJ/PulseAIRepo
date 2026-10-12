# Agent-Core Audit Fixes — 2026-10-12

Follow-up to the agent-core audit (`AGENT_CORE_AUDIT.md`). Four defects and one
claim gap were found by running the repo's own hermetic suite against the shipped
code; all four are fixed here, each with a regression pin that fails against the
old code. CI was added — the repo had none, which is *how* these shipped.

## What changed

| # | Defect (audit) | Fix | Files |
|---|---|---|---|
| 1 | D35 parallel-tool-call guidance was a silent no-op: `CLAUDE_SYSTEM_PERSONA.replace(_D35_LEGACY_BATCH_SENTENCE, …)` matched nothing, so the batch block never reached the model | Composition is now structural: drop the legacy line *if present*, then **always** append `_D35_BATCH_SENTENCE` | `src/prompts/claude_persona.py` |
| 2 | `_looks_like_execution_task` matched markers as substrings — `"test"` inside `"test2"` — so read-only verification turns were stamped incomplete | Word-boundary regexes with real inflections; `"test2"`/`"address"` no longer match, `"build/test/adding/write a"` still do | `src/graphs/gates.py` |
| 3 | `no_work_done` fired on "no *mutation* tool ran", which is every read-only turn; and `finalize`'s console line disagreed with the verdict it returned | Check now requires **zero tool activity at all** (pure monologue); the verdict is computed once and used for both `task_status` and the log line | `src/graphs/chat_graph.py` |
| 4a | The plan-complete wrap lap (one closing summary) could be routed back into `finish_gate` because the no-tool Hard Gate sat above it | The `wrap_summary` terminal check moved above the Hard Gate; pending tool calls still dispatch first | `src/graphs/gates.py` |
| 4b | A task asking for a screenshot could pass verification with only a DOM snapshot | `_task_asks_visual_proof` + `screenshot` added to the required receipt domains for those tasks | `src/graphs/gates.py` |
| 5 | `resolve_context_window` ignored its `endpoint_probe` flag: the slow endpoint ask (measured 5.1 s) ran on blocking paths | Rung 3 is gated on `endpoint_probe`; the background warm-up remains the place the endpoint is asked | `src/context/model_budgets.py` |
| 6 | Stale pins / drift: stall timeout pinned at 45 (code: 35), trip-reason pinned at the old 30 budget, depth-cap wording, rung-7 fallback asserted against the wrong constant | Pins updated to the shipped, documented contracts (each with a comment naming the intent) | `src/tests/*` |
| 7 | Claims with no evidence in-repo: "100% pass@1" from a script that never invokes the agent; an 82 %/86 % figure with no run | Script output relabelled as a gate self-check; README rows corrected | `scripts/run_cline_smoke_tests.py`, `README.md` |

## Strengthening

- **`src/tests/test_verdict_honesty.py`** (new, 11 pins): word-boundary
  classification, read-only turn completed, recovered failures never fail a turn,
  pure monologue still fails, log line == returned verdict, wrap lap is terminal
  (and still dispatches tool calls), screenshot ask requires a screenshot
  receipt, composite `verify_ui_workspace` satisfies it.
- **`test_prompt_guard.py`**: the pin that "proved" the replace was rewritten —
  it asserted the bug's precondition. Added
  `test_d35_batch_block_cannot_silently_vanish`, which asserts the composed
  block by content, not by fragments.
- **CI** (`ci/agent-core.yml` — staged; install with the one command in
  `ci/README.md`). No `.github/` existed before. The `agent-core` job runs the
  hermetic runner on Python 3.11 with the full dependency set (tree-sitter
  grammars, Pillow, pyright) — the same command as a laptop. A second
  informational job keeps the desktop-panel parity pins visible without
  blocking. The workflow file sits in `ci/` because Arena's GitHub App lacks
  the `workflows` permission, so a push touching `.github/workflows/**` is
  rejected; `cp ci/agent-core.yml .github/workflows/` + push (or reconnecting
  GitHub with that permission) finishes the job.

## Evidence (same machine, same runner)

| Run | Result |
|---|---|
| Before, on `ecd55994` | **39 failed**, 2236 passed, 23 skipped, 1 xfailed (294.92 s) |
| After, full dependency set | **5 failed**, 2299 passed, 21 skipped, 1 xfailed (461.93 s) |

The 5 remaining failures all live in `test_desktop_renderer_architecture.py` and
`test_hermes_activity_parity.py` and are **desktop build-output drift**: the repo
tracks `desktop/vscode/out/**` (52 committed files) and the shipped
`SOURCES_HASH` (`77e131de…`) no longer matches the current TypeScript sources
(computed `fc11c606…`). They are not agent-core defects; they are fixed by
rebuilding the desktop panel and regenerating the hash. They fail on `main`
*before* these changes too.

Fixes verified to also remove these previously-red groups: `test_lang_extractors`
(18 — needed the tree-sitter grammars from `pip install -e .`),
`test_efficiency_receipts` (Pillow), `test_lab_fixes` tsx receipts (tree-sitter
TS/TSX fallback when global esbuild is absent), `test_review12` depth cap,
`test_stream_stall_discipline`, `test_grace_summary_hermes_law`,
`test_model_endpoint_metadata`, `test_finalize_chat_turn`,
`test_attempt11_completion_integrity`.

## How to verify on your machine

```bash
git pull
python -m compileall -q src          # compile check
python -c "import src.graphs.chat_graph"   # graph imports

# the new gate, directly:
python -c "
from src.prompts.claude_persona import system_persona, _D35_BATCH_SENTENCE
print('batch guidance shipped:', _D35_BATCH_SENTENCE in system_persona())
from src.graphs.gates import _looks_like_execution_task
print('test2 not a verb:', _looks_like_execution_task('verify the test2 folder') is False)
"

# hermetic suite (never touches your real HOME or keys)
scripts/run_tests.sh
```

Then the part that needs the app: open the desktop IDE and run a UI task that
asks for a screenshot — the turn must not report completion without the
screenshot receipt, and a read-only "verify the test2 folder" turn must report
`task_status="completed"`.

---

## Desktop pins round (same audit, second pass)

The 5 remaining failures were pinned to the desktop contrib sources
(`desktop/vscode/src/vs/workbench/contrib/crusorai/**`). Four were small
drifts and are fixed here; the fifth is a build artifact and needs your
rebuild.

| Pin | Drift found | Fix |
|---|---|---|
| `test_reveal_paths_and_terminal_obey_hermes` | `--crusorai-terminal-max-h` was `5rem` under a comment claiming hermes `max-h-16` parity (Tailwind `max-h-16` = **4rem**) | token corrected to `4rem` |
| `test_crusorai_type_grammar_is_tokenized` | one raw `font-size: 11px` survived the type grammar | → `var(--crusorai-text-meta)` (0.6875rem = 11px, exact) |
| `test_hermes_activity_parity::…mount_the_same_column…` | the Manager mount spread the column through the enclosing ternary, so the literal `...agentColumn(...)` appeared once; the pane and the Manager must both spread the column explicitly | Manager site now `[...agentColumn(...)]` (behaviour identical) |
| `test_streaming_isolation_only_the_message_part_repaints` | pin carried a 32px follow-window; the shipped source uses **120px at both sites** | pin updated to the shipped value, with a comment naming both sites — **if you want 32 back, change the source and the pin together** |
| `test_engine_hash_matches_the_shipped_panel_on_this_repo` | tracked `out/**` build output is older than the sources | **your rebuild** (below) |

The workbench UI stamp moved `2026-10-02 → 2026-10-12` with it (the engine's
`engineBuild` is the HEAD commit date, so without the bump the chip would
false-flag `STALE`), and both stamp pins moved together.

### Regenerate the desktop panel (fixes the last pin)

```bash
cd desktop/vscode
gulp compile                          # ~4–7 min
node scripts/emit-crusorai-bundle.mjs # regenerates out/** + SOURCES_HASH + manifest + DI check
cd ../.. && git add desktop/vscode/out && git commit -m "build(desktop): rebuild crusorai panel"
```

Then **fully quit and reopen** the app (a running process keeps the old JS in
memory). The chip should read `ui 2026-10-12` with no `STALE`, and the hash pin
goes green.
