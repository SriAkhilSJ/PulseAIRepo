# Host test — interrupt as a hand brake, undo on the request row

> Hand this file to the desktop agent along with the branch. It is the whole
> path for **this round only** (2026-10-04): pull → verify → (optionally)
> compile → launch → what to look at → what to send back.
>
> Branch `arena/01a10795-pulseairepo`, tips `226d742c` (code + shipped panel)
> and `47bcdf6e` (blueprints). Read `CRUSOR_PREVIEW_DESKTOP_APP_TEST.md` for
> the standing gate order; this file does not replace it.

The shipped panel under `desktop/vscode/out/` is **committed**. That is what
the app loads at launch — so **you do not need to compile anything to test
this UI**. Compile is only for proving the sources build on your machine, and
it is the step most likely to dirty your tree (§3 says how to undo that).

---

## 1. Pull

```powershell
$ErrorActionPreference = 'Stop'
cd D:\pulseAIagent\PulseAIRepo

$branch = 'arena/01a10795-pulseairepo'
# Fetch this exact remote-tracking ref, including on a fresh clone.
git fetch origin "+refs/heads/${branch}:refs/remotes/origin/${branch}"
if ($LASTEXITCODE -ne 0) { throw 'fetch failed' }

git show-ref --verify --quiet "refs/heads/$branch"
if ($LASTEXITCODE -eq 0) {
    git switch $branch
} else {
    git switch --track --create $branch "origin/$branch"
}
if ($LASTEXITCODE -ne 0) { throw 'could not switch to the Arena branch' }
git pull --ff-only origin $branch
if ($LASTEXITCODE -ne 0) { throw 'pull was not a fast-forward; stop and report' }

git log --oneline -3
```

The history must contain `226d742c` (implementation + shipped panel) and
`47bcdf6e` (blueprint), plus the host-test guide commits above them. The exact
tip can be newer as this guide evolves; the verifier in §2a checks the two
product commits. If `226d742c` is absent, stop and report — nothing below is
meaningful.

Then look at what the pull landed in:

```powershell
git status --porcelain
```

- Empty → good.
- Only `??` lines for notebooks/scratch → ignore them, keep going.
- **Any `M` line under `desktop\vscode\out\`** → your local build is on top of
  the shipped panel. Discard it before testing, or you are testing your build,
  not the pushed one:

  ```powershell
  git checkout -- desktop\vscode\out
  ```

- `M` lines anywhere else → keep them, but say so when you report.

## 2. Verify — keyless, no display, under a minute

### 2a. The panel check (scripts/verify_crusor_interrupt_undo.py)

```powershell
python scripts\verify_crusor_interrupt_undo.py
```

This check is standard-library only — it does not need `.venv` or any `pip install`.

**PASS = `RESULT: all checks passed`**, exit 0, and 88 `PASS` lines. It checks
that the two commits are in your history, that your `out/`
is byte-identical to the committed panel, that the shipped JS/CSS contains
every new class and every dictated string, that the removed vocabulary
(`stopping`, `safely`, `Run cancelled`) is genuinely gone from what ships, and
that the engine side (`checkpoint_restore`, `turn_undo_point`, `[new file]`)
is present.

**If it prints FAIL, do not launch** — paste the FAIL lines back. That script
answering "am I looking at the right build?" is the point; the app cannot tell
you that.

### 2b. The pinned lane

```powershell
.\.venv\Scripts\python.exe -m pytest src\tests\test_desktop_renderer_architecture.py `
    src\tests\test_shadow_checkpoints.py -q
```

**PASS = `81 passed, 1 skipped, 1 xfailed`.** One of those tests
(`test_engine_hash_matches_the_shipped_panel_on_this_repo`) recomputes the
engine's source hash from your checkout and compares it to the shipped
`SOURCES_HASH`; it passing is the machine proof that your sources and the
panel agree, i.e. the pane chip cannot read `STALE` on this tree. If it fails,
report it as a real finding with `git status --porcelain` output — do not
"fix" it by re-emitting unless you changed something.

Broader lane, same pass/fail shape, ~25 s:

```powershell
.\.venv\Scripts\python.exe -m pytest src\tests -q -k "renderer or checkpoint or protocol_v2 or file_state or file_tools or bridge"
```

**PASS = `218 passed, 1 skipped, 1 xfailed, 2076 deselected`.**

Do **not** run the whole suite as a verdict: it has 27 failures that reproduce
on the pre-round commit (`a2c3c9b5`) and have nothing to do with this change.
Chasing them wastes your afternoon.

## 3. Compile — only if you want to prove the sources build

Skip this whole section if 2a and 2b pass. Compiling is not what makes the app
show this UI; `out/` already does. But if you do compile, the order matters
and so does the cleanup afterwards.

```powershell
cd D:\pulseAIagent\PulseAIRepo\desktop\vscode
node --version                 # repo pins 24.18.0; record the version you used
if (!(Test-Path node_modules)) { npm install }
npm run typecheck-client       # must exit 0
npm run valid-layers-check     # browser/ must not reach for electron/node
npm run compile                # several minutes cold
node scripts\emit-crusorai-bundle.mjs
node scripts\audit-preview-pipeline.mjs
```

`compile` rewrites `out/` with **your** toolchain; the emitter then re-emits
the crusorai files and the hashes. Your `tsc` may inline some things (const
enums) slightly differently from the shipped bytes — that is drift, not a
feature. So finish with:

```powershell
git status --porcelain -- desktop\vscode\out
```

Anything listed there is your compiler's handwriting, not this round's.
Discard it so the tree matches what was tested:

```powershell
git checkout -- desktop\vscode\out
```

Then re-run 2a and 2b. (The `SOURCES_HASH` the engine compares at boot is
written by the emitter, so the panel stays current either way — but a dirty
`out/` means the next person cannot tell what you tested.)

## 4. Launch — keyless, guarded

The guard makes the bridge answer locally: no model call, no credential,
no network. Set it in the shell you launch from.

```powershell
cd D:\pulseAIagent\PulseAIRepo
Remove-Item Env:CRUSORAI_ALLOW_LIVE_AGENT_TEST -ErrorAction SilentlyContinue
$env:CRUSORAI_BRIDGE_RUNNER = 'echo'
$env:CRUSORAI_ECHO_DELAY_MS = '3000'      # slow the echo turn down so the brake is reachable

cd desktop\vscode
.\scripts\code.bat "D:\work\your-project"
```

**Quit and relaunch if the app was already open** — a running process keeps
the old JS in memory and will show you the previous round with no hint that
anything is wrong.

## 5. What to look at — the evidence

Work down the table with the app in front of you. "Send" = paste the pane text
for that row.

| # | Do this | Pass looks like | If it fails |
| --- | --- | --- | --- |
| 1 | Look at the engine chip at the bottom of the pane | `ui 2026-10-04`, no `STALE` | `STALE` or an older date = `out/` is not this round; go back to §2a |
| 2 | Send any prompt with the delay set, then look at the composer | send slot is a solid **square**; hover reads `Interrupt — stops now`; the hint bar shows `Esc to interrupt` | send arrow still there = not this round's renderer |
| 3 | Pull it mid-turn (click the square) | the moment it lands: the assistant row reads **`Interrupted.`**, a **cut mark** sits on the last frame, and the receipt says `Interrupted` with landed/dropped counts. **No** "stopping", no wind-down, no question asked | any transitional wording or a confirm dialog = a real finding, send it |
| 4 | Same, with the keyboard: press `Esc` while a turn runs | identical to row 3 | nothing happens = Esc-handler finding; send it |
| 5 | While a clarify form is open, press `Esc` | the form closes, the turn is **not** interrupted (designed precedence) | turn cut instead = send it |
| 6 | Hover **the user bubble** of a finished request (row hover, no click) | a hairline pair fades in **under the user's message** with `↩ Undo turn` and `Fork from here`; invisible at rest | control on the assistant receipt instead = wrong anchor, send it |
| 7 | Click `Undo turn` | the button becomes a split pill: shimmering **confirm** + `✕`. `✕` restores the button untouched — nothing happens to the tree | pill missing = §2a was not green |
| 8 | Confirm it | the tree goes back to just before that turn; the line reads `Checkpoint restored · <hash>` and offers **`Put it back`** | send the line you got |
| 9 | Click `Put it back` | the pre-restore state is returned (the undo is itself undone) | send it |
| 10 | On the changed-files card: `Undo All Edits` | same split pill; a file the turn **created** carries a `[new file]` marker | send it |
| 11 | Send a second prompt while the first runs | a `Queued · …` chip appears — no silent drop | silent drop = real finding, send it |

The two blueprint pages are static and self-contained — double-click them, no
build and no server: `blueprints\copilot-revert-interrupt.html` (how Copilot
does it; what was asked for) and
`blueprints\crusor-interrupt-undo-implementation.html` (the shipped F1–F6
frames, live states, wire JSON, and the exact code excerpts). If a frame in
the second page disagrees with the app, the page is the bug — tell me which
frame and I will re-cut it.

## 6. Report back — the short version

1. `git log --oneline -2` output.
2. §2a last line, and the pytest counts from §2b (yours, not the expected).
3. The chip line from the app (`ui …`).
4. For anything off: which row of §5, what you did, what you saw — pane text,
   not a summary.

## 7. What this round does **not** claim

So you do not spend time on ghosts:

- `Fork from here` has its wire path and unit pins, but has **never been
  driven end-to-end in the app**. Row 6 only checks that the control appears
  in the right place. Treat a real fork as untested territory, not a bug.
- `hideCheckpoints` can lose a race against the checkpoint-list reply; the
  checkpoint log's open/closed state can therefore be stale for one frame.
- A `turn_done` arriving after the freeze is a no-op — correct for now, but
  the interaction is not pinned.
- `TOOL_ICON_PATHS` membership for the `history`/`clock`/`warning` glyphs is
  unverified; a missing path renders as a blank slot, not an error.
- The 27 suite-wide failures from §2b's warning are pre-existing (they
  reproduce on `a2c3c9b5`, before this round).
