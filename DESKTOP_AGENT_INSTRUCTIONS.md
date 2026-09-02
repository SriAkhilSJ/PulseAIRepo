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
if (git status --porcelain=v1) { throw 'Checkout is not clean — preserve it and STOP' }
git fetch origin arena/01a0564d-pulseairepo
git merge-base --is-ancestor f7815e473 FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw 'The registration slice is not an ancestor — STOP' }

$evidence = 'bench-results\pulse-manager-registration-desktop'
if (Test-Path $evidence) { throw 'Evidence directory already exists — STOP; never overwrite or retry' }
New-Item -ItemType Directory -Path $evidence | Out-Null
git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8
git log --oneline -6        | Set-Content "$evidence\recent-commits.txt" -Encoding utf8
node --version              | Set-Content "$evidence\node-version.txt" -Encoding utf8
```

`git pull --ff-only` only if step 1's ancestor check fails; never `--rebase`, never a hard reset.

## 2. Gate A — strict scoped typecheck (proves the registration satisfies the fork's contracts)

```powershell
cd D:\pulseAIagent\PulseAIRepo\desktop\vscode
$tsc = if (Test-Path .\node_modules\.bin\tsc) { '.\node_modules\.bin\tsc' } else { '..\..\pulse-webview\node_modules\.bin\tsc' }
& $tsc -p src\tsconfig.pulseai-check.json --noEmit 2>&1 |
  Tee-Object "$PWD\..\..\$evidence\gate-a-tsc.txt" | Out-Null
$mine = Select-String -Path "$PWD\..\..\$evidence\gate-a-tsc.txt" -Pattern '^vs/workbench/contrib/pulseai'
"Pulse errors: $($mine.Count)"
```

**PASS = `Pulse errors: 0`.** Errors in other paths are expected (missing `@types` in a partial checkout)
and are not failures — only lines beginning `vs/workbench/contrib/pulseai` count. Non-zero → skip
everything below, go to step 5.

## 3. Gate B — the two python lanes that cover this slice

```powershell
cd D:\pulseAIagent\PulseAIRepo
.\.venv\Scripts\python.exe -m pytest src\tests\test_pulse_session_registration_parity.py src\tests\test_desktop_renderer_architecture.py -q 2>&1 |
  Tee-Object "bench-results\pulse-manager-registration-desktop\gate-b-pytest.txt"
```

**PASS = zero failures/errors**, and `test_pulse_session_registration_parity.py` contributing **8 passed**
(not 8 *skipped* — a skip means `node` or `pulse-webview\node_modules\.bin\esbuild` is missing, which is a
host gap to report, not a pass). These 8 execute the projection in node; they are the proof that the
lifecycle mapping, elapsed/attention rules and the `pulseai:` session URI round-trip behave, not just
that someone wrote the words.

## 4. Gates C and D — build, then the paint

Follow `docs/DESKTOP_MANAGER_REGISTRATION_VERIFY.md` §C and §D verbatim: `npm install` (only if
`desktop\vscode\node_modules` is absent) → `npm run compile` → launch
`.\desktop\vscode\.build\electron\PulseAI.exe --remote-debugging-port=9222` on a fresh
`--user-data-dir` → `node scripts\validate_pulse_ui_cdp.js bench-results\pulse-manager-registration-desktop\cdp --manager-only`
→ the Developer-Tools console object for `.pulseai-session-row` (the doc prints the exact snippet).
Every PASS line and every mismatch is written into `gate-d-findings.md` in the evidence directory.

Read `cdp-ui-result.json` (that is the harness's report filename) rather than trusting the console.

## 5. Evidence, hashes, commit, push — on PASS *and* on FAIL

```powershell
cd D:\pulseAIagent\PulseAIRepo
$evidence = 'bench-results\pulse-manager-registration-desktop'
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
