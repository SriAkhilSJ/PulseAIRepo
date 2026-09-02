# Desktop verification — Manager session registration (step 1)

**For:** the owner's Windows laptop, real VS Code fork (`PulseAI.exe`) + real Copilot Chat.
**Entry point:** `DESKTOP_AGENT_INSTRUCTIONS.md` (authorization, budget, evidence push). This file is the appendix:
the exact PASS lines, the console snippet, and the deliberate gaps.
**Sandbox status of this slice:** `f7815e473`, pushed to `arena/01a0564d-pulseairepo`. Type-checked and
behaviour-tested here (see `bench-results/hermes-prompt-ui-copilotkit-verification/pulseai-registration-step1.log`);
**not built, not painted** — this sandbox has no `yarn install`, no bundler, no chromium. That gap is
what this document closes. Nothing below is a re-run of what already passed.

**Budget rule (only 80 credits remain — see the entry point's budget section): run gates A → B → C → D in order and
STOP at the first failure.**
Do not re-run a failed gate "to see if it flakes" — a failure is evidence. Do not run the full python
suite (the sandbox already ran the 4 lanes that matter). If everything passes, you never reach step 5,
so the whole job costs two builds' worth of waiting and about a dozen short commands.

---

## 0. Get the slice, keep the tree clean

```powershell
$ErrorActionPreference = 'Stop'
cd D:\pulseAIagent\PulseAIRepo
git status --porcelain=v1          # must be empty; if not, STOP and tell me what is dirty
git fetch origin arena/01a0564d-pulseairepo
git checkout arena/01a0564d-pulseairepo
git reset --hard FETCH_HEAD        # safe: the tree above was clean
git log --oneline -1               # expect f7815e473 "manager: register Pulse as a session provider"
$env:PULSEAI_BRIDGE_RUNNER = 'echo'      # mandatory provider/network guard for every launch below
Remove-Item Env:PULSEAI_ALLOW_LIVE_AGENT_TEST -ErrorAction SilentlyContinue   # must never be set
```

Never `git stash`, `git clean`, or amend. Never set `PULSEAI_ALLOW_LIVE_AGENT_TEST=1`. If a step says
"stop", stop and paste the output — do not edit source to make a gate pass.

---

## A. Gate A — the strict typecheck (fast, no install needed)

This is the lane that caught six shipped defects in this contribution, and it is the only gate that
proves the new registration actually satisfies the workbench's contracts
(`IChatSessionItemController`, `IChatSessionItem`, `ChatSessionStatus`, `sessionOpenerRegistry`).

```powershell
cd D:\pulseAIagent\PulseAIRepo\desktop\vscode
..\..\pulse-webview\node_modules\.bin\tsc -p src\tsconfig.pulseai-check.json --noEmit 2>&1 |
  Tee-Object -FilePath $env:TEMP\pulseai-tsc.txt | Out-Null
$mine = Select-String -Path $env:TEMP\pulseai-tsc.txt -Pattern '^vs/workbench/contrib/pulseai'
"Pulse errors: $($mine.Count)"
$mine | Select-Object -First 20
```

**PASS:** `Pulse errors: 0`. Errors in other paths are expected here (missing `@types` in a
partial checkout) and are not failures — only lines starting `vs/workbench/contrib/pulseai` count.

**If Pulse errors are non-zero:** stop. Do not fix them. Go to step 5 and push
`%TEMP%\pulseai-tsc.txt` as `gate-a-tsc.txt`.

---

## B. Gate B — python lanes, only the two that touch this slice

```powershell
cd D:\pulseAIagent\PulseAIRepo
.\.venv\Scripts\python.exe -m pytest src\tests\test_pulse_session_registration_parity.py src\tests\test_desktop_renderer_architecture.py -q
```

**PASS:** `16 passed` (8 + 8), no F/E. A `skip` here is a host gap to report, not a pass —
it means node or `pulse-webview\node_modules\.bin\esbuild` is missing, so run
`cd pulse-webview; npm install` and repeat once.

---

## C. Gate C — build (the long one; only after A and B are clean)

```powershell
cd D:\pulseAIagent\PulseAIRepo\desktop\vscode
npm install          # first time only; if node_modules already exists, skip
npm run compile 2>&1 | Tee-Object -FilePath $env:TEMP\pulseai-compile.txt
Test-Path .build\electron\PulseAI.exe
```

**PASS:** `True`. **If compile fails:** stop and go to step 5 with
`$env:TEMP\pulseai-compile.txt` (last 200 lines is enough) — the exact error text is what I need, not a summary.

---

## D. Gate D — the paint, keyless, no paid turn

Launch the fork with CDP on 9222, then run the existing manager-only validator (it makes no model
turn and waits for `.pulseai-manager-shell`):

```powershell
cd D:\pulseAIagent\PulseAIRepo
Start-Process -FilePath ".\desktop\vscode\.build\electron\PulseAI.exe" `
  -ArgumentList '--remote-debugging-port=9222','--user-data-dir','D:\pulseAIagent\pulse-profile','--disable-workspace-trust','D:\pulseAIagent\playground'
node scripts\validate_pulse_ui_cdp.js bench-results\pulse-manager-registration-desktop\cdp --manager-only
Get-Content bench-results\pulse-manager-registration-desktop\cdp\cdp-ui-result.json |
  Select-String -Pattern '"checks"|PASS|FAIL|error' -Context 0,1 | Select-Object -First 40
```

(`--user-data-dir` on a fresh profile is what makes `window.commandCenter: true` and
`window.titleBarStyle: "custom"` matter again — set those two in that profile's `settings.json`
before launching if the Pulse view does not appear in the right-hand bar.)

Then, in the running IDE, open the Manager (the `Manager` button in the Agent pane header, or
`Ctrl+Shift+P` → `Open Pulse Manager`) and paste this into Help → Toggle Developer Tools → Console:

```js
const rows = [...document.querySelectorAll('.pulseai-session-row')];
({
  rows: rows.length,
  classes: rows.map(r => r.className),
  text: rows.map(r => r.textContent.replace(/\s+/g, ' ').trim()),
  detail: rows.map(r => r.querySelector('.pulseai-session-detail')?.textContent),
  state:  rows.map(r => r.querySelector('.pulseai-session-state')?.textContent),
  empty:  !!document.querySelector('.pulseai-session-row.is-empty'),
  footer: document.querySelector('.pulseai-manager-sidebar-footer')?.textContent,
  agentColumnInManager: !!document.querySelector('.pulseai-manager-main .pulseai-transcript-scroll'),
})
```

**PASS, every line (write each result into `gate-d-findings.md`):**
* `rows >= 1` once a session exists, or `empty: true` with `text: ['No session yet…']` before one does.
  Never a row that was not earned — an empty array standing in for "no data" is the bug this pins out.
* exactly one class containing `is-active`, and that row's `state` is `Working…` during a turn,
  `Ready` between turns, `Needs input` while an approval is open (its dot also gets
  `is-needs-input` + `pulseai-status-dot is-waiting`).
* `detail` for the active row is the same narration the Agent pane shows (e.g. `read pulseAIViewPane.ts…`).
  Same action, same words, in both surfaces — if they differ, that is a defect worth the evidence push.
* `footer` reads `N session(s) remembered · …` and N is the real count.
* `agentColumnInManager: true` — the manager's main column is the desktop agent renderer (`.pulseai-transcript-scroll`
  lives inside `.pulseai-manager-main`), not a copy of it.
* No `+N −M` file numbers on any row (that field is deliberately absent until one diff counter is shared).
* `cdp-ui-result.json` shows `Pulse Manager opens as a visible editor surface` and
  `Pulse Manager has no horizontal overflow` as PASS, and the DevTools console is clean of
  `pulseai` errors.

**Optional, and the one thing you should look at once:** `Ctrl+Shift+P` → `Focus Agent Sessions`.
Pulse sessions now appear in the workbench's *own* list, because that is what registering buys
(sorting, sections, filter submenu, find, a11y/focus commands). Expect: our label, our elapsed text,
no rename/archive/delete on our rows (that type is not `local`), and if the turn is still running a
spinner rather than a pulse. Tell me if you want Pulse hidden there — the revert is exactly one line
(`registerChatSessionItemController`) and I would rather delete it than have you want it gone later.

---

## 5. If any gate failed: push the evidence, change nothing

```powershell
cd D:\pulseAIagent\PulseAIRepo
$e = 'bench-results\pulse-manager-registration-desktop\retry-forbidden'
New-Item -ItemType Directory -Force -Path $e | Out-Null
git rev-parse HEAD | Set-Content "$e\head.txt"
Copy-Item $env:TEMP\pulseai-tsc.txt "$e\gate-a-tsc.txt" -ErrorAction SilentlyContinue
Copy-Item $env:TEMP\pulseai-compile.txt "$e\gate-c-compile.txt" -ErrorAction SilentlyContinue
Copy-Item $env:TEMP\pulseai-devtools-console.txt "$e\gate-d-console.txt" -ErrorAction SilentlyContinue
# paste the console object above and the failing text into this file with your editor, then:
git add -f $e
git commit -m "evidence: manager registration gate <A|B|C|D> failed on Windows (no source edits)"
git push origin HEAD:arena/01a0564d-pulseairepo
```

`bench-results\` is gitignored, so `-f` is required; the failure is committed as-is, no edits, no
retry, no cleaning. Then tell me which gate and paste the last 20 lines here.

---

## What is deliberately NOT done (so a red check is not mistaken for a bug)

* Rows other than the open one are **disabled** — steering another session needs `session_resume`, which
  this build never calls. `title` says so.
* `IChatSessionItem.changes` is **absent**, so no row shows `N files +A −D`.
* `setChatSessionItemRead` is unimplemented on purpose: the host's persisted read tracking wins.
* `openManagerWindow()` and the manager chrome are **still hand-built**; step 2 is replacing them with
  the host's `AgentSessionsControl` inside the Agent pane. Popup-vs-tab is still your call
  (`xfail(strict=True)` in the desktop lane until you pick).
