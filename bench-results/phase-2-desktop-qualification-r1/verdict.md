# Phase 2 desktop production qualification r1 — verdict

**Verdict: `DESKTOP_PARTIAL`**

The actual Electron application builds, launches, starts its Python worker,
speaks Bridge Protocol v2, binds the right workspace, renders Agent and Manager,
handles approvals, cancels an active turn, survives a worker kill, and replays a
live session without duplicates. It does **not** meet the pass bar because four
committed focused tests fail, one approval-dock layout defect breaks the primary
action at default width, cancellation has a pre-turn race, and several required
scenarios were only reachable through a process-boundary test double.

This is not whole-product production readiness and it is not a statement about
the Python Agent Core.

## Provenance

| Item | Value |
|---|---|
| Branch | `feat/prompt-cache-stabilization` |
| Starting HEAD | `e9b6ee02dbe75497353f4d62b12d5ff38ac4b5d3` |
| Origin at start | identical |
| Desktop source dirty? | no (`git status -- desktop/vscode/src` empty) |
| Pre-existing dirty entries | 175 at handoff; 184 at this run's snapshot, all preserved |
| Evidence dir | created new; no overwrite of prior runs |

The tree grew from 175 to 184 entries before this run (user work in
`src/tools/*`, memory layer, and untracked files). Nothing was reset, cleaned,
stashed, rebased or force-pushed. Only named evidence files were staged.

## Commands executed

```
python -m pytest src/tests/test_bridge_protocol_v2.py \
  src/tests/test_desktop_renderer_architecture.py \
  src/tests/test_crusor_session_registration_parity.py \
  src/tests/test_preview_contract.py \
  src/tests/test_crusor_file_icons.py -q
python scripts/generate_bridge_protocol.py --check
npm run typecheck-client                (desktop/vscode)
npm run compile-client                  (desktop/vscode)
CrusorAI.exe . --user-data-dir=... --extensions-dir=... --remote-debugging-port=... ...
python logs/bridge-probe.py <workspace>
node logs/cdp-drive.mjs                 (CDP evaluation/screenshot driver)
```

## Gate results

| # | Gate | Result | Evidence |
|---|---|---|---|
| 1 | Source provenance | PASS | `head.txt`, `branch.txt`, `git-status.txt` |
| 2 | Focused provider-free tests | **FAIL — 4 failed, 148 passed, 7 skipped, 1 xfailed** | `focused-tests.txt` |
| 3 | Protocol/generated types agree | PASS | `protocol-validation.txt` |
| 4 | Desktop typecheck | PASS (exit 0) | `typecheck.txt` |
| 5 | Desktop compile | PASS (exit 0, 597.99 s) | `compile.txt` |
| 6 | Actual Electron launch | PASS | `electron-launch.txt`, screenshots |
| 7 | Worker + bridge v2 handshake | PASS | `worker-bridge.txt`, `logs/bridge-probe.out.txt` |
| 8 | Workspace/session binding | PASS | `workspace.bound` frame; Manager breadcrumb |
| 9 | Agent surface renders | PASS | `agent-ui.txt` |
| 10 | Manager surface renders | PASS | `manager-ui.txt` |
| 11 | Native approval flow | PARTIAL (PASS via engine stub; dock layout FAIL) | `approval-flow.txt` |
| 12 | Cancellation | PARTIAL (active turn PASS; pre-turn race FAIL) | `cancellation.txt` |
| 13 | Session replay | PARTIAL (warm PASS; cold transcript NOT EXERCISED) | `session-replay.txt` |
| 14 | Worker recovery | PASS (single bounded restart) | `worker-recovery.txt` |
| 15 | Visual acceptance from screenshots | PASS with one HIGH defect | `visual-findings.md` |
| 16 | No unexplained critical runtime errors | PASS with recorded non-fatal startup errors | `electron-launch.txt` |

### First blocking failure (recorded, not fixed)

`src/tests/test_desktop_renderer_architecture.py` fails in committed source with
four structural assertions:

1. `test_agent_layout_keeps_progressive_disclosure_and_stable_docks_native`
   — missing `host.submitPrompt(value)`.
2. `test_execution_mode_picker_is_functional_and_theme_driven`
   — missing `this.send({ type: 'prompt'`.
3. `test_crusorai_type_grammar_is_tokenized`
   — raw sizes `11px`, `10px`, `12px`, `10px`.
4. `test_tool_cards_follow_opencode_basictool`
   — missing `presentation.family === 'subagent' ? [] : toolArgsChips(tool)`.

The working tree's desktop source is clean, so these are real defects in the
committed HEAD, not local edits. Per the task, no production code was changed to
make them pass.

## Scenario matrix (runtime)

| Scenario | Result | Note |
|---|---|---|
| A. Workbench startup | PASS | all workbench parts; no crash/boot loop |
| B. Worker and bridge | PASS | v2 hello, session create, exact workspace, frames painted |
| C. Agent interface | PASS | echo turn, running/completed/failed/cancelled distinct, no duplicates |
| D. Manager interface | PASS | shared store, correct counts/labels, consistent with Agent |
| E. Approval workflow | PARTIAL | allow/deny/pairing PASS via engine stub; dock clips `Allow once` |
| F. Cancellation | PARTIAL | active turn stops truthfully; cancel during startup is dropped |
| G. Session replay | PARTIAL | warm replay duplicate-free; cold message replay not exercised |
| H. Worker recovery | PASS | one supervised restart, handshake re-established, next turn works |

## Exact limitations

1. **Focused tests fail** in committed source (4 renderer-architecture tests).
   No runtime pass is claimed from source-level tests and vice versa.
2. **Approval tool execution not exercised.** The approval frames came from a
   one-file protocol stub at the engine process boundary. Renderer, utility
   process, framing and approval UI were real.
3. **Cancellation race.** `Escape` before the turn becomes active returns
   `accepted=False turn_elapsed=None` and the prompt still runs. Measured with
   the 6 s echo delay.
4. **Cold replay.** The echo seam writes no durable transcript
   (`session_messages` = 0), so a cold restart restores the session row but an
   empty transcript. Long-transcript replay and tool start/end pairing across a
   cold boot are NOT EXERCISED.
5. **Echo test seam is not visibly labelled** in the transcript; the reply looks
   like a normal answer.
6. **Light theme NOT EXERCISED.** The dev theme picker listed marketplace themes
   only and a profile `workbench.colorTheme` write was reset on reload.
7. **Ctrl/Cmd+L did not open the panel** in this CDP-driven session; the command
   palette command did. The keybinding is registered but was not proven at the
   input layer here.
8. **Restart bounds not measured.** One kill produced one restart; backoff,
   attempt caps and in-flight-turn recovery were not measured.
9. **Owner-profile side effect from launch 1.** The Python sidecar stores under
   `Path.home()`, so the first reconnaissance launch wrote to the machine's real
   `%USERPROFILE%\.crusorai` (sessions.db-WAL + traces timestamps). Launches 2-3
   used an isolated `USERPROFILE`/`HOME`. No owner session was read or deleted;
   one disposable-workspace session row was added before isolation was applied.
10. **Build artifacts.** `npm run compile-client` rewrote 15 tracked
    `desktop/vscode/out/**` files; they were restored with
    `git checkout -- desktop/vscode/out` and are not part of the evidence commit.
11. Startup logs contain four non-fatal errors (native-is-elevated optional
    module, built-in chat contribution DI, `agentHostClientProxy` channel,
    crashpad registration). None blocked the workbench; they are product
    defects/limitations outside this qualification's scope.
12. No provider call, no API-key inspection, no live agent test,
    `CRUSORAI_ALLOW_LIVE_AGENT_TEST` removed from the child environment.

## Evidence hygiene

- Workspace, user-data, extensions and `USERPROFILE` were disposable copies under
  the session temp directory; the owner's normal profile/workspace was not used
  (except as noted in limitation 9).
- Absolute personal paths in the committed logs are replaced with `<REPO>`,
  `<TEMP>`, `<USERPROFILE>`.
- No `.env` file, credential dump or API key value is included.
- Screenshots contain only the disposable `workspace` fixture (`hello.txt`,
  `notes.md`).

## Release decision

`DESKTOP_PARTIAL`. The native desktop path is demonstrably functional for
provider-free startup, worker/bridge, workspace binding, Agent/Manager rendering,
approvals, cancellation of an active turn, worker restart and warm replay, but
it is not qualified: committed renderer tests fail, the approval dock clips its
primary action, cancellation has a startup race, and cold transcript replay plus
real tool approval remain unproven.
