# Permission handling in the desktop agent — quality assessment

Scope: how consent works when Pulse writes files **inside the VS Code fork**, plus the state of
Ask/Plan modes, the Manager surface, and the CopilotKit view. Written against `main` as of
`9af0009b`+this commit. Every claim names a file and line; anything I could not verify is in
"Open" with the reason.

## The rule

Consent is decided by the **path**, not by which tool the model happened to pick:

```
ignored by git          -> consent required, every time (no session grant accepted)
tracked / not ignored   -> the agent goes alone, no prompt
no git able to answer   -> the pre-existing verdict, unchanged
```

Implemented in `src/context/safety_guard.py` (`_consent_for`), consulted for `write_file`,
`edit_file`, and `copy_file` on **both** `src` and `dst`. `git check-ignore` is the oracle
(nested `.gitignore`, `.git/info/exclude`, `core.excludesFile`, `!` negations) and is deliberately
*not* `--no-index`: a force-committed file is tracked, so git can restore it, so it must not gate.
A named-secret / `.git` / `.ssh` veto runs **before** git is consulted, so "tracked" relaxes
friction and never secrets.

## Strong

| thing | evidence |
|---|---|
| One rule for all mutating tools; no tool-choice bypass | `safety_guard.py::PATH_ARGS`, `_consent_for`; 18 behavioural tests in `src/tests/test_safety_guard_consent.py` on real `git init` fixtures |
| Session-scoped grants are real, not decorative | `safety_reply { always_allow }` → `src/bridge/__main__.py:552` → `src/dashboard/event_bus.py:145,152`; and the *engine* still re-asks for the never-auto class because the guard returns `False` before scope is considered |
| Autonomous runs degrade instead of deadlocking | `chat_graph.py:2765+`: a flagged call becomes a denial `ToolMessage` telling the model to pick another path and **not wait for approval**; safe calls in the same batch still execute |
| Reversible work is not interrupted | tracked-file overwrite needs no prompt and no env flag; `PULSEAI_AUTO_APPROVE_WRITES` keeps its old meaning for eval lanes |
| Approval surface is theme-safe and state-labelled | `pulseAIRenderer.ts::approvalDock`, states `queued/running/passed/approval/failed` (`:11`), `--pulseai-approval` amber token, `shield` glyph |
| Undo exists per mutation | `checkpoint_before_mutation` in `file_tools.py`, and the renderer host exposes `restoreCheckpoint` (`pulseAIRenderer.ts::PulseAIRenderHost`) |
| Guard is argument-level, never prompt-level | documented at the top of `safety_guard.py`; `check_tool_call` sees only `tool_args` |

## Fixed in this commit (fork side, `desktop/vscode/.../pulseai/`)

1. **"Allow for session"** now exists. `replyToSafety(toolId, approved, alwaysAllow?)` has carried the
   third argument since the start and the bridge honours it, but the dock sent only `true`/`false` —
   so the grant was unreachable from the UI and every ordinary write re-prompted. Dock now offers
   `Allow once` / `Allow for session` / `Deny`, each with an icon and a `title` explaining its scope.
2. **Green/red by meaning.** `Allow once` = button primary + `--vscode-testing-iconPassed`; `Deny` =
   `--vscode-testing-iconFailed` border/tint; `Review change` secondary. Previously Allow was
   indistinguishable-in-kind from Review (both secondary) and nothing about a denial read as one.
3. **Diff lines are tintable.** `.pulseai-diff-preview` was a single `<pre>` of text — no per-line
   colour was possible — now `diffPreview()` emits one node per line with `is-added` / `is-removed` /
   `is-meta`, coloured with the *editor's own* diff tokens (`--vscode-diffEditor-insertedTextBackground`,
   `removedTextBackground`), so the pane and the native diff cannot disagree about what an added line
   looks like. Clamped to 40 lines **for paint**, with a row saying how many it hid and pointing at
   `Open native diff` for the whole thing.
4. **Two invented values deleted.** The file-write card showed `+12 −4` whenever the engine sent no
   `change` field, and always showed `Receipt: syntax valid`. Line counts are now **counted** from the
   diff that arrived (`diffStats`, `undefined` when there is no diff body → renders `—`), and the
   receipt row only appears if the tool reported one. A placeholder the user can't distinguish from a
   measurement is worse than a blank.
5. **The CopilotKit view works off a dev server.** `pulseAIViewPane.ts` hardcoded
   `src='http://localhost:5173'` at a fixed `height:50%`. On a packaged build, a remote/WSL window
   (where `localhost` is the client), a taken port, or a forgotten `npm run dev`, that is an empty
   frame — and the native renderer still surrendered half the pane to it. Now three settings:
   `pulseai.copilotWebview.enabled` (off ⇒ native view gets 100%), `.url`, `.height`, plus an
   in-pane "not answering at <url>" notice with a Reload and the exact fix. Declared in
   `pulseAI.contribution.ts` so they are discoverable in Settings, not tribal knowledge.
6. **Native view has a designed empty state** (`emptyState` + starter prompts). `function emptyState`
   was *required* by the fork's own architecture pin and **red at base `86eaaae2`** — an empty
   transcript rendered as an empty lane. It now mirrors the ported webview's
   `hermes-ui/components/empty-state.tsx`, and only shows when nothing is broken (engine setup errors
   and workspace-selection states keep their own surfaces).
7. **`Review` → `Review change`**, the label the same pin asked for.

Also in this commit, in the pin file `src/tests/test_desktop_renderer_architecture.py`:
the `ui/src` catalog pin **skips with a stated reason** (that tree is not tracked in this repo, so
the test can never compare anything), and the three new fork pins (webview settings, session-scope
grant, counted-not-placeholder rows) fail on any regression.

## Modes, measured

| mode | what actually happens | verdict |
|---|---|---|
| `ask` | `chat_graph.py:797` inserts an ASK MODE prefix **and** `_drop_tool_pairs()` so a resumed Agent session can't smuggle old tool pairs into a no-tools turn; `after_task_manager` routes straight to `ai`; `should_continue` finalizes even if the model emits an unsolicited tool call | real, and the only mode with a *removal* guarantee. Pinned in `src/tests/test_execution_modes.py` |
| `plan` | `after_task_manager → planner`, `after_planner → plan_preview` (a preview the user approves before execution) | **not inert** — correcting an earlier claim of mine. Gap: the ported `build_plan_prompt` text (`src/prompts/hermes/plan_learn.py`) has no runtime caller; the planner has its own prompt |
| `debug` | `:808` DEBUG MODE prefix: reproduce → diagnose → smallest fix → rerun the strongest check | real prefix, no routing change |
| `agent` | default: full pipeline, tools declared | baseline |

The fork's chip is wired properly: `modePicker` → `setMode` (`pulseAIRendererService.ts:95`) →
`{ type:'prompt', …, mode: this.mode }` (`:478`), and mode is locked while a turn runs.

## Open — owner decisions

1. **Two Manager surfaces.** The in-pane `Manager` button calls
   `pulseAIRendererService.openManagerWindow()` (`:325`), which opens an **auxiliary window** and
   hand-builds a root with class `pulseai-manager-editor`; the `pulseai.openManager` **command**
   (`pulseAI.contribution.ts:190-201`) opens the registered `PulseAIManagerEditor`, whose DOM
   carries `.pulseai-manager-shell` — the selector `scripts/validate_pulse_ui_cdp.js:218-239` waits
   for. So a Phase-4 run that reaches Manager through the *button* times out on a UI that is
   genuinely on screen. Pick popup-or-tab and route one through the other
   (`executeCommand(PulseAICommandId.OpenManager)`); the pin
   `test_agent_layout_keeps_progressive_disclosure_and_stable_docks_native` is left **red on purpose**
   until that choice is made, with the reason inlined. *(Disclosure: I first read the command as a
   no-op because my `sed` window ended at line 200 — `openEditor` is on `:201`. It works.)*
2. **Reads are not consent-gated.** `read_file` / `search_code` of an ignored secret rely on
   `file_safety.get_read_block_error`, not on this rule; `copy_file`'s read side is now checked only
   because I added it to the mutation map. Decide whether "read of a git-ignored file" is a consent
   event (it is how secrets leave a machine) or stays an editor-level policy.
3. **`/plan` prompt text.** Either prepend `build_plan_prompt(task, target_path=plan_target_path(task))`
   to the plan-mode turn (**as a user-turn message, never a system prefix** — the port's cache
   contract in `plan_learn.py`'s docstring), or delete the unused builder.
4. **Nothing here is visually verified.** The fork has no `node_modules` in this checkout and no
   browser binary exists in the sandbox (`npx playwright install chromium` → `ECONNRESET` to
   `cdn.playwright.dev`), so: no screenshot, no painted pixel, and **the fork TS is not
   typechecked** — only transpile-clean (`tsc.transpileModule` over all three edited files). The
   first `yarn && yarn compile` on the laptop is the real gate for those files.

## Runbook for the laptop

```powershell
cd pulse-webview
npm install; npm run dev                      # :5173  (or set pulseai.copilotWebview.url to a build you serve)
npm run runtime                               # :8200  (needs the engine below)
cd ..
.venv\Scripts\python.exe -m uvicorn src.server:app --host 0.0.0.0 --port 8123
node scripts\ui_stack_smoke.mjs               # expect: 5/5 hops healthy
.venv\Scripts\python.exe -m pytest src\tests\test_desktop_renderer_architecture.py -q
```

For the fork window itself: `"window.commandCenter": true` and `"window.titleBarStyle": "custom"` in
the test profile's `settings.json` (the CDP opener lives in the custom title bar — its absence, not
a UI defect, is what blocked the last round), then launch
`desktop\vscode\scripts\code.bat $repo --user-data-dir=$profile --remote-debugging-port=9222`.
Settings to know: `pulseai.copilotWebview.enabled/.url/.height`,
`PULSEAI_SAFETY_GITIGNORE=0` (revert the consent rule to its previous behaviour for one run),
`PULSEAI_ALLOW_LIVE_AGENT_TEST` (never set it: that is the paid-turn gate).
