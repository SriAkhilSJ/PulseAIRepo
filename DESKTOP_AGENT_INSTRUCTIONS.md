# Desktop Agent Instructions — Manager session registration (fork craft, step 1)

**Updated:** 2026-09-02
**Required branch:** `arena/01a0564d-pulseairepo`
**Required HEAD to verify:** `f7815e473` — "manager: register Pulse as a session provider, not as a second UI"
**Evidence directory:** `bench-results/pulse-manager-registration-desktop`
**Appendix (checklists, console snippet, known gaps):** `docs/DESKTOP_MANAGER_REGISTRATION_VERIFY.md`
**Open PR:** none — do not open, merge, or delete anything

## Budget: 80 credits remain. Spend them like that.

* Run gates A → B → C → D **in order**, and **stop at the first failure**. A failure is the result.
* Each gate runs **once**. No flake re-runs, no second attempt after a fix, no "let me try again".
* Do not run the whole `src/tests` suite or `yarn test`/`yarn compile --watch`. Nothing here needs them.
* Do not paste logs to me except the named files' last 20 lines; the evidence push carries the rest.
* If the environment lacks node/`.venv`/`esbuild`, that is a reportable host gap — say so and stop. Do not
  reinstall the world to make a check go green.

## Authorization and stop rules

This is a provider-free type/build/CDP validation of the Manager's session registration. No provider
request, probe, fallback, live Test 5 turn, paid completion, credential inspection, merge, or branch
deletion is authorized.

Use only the existing repository at `D:\pulseAIagent\PulseAIRepo`. Do not clone, reset, clean, amend
source, or touch historical evidence. Set `PULSEAI_BRIDGE_RUNNER=echo` before launching the IDE — that is
the mandatory network/provider guard. **Never** set `PULSEAI_ALLOW_LIVE_AGENT_TEST=1`
(`Remove-Item Env:PULSEAI_ALLOW_LIVE_AGENT_TEST -ErrorAction SilentlyContinue`). Do not edit any source
file, including to fix a failing gate: report it, push the evidence, stop.

## 1. Establish the exact clean source

```powershell
$ErrorActionPreference = 'Stop'
cd D:\pulseAIagent\PulseAIRepo
if ((git branch --show-current) -ne 'arena/01a0564d-pulseairepo') { throw 'Wrong branch — STOP' }
# Tracked changes are the only thing that can corrupt a run. Untracked scratch cannot, and this
# repo has known, already-accepted untracked files (see the note below), so they are inventoried
# into the evidence rather than blocking the gate or being committed.
if (git status --porcelain=v1 -uno) { throw 'Tracked files are modified — preserve them and STOP' }
git fetch origin arena/01a0564d-pulseairepo
git merge-base --is-ancestor f7815e473 FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw 'The registration slice is not an ancestor — STOP' }

$evidence = 'bench-results\pulse-manager-registration-desktop-r2'
if (Test-Path $evidence) { throw 'Evidence directory already exists — STOP; never overwrite or retry' }
New-Item -ItemType Directory -Path $evidence | Out-Null

# Then inventory the untracked scratch, and refuse anything outside the accepted list.
git status --porcelain=v1 | Set-Content "$evidence\untracked-inventory.txt" -Encoding utf8
$known = 'pulse-webview/live-failure.spec.ts', 'sitecustomize.py'
$unexpected = (git status --porcelain=v1 | ForEach-Object { $_.Substring(3).Trim('"') } |
  Where-Object { $known -notcontains $_ })
if ($unexpected) { "Untracked, not on the accepted list: $unexpected" | Tee-Content "$evidence\untracked-note.txt" }
# Scratch at the root is a note. Untracked *source-shaped* code can change what is being verified,
# so it stops the run and is reported rather than run over.
$suspicious = $unexpected | Where-Object { $_ -match '^(desktop/vscode/src|src/|pulse-webview/src/)' }
if ($suspicious) { throw "Untracked source-shaped file present: $suspicious — STOP and report it" }
git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding ascii
git log --oneline -6        | Set-Content "$evidence\recent-commits.txt" -Encoding utf8
node --version              | Set-Content "$evidence\node-version.txt" -Encoding utf8
```

`git pull --ff-only` only if step 1's ancestor check fails; never `--rebase`, never a hard reset.

**Write every evidence file as ASCII** (`Set-Content -Encoding ascii`, and `... | Out-File -Encoding ascii`
instead of `Tee-Object` for logs). Windows PowerShell's `Tee-Object` defaults to UTF-16, which made round 1's
`gate-a-tsc.txt` a 60 KB binary blob in the diff — hashed and unreadable. Decoding it by hand confirmed
`Pulse errors: 0` on your host, but evidence has to be checkable without a decoder.

**Why `-uno` and an allowlist, in one line:** `pulse-webview/live-failure.spec.ts` is scratch from the
*live* e2e round and is already recorded as accepted-untracked in this repo's own findings
(`bench-results/prompt-ui-live-e2e/findings.md:3-4`, "untracked, not modified… noted and accepted"). It is
not in the tree I have, so nobody here can vouch for its bytes, and committing live-provider scratch into
the source tree is not how a verification round ends. `vitest.config.ts` collects only
`src/__tests__/**/*.test.{ts,tsx}`, so it is never executed by `npm test` either: leave it alone, list it.
A round-2 evidence directory is used because the first round's is evidence too, and evidence is never reused.

## 2. Gate A — strict scoped typecheck (proves the registration satisfies the fork's contracts)

```powershell
cd D:\pulseAIagent\PulseAIRepo\desktop\vscode\src        # this directory, or the paths shift
$tsc = if (Test-Path ..\node_modules\.bin\tsc) { '..\node_modules\.bin\tsc' } else { '..\..\..\pulse-webview\node_modules\.bin\tsc' }
& $tsc -p tsconfig.pulseai-check.json --noEmit 2>&1 | Out-File -Encoding ascii "$PWD\..\..\..\$evidence\gate-a-tsc.txt"
$log = "$PWD\..\..\..\$evidence\gate-a-tsc.txt"
# Unanchored on purpose, and coverage asserted separately. `^vs/workbench/contrib/pulseai` matched
# nothing when the command ran from desktop\vscode, because tsc then prints `src/vs/...` -- so for four
# rounds gate A reported "0" whether the tree was clean or not, and TS2459 in pulseAISessionController.ts
# walked straight through it to reach npm run compile. A grep that cannot match is not a clean build.
$mine  = (Select-String -Path $log -Pattern 'contrib/pulseai' | Where-Object Line -match 'error TS').Count
$total = (Select-String -Path $log -Pattern 'error TS').Count
$files  = (& $tsc -p tsconfig.pulseai-check.json --noEmit --listFilesOnly 2>$null | Select-String 'contrib/pulseai').Count
"Pulse errors: $mine   all errors: $total   Pulse files in program: $files"
if ($files -lt 26) { throw "Gate A has no coverage ($files Pulse files in the program) — STOP, this is not a pass" }
```

**PASS = `Pulse errors: 0` AND `Pulse files in program >= 26`.** Other errors are expected (missing
`@types` in a partial checkout) and are not failures. Never judge this lane by a total of zero: an
empty log means the compiler or the filter failed, and that is a STOP. Non-zero → skip
everything below, go to step 5.

## 3. Gate B — the two python lanes that cover this slice

```powershell
cd D:\pulseAIagent\PulseAIRepo
.\.venv\Scripts\python.exe -m pytest src\tests\test_pulse_session_registration_parity.py src\tests\test_desktop_renderer_architecture.py -q 2>&1 |
  Tee-Object "bench-results\pulse-manager-registration-desktop\gate-b-pytest.txt"
```

**PASS = zero failures/errors**, and `test_pulse_session_registration_parity.py` contributing **8 passed**.
Both harness assumptions are gone. `src/tests/_node_loader.py` probes candidates and keeps the first one
that runs `--version`: `.bin/esbuild`, `.bin/esbuild.cmd`, `@esbuild/<platform>/bin/esbuild.exe`,
`@esbuild/<platform>/esbuild.exe`, `esbuild/bin/esbuild` — which is where the real binary lives when
`node_modules` was installed on another platform and `.bin` is a POSIX script. If none of those execute,
the registration lane falls back to `typescript\bin\tsc` (plain JS, no native binary) and the two Hermes
lanes skip. Round 1 died on the shim, round 3 on the same shim in the other two files; both shapes are now
pinned at source level, so a future edit cannot reassume them.

`*skipped*` is a host gap to report, never a pass and never something to chase with a reinstall.

Evidence goes to `bench-results\pulse-manager-registration-desktop-r3` — the r2 directory is the record of
gate A passing and the harness failing, and evidence is never overwritten. Put one line in r3's `gate.txt`:
`gate A carried forward from r2/gate-a-tsc.txt (sha256 in r2/sha256sums.txt)`.

## 4. Gates C and D — build, then the paint

One command covers the launch, the harness and the row extraction -- use it instead of building
`Start-Process` argument lists by hand, because Chromium flags take their value with `=` and a bare path
after `--user-data-dir` becomes a positional that the build reads as "what to load", not "the folder to
open" (that mistake ended round 5, and the workbench looked broken when only the argv was).

```powershell
cd D:\pulseAIagent\PulseAIRepo
node scripts\verify_pulse_manager_registration.mjs "bench-results\pulse-manager-registration-desktop-r4\cdp"
```

Then follow Follow `docs/DESKTOP_MANAGER_REGISTRATION_VERIFY.md` §C and §D verbatim: `npm install` (only if
`desktop\vscode\node_modules` is absent) → `npm run compile` → launch
`.\desktop\vscode\.build\electron\PulseAI.exe --remote-debugging-port=9222` on a fresh
`--user-data-dir` → `node scripts\validate_pulse_ui_cdp.js bench-results\pulse-manager-registration-desktop\cdp --manager-only`
→ the Developer-Tools console object for `.pulseai-session-row` (the doc prints the exact snippet).
Every PASS line and every mismatch is written into `gate-d-findings.md` in the evidence directory.

Read `cdp-ui-result.json` (that is the harness's report filename) rather than trusting the console.

## 5. Evidence, hashes, commit, push — on PASS *and* on FAIL

```powershell
cd D:\pulseAIagent\PulseAIRepo
$evidence = 'bench-results\pulse-manager-registration-desktop-r2'
Set-Content "$evidence\gate.txt" -Value "reached: <A|B|C|D>; result: <PASS|FAIL>; first failure: <gate + one line>" -Encoding utf8
Get-ChildItem $evidence -Recurse -File | Where-Object Name -ne 'sha256sums.txt' | Sort-Object FullName |
  ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    "$hash  $([IO.Path]::GetRelativePath((Resolve-Path $evidence), $_.FullName).Replace('\','/'))"
  } | Set-Content "$evidence\sha256sums.txt" -Encoding ascii
git status --short          # ONLY the evidence directory may appear
git add -f $evidence
git commit -m "evidence(desktop): manager session registration — <PASS|FAIL at gate X>"
git push origin HEAD:arena/01a0564d-pulseairepo
```

`bench-results\` is gitignored, so `-f` is required. If `git status --short` shows any source, test,
lockfile or historical-evidence change, **do not commit it** — leave it in the tree, commit only the
evidence directory, and say what is dirty. Never `git stash`, `git clean`, `git reset --hard`, or
`git push --force`.

Report: which gate stopped it, `gate.txt`, `sha256sums.txt`, the evidence commit SHA, and the last 20
lines of the failing gate's log. Then stop. Do not open or merge a PR, do not delete a branch, do not
retry, and do not upgrade a build PASS over a CDP FAIL.
