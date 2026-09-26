# Running the agent inside the desktop app — and then Crusor Preview in it

This is the host lane: pull, verify, build, launch, and watch the agent work in the real Electron
window. `CRUSOR_PREVIEW_LAUNCH_CHECKS.md` starts *after* this one — it assumes the app is up and the
agent is answering. Read the two together: this file gets you to a running app, that file tells you
what to look at once the preview exists.

What is verified where:

- **[here]** — I ran it in the checkout (`PulseAIRepo`), you can trust the output;
- **[host]** — needs the desktop build and a display, so it runs on your Windows machine only. I
  cannot do it here: this sandbox has no display and no vendored `node_modules` for a Code OSS
  build.

Order is not optional: A → B → C → D. **Stop at the first failure** and report it. Do not reinstall
the world to make a check go green — a missing node, `.venv` or esbuild is a host gap to report.

---

## 1. Get the current branch, and drop your local fixes

Your four local `tsc` fixes are **already on this branch** (they were six sites, not four — see §2).
Do not re-apply them: keeping them means you are building a tree nobody else has verified, and two of
them would conflict with what is committed.

```powershell
$ErrorActionPreference = 'Stop'
cd D:\crusorAIagent\PulseAIRepo
git fetch origin arena/01a0ca7c-pulseairepo
git merge-base --is-ancestor 2b2880f8 FETCH_HEAD    # the tip this doc ships in; later tips keep it as an ancestor
if ($LASTEXITCODE -ne 0) { git pull --ff-only origin arena/01a0ca7c-pulseairepo }
```

Now look at what your tree still has:

```powershell
git status --porcelain=v1
```

- `M desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIPreviewService.ts`
  and/or `M .../common/crusorAIPreview.ts` → **discard them**, they are superseded:

  ```powershell
  git checkout -- desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIPreviewService.ts `
                  desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAIPreview.ts
  ```

- anything else modified → keep it, and say so when you report. Do not stash, clean or reset.

The six sites that are now fixed and pushed, so you can recognise your own patch:

| File | Site | Was | Now |
| --- | --- | --- | --- |
| `crusorAIPreviewService.ts:105` | `new MutableDisposable<DisposableStore>>()` | TS1109, an extra `>`; in plain JS `a < b >> c` is legal, so `node --check` cannot see it | one `>` |
| `crusorAIPreviewService.ts:158` | `this.environmentService.userHome` | TS2339 — `userHome` is on `INativeEnvironmentService`, which the workbench does not register | `this.pathService.userHome({ preferLocal: true })` |
| `crusorAIPreviewService.ts:324` | `listen(): Disposable` | TS2739 — `toDisposable` returns `IDisposable` | `: IDisposable` |
| `crusorAIPreview.ts:186/189` | `const query: string[] = [['endpoint', …]]` | TS2322/TS2345 — pairs assigned to `string[]` | `const query: [string, string][]` |
| `crusorAIPreviewService.ts:87` | `ENDPOINT_FRESH_MS` | TS6133 under the fork's `noUnusedLocals` | deleted (staleness is `started_at` + 12 h, further down) |
| `crusorAIPreviewService.ts:89` | `interface PreviewWindowHost` | TS6196, never referenced | deleted |

---

## 2. Gate A — the scoped typecheck, seconds, not minutes **[here: 0 errors]**

This is the fork's own lane for `contrib/crusorai` (`browser/` + `common/`), so it compiles the
preview code without a full `node_modules` tree. Run it from `desktop\vscode\src`:

```powershell
cd D:\crusorAIagent\PulseAIRepo\desktop\vscode\src
$tsc = if (Test-Path ..\node_modules\.bin\tsc.cmd) { '..\node_modules\.bin\tsc.cmd' }
       elseif (Test-Path ..\..\..\crusor-webview\node_modules\.bin\tsc.cmd) { '..\..\..\crusor-webview\node_modules\.bin\tsc.cmd' }
       else { throw 'No tsc — run npm install in desktop\vscode first (see §4)' }

& $tsc -p tsconfig.crusorai-check.json --noEmit 2>&1 | Out-File -Encoding ascii gate-a-tsc.txt
$mine   = (Select-String -Path gate-a-tsc.txt -Pattern 'contrib/crusorai' | Where-Object Line -match 'error TS').Count
$files  = (& $tsc -p tsconfig.crusorai-check.json --noEmit --listFilesOnly 2>$null | Select-String 'contrib/crusorai').Count
"Crusor errors: $mine   Crusor files in program: $files"
if ($files -lt 26) { throw "Gate A has no coverage ($files files) - this is not a pass" }
if ($mine -ne 0)   { throw "Gate A failed with $mine error(s) - send me gate-a-tsc.txt and stop" }
```

**PASS = `Crusor errors: 0` AND `Crusor files in program: 34`** (≥ 26 is the floor).

Two traps, both already paid for:

- The compiler is pinned: `desktop/vscode/package.json` has
  `"typescript": "npm:@typescript/typescript6@^6.0.2"`, a shim over `typescript@^6` — the newest
  TS6 on the registry is **6.0.3**, and that is what I used. A TS 5.8 run of the same tree with
  `noUnusedLocals` off misses `ENDPOINT_FRESH_MS`/`PreviewWindowHost` entirely, which is exactly how
  the first pass reported "clean" while these two sites were still red.
- `-Pattern 'contrib/crusorai'` is **unanchored on purpose**, and coverage is asserted separately: a
  grep that cannot match reports 0 whether the tree is clean or not. Errors elsewhere in the log are
  expected — they are missing `@types` in a partial checkout (`@webgpu/types`,
  `@types/trusted-types`, `mocha`, `winreg`…) and are not failures. Judge only `Crusor errors`.

Output I got, for comparison: `Crusor errors: 0   Crusor files in program: 34`, 363 unrelated
errors, `tsc` exit 2 because of those.

## 3. Gate A′ — the full client typecheck, after `npm install` **[host]**

Once `desktop\vscode\node_modules` exists, run the same gate the way the build does. This is the one
that actually failed on the tip you pulled: `src/tsconfig.json` includes `./vs/**/*.ts`, so
`contrib/crusorai` is in the program.

```powershell
cd D:\crusorAIagent\PulseAIRepo\desktop\vscode
npm run typecheck-client      # tsc -p ./src/tsconfig.json --noEmit --skipLibCheck
```

**PASS = exit 0.** With `node_modules` installed there is none of the partial-checkout noise above, so
this one must be completely clean.

## 4. Gate B — the python lane for this feature **[here: 67 passed]**

```powershell
cd D:\crusorAIagent\PulseAIRepo
.\.venv\Scripts\python.exe -m pytest src\tests\test_preview_inject.py src\tests\test_preview_prompt.py `
  src\tests\test_preview_server.py src\tests\test_preview_endpoint.py src\tests\test_preview_contract.py -q
```

**PASS = `67 passed`** (12 inject, 11 prompt, 19 server, 11 endpoint, 13 contract + the window-query
pin). No provider, no network, no display. `test_preview_contract.py` needs `node` on PATH — it runs
the shipped JavaScript and the TypeScript contract through node; skip it only if node is missing, and
say so rather than counting it as a pass.

The rest of `src\tests` needs the engine's full dependency set (`httpx`, the graph stack …) — that is
*not* this gate. If you also want the two bridge lanes that cover the app-to-agent path, they must run
under the repo `.venv`; run them with a bare `python` and they fail on imports
(`ModuleNotFoundError: No module named 'typing_extensions'`), which is a host gap, not a product
failure:

```powershell
.\.venv\Scripts\python.exe -m pytest src\tests\test_bridge_protocol_v2.py src\tests\test_bridge_transport.py -q
```

**PASS = exit 0.** I could not verify these here — this sandbox has pytest but not the engine's
libraries, so 3 of the 23 failed on `typing_extensions` alone. Bring your own count to the report.

## 5. Gate C — build the app **[host]**

```powershell
cd D:\crusorAIagent\PulseAIRepo\desktop\vscode
node --version                 # .nvmrc pins 24.18.0; node 22 works, record what you used
npm install                    # only if node_modules is absent
npm run typecheck-client       # Gate A' — must be clean
npm run valid-layers-check     # browser/ must not reach for electron/node
npm run compile
npm run gulp minify-vscode
```

**PASS = every command exits 0.** `compile` is the long one (several minutes on a cold tree).
`minify-vscode` is only needed for a packaged build; for the in-app test `compile` is enough, and
`scripts\code.bat` will fetch Electron on first launch.

If a layer check fails on `crusorai`, send the two lines it prints — that lane is exactly what a
`browser/` file reaching for a `node/` or electron import would trip, and the preview service is
`browser/`.

## 6. Gate D — launch it with the network guard, then talk to the agent **[host]**

`CRUSORAI_BRIDGE_RUNNER=echo` is the mandatory guard: the bridge answers each turn locally, makes no
model call and touches no credential. Setting it in this shell is enough — the workbench spawns
`python -m src.bridge` with `env: { ...process.env, PYTHONUNBUFFERED: '1' }`
(`crusorAIWorkerProcessService.ts:156`), so the variable is inherited by the engine process.

```powershell
cd D:\crusorAIagent\PulseAIRepo
Remove-Item Env:CRUSORAI_ALLOW_LIVE_AGENT_TEST -ErrorAction SilentlyContinue   # never set this
$env:CRUSORAI_BRIDGE_RUNNER = 'echo'
$env:CRUSORAI_ECHO_DELAY_MS = '1500'    # optional: a turn slow enough to see the Stop button
cd desktop\vscode
.\scripts\code.bat "D:\work\your-project"    # opens that folder; omit the argument to open the repo
```

Use your project folder as the argument — **not** `--user-data-dir`-style flags with a bare path
after them, which the build reads as "what to load" rather than "what to open". If the window still
comes up with no folder, re-run the same launch with `--folder-uri "file:///D:/work/your-project"`.

Then, in the window:

| # | Do this | Pass looks like | If it fails |
| --- | --- | --- | --- |
| 6.1 | Open the Crusor container (activity bar, or `Ctrl+L`) | the Agent pane renders, composer focused | a blank pane means the renderer, not the engine — check `Help → Toggle Developer Tools` for the module error |
| 6.2 | Send any prompt, e.g. `hi` | a reply appears, instantly (or after `CRUSORAI_ECHO_DELAY_MS`), and `Stop` is offered while it runs | the engine never started: read the pane's error line. `CrusorAI engine root is not configured: set crusorai.engineRoot or CRUSORAI_ENGINE_ROOT, or open a workspace that contains src/bridge.` means the opened folder is not the checkout and no setting points at it |
| 6.3 | Confirm which python it used | `PulseAIRepo\.venv\Scripts\python.exe` if it exists, else `CRUSORAI_PYTHON_PATH`, else `python` on PATH | if your `.venv` is elsewhere, set `CRUSORAI_PYTHON_PATH` before launching |
| 6.4 | Send a second prompt while the first is still running (needs 6.2 with the delay) | the turn queues or refuses cleanly — no silent drop | a silent drop is a real finding: send me the pane text |
| 6.5 | The provider-free pass is done | now do a **real** turn: §7 below. It costs money and needs a key, which is why it is a separate section rather than an extra row here | — |

The agent's reply arriving in the app is the whole point of this gate: it proves the workbench →
worker process → bridge → back path survives the build, which no pytest can.

## 7. A real turn — the live provider **[host, costs money]**

Everything above runs keyless on purpose. This is the one lane that talks to a model, and it is how
you find out whether the app can hold a real conversation.

Two rules first: **never paste a key into this chat**, and **do not export a key in a shell you also
launch from if a `.env` already exists** — `src/config/settings.py` loads `.env` with
`override=True`, so the file wins over your exported variable. That single line explains most "I set
the key and it still fails" reports.

### 7.1 Put the key where the engine looks for it

The engine reads `PulseAIRepo/.env` (a file, not a shell variable). Open it, or create it from the
template:

```powershell
cd D:\pulseAIagent\PulseAIRepo
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Fill in the provider you actually have, and the model that account can serve:

```ini
LLM_PROVIDER=groq
LLM_MODEL=<a model your account has>
GROQ_API_KEY=<your key>
```

- `groq` is the engine default and has a free tier, so it is the cheapest first run. `openai`,
  `gemini`, `nvidia` work the same way with their own variable (`OPENAI_API_KEY`, `GEMINI_API_KEY`,
  `NVIDIA_API_KEY`). A local OpenAI-compatible server needs `LLM_PROVIDER=custom` plus
  `CUSTOM_BASE_URL` and `CUSTOM_API_KEY`, and costs nothing.
- **`LLM_MODEL` matters as much as the key.** `.env.example` ships `qwen/qwen3.6-27b`, which is the
  code default and may not exist on your account. If your provider's model list does not have it,
  the turn fails with a model error. Use a model id you can see in your provider's console — I cannot
  see your account, so I cannot pick it for you.

### 7.2 Prove the key before you launch the app — `scripts/check_provider.py`

A bad key inside the app is a vague error card several layers from the cause. This check runs the
*engine's own* client, so a pass means the agent's path works:

```powershell
cd D:\pulseAIagent\PulseAIRepo
.\.venv\Scripts\python.exe scripts\check_provider.py            # config only: no network, no cost
.\.venv\Scripts\python.exe scripts\check_provider.py --live     # one 2-token request: fraction of a cent
```

What you should see (the dry run, with a key present):

```text
provider      : groq
model         : <your model>
GROQ_API_KEY  : set, ...9f8e (33 chars)
.env file     : present (…\.env)
                note: .env overrides exported variables (load_dotenv(override=True))
ok    configuration is complete. Re-run with --live to prove the key works:
```

Then `--live` ends either with `ok    groq/<model> answered in 1.2s: 'READY'` — launch the app — or
with `FAIL`, the provider's own message, and a classification line that names the fix: a wrong key,
a billing/credit refusal, or a model id that does not exist for that account. The key is never
printed; only its last four characters and its length.

Run it with `.venv\Scripts\python.exe`, not a bare `python`: the live probe imports the provider
SDKs, and a system interpreter does not have them (`FAIL provider SDKs are not importable` says so).

### 7.3 Launch without the guard

```powershell
Remove-Item Env:CRUSORAI_BRIDGE_RUNNER -ErrorAction SilentlyContinue
$env:CRUSORAI_BRIDGE_RUNNER    # must print nothing — confirm before launching
cd D:\pulseAIagent\PulseAIRepo\desktop\vscode
.\scripts\code.bat "D:\work\your-project"
```

The engine process inherits your shell (`env: { ...process.env }` in
`crusorAIWorkerProcessService.ts`), so a variable you remove here is genuinely gone — but if the app
is already running, **quit and relaunch it**: the bridge is spawned at startup, and env changes do
not reach a process that is already up.

### 7.4 Send one real message

Ask something small and unambiguous — `say hello and nothing else`. A pass is: a reply that is *not*
your own sentence, arriving word by word, with `Stop` available while it runs. The "test mode"
notice from §6 will not appear; that notice only ever comes from the echo seam.

| What you see | What it means |
| --- | --- |
| Your own words come back | the guard is still set — `$env:CRUSORAI_BRIDGE_RUNNER` printed something, or the app was not relaunched |
| A red error card naming a model or a 404 | `LLM_MODEL` is not a model your account serves |
| An error card naming auth/401 | the key is wrong, expired, or from a different provider than `LLM_PROVIDER` |
| An error about credits/quota/billing | the key works, the account has no balance |
| Nothing at all, then a stall message | the provider was reached but never answered — the message is the evidence, send it |
| A real reply | done: the app, the engine, your key and your account all work together |

### 7.5 Test the prompt itself, without the IDE — `scripts/preview_batch_turn.py`

The preview window's last step is a prompt, and the only question that matters about it is whether the
agent finds the element the user clicked — or repaints the page. This harness answers that in a
terminal: it builds a batch, prints the exact prompt text, spawns `python -m src.bridge` the way the
workbench does, streams what comes back (reasoning, every tool call, tokens), and then reports what
changed in the workspace.

```powershell
cd D:\pulseAIagent\PulseAIRepo
# safe first run: edits a TEMP copy of the lab fixture, nothing in the repo is touched
.\.venv\Scripts\python.exe scripts\preview_batch_turn.py --demo --diff

# then a real project — use a scratch copy, this edits files
.\.venv\Scripts\python.exe scripts\preview_batch_turn.py --workspace C:\work\scratch-project --diff
```

**What a pass looks like**, from two independent sessions against the fixture:

1. `search_files(pattern=btn btn-primary)` and `search_files(pattern=hero-title)` — it searched for the
   **fingerprints**, which is the whole reason the prompt lists classes, text and attributes;
2. a few reads to locate the rules (`read_file`, `grep -n btn styles.css`, targeted offset reads);
3. `edit_file` on the stylesheet only — the markup was never touched, which is the scope rule working;
4. a verification pass, then a summary.

The batch's first fix names an element the fixture stamps with `data-crusor-source` (the precise path)
and its second does not (the heuristic path) — the second is the one that has to work in your own
project, and it did: the agent used the fingerprint attribute as its own selector.

Two things that will confuse you if you do not know them:

- **Output is live.** If nothing appears for minutes, the provider is slow, not the script: the
  heartbeat prints elapsed time, the number of frames received, and what the engine sent last.
  (The first live run before this was added reported "600 seconds, zero lines" — a buffered pipe hid a
  turn that was working.) For the same reason the first turn can legitimately take minutes: the engine
  warms its heavy imports before it answers.
- **`--diff` reads the files, not git.** `--demo` edits a temp copy that is not a repository, so a
  git-based diff there reports "no changes" no matter what happened — the report is a before/after
  comparison of file contents, with line counts and a short unified diff per changed file, and it says
  `no file changed (N file(s) compared)` when that is the truth.

**If the agent searches with a regex escape, this is why.** A live run sent `search_files(pattern=\.btn)`
and got `No results found for '' in '.'` three times, then invented a class that exists nowhere and
spent the rest of the turn in the terminal. Two long-standing defects in the tool produced that:

- the miss message named the legacy `query` argument, which is empty whenever the caller sends
  `pattern` — so every miss read as *empty pattern*, and the real pattern was never shown;
- `search_files` matches **literal** text, not regular expressions, and said nothing about it, so
  `\.btn` searched for a backslash that is not in any file.

Both are fixed: the message names the pattern that was used, and when a de-escaped form of it would
have matched, the miss says so and shows a real line. If you see the hint in a run, the agent is
about to retry correctly instead of guessing. (Reordered arguments were the first theory and are
false — the tool receives a dict, so key order cannot matter; the reordered calls in that log were
simply the escaped ones.)

**If a run times out, leave nothing behind.** The harness kills the engine's whole process tree, not
just the engine: a model that backgrounds a command (`python -m http.server &`) would otherwise leave
a listening process behind after the turn. On POSIX that is a process group; on Windows `taskkill /T`.
The run prints which was used (`engine stopped: process group (whole tree)`).

**What this does not cover:** the fixture is static HTML and CSS. The harder cases — a component
library, Tailwind utilities, CSS-in-JS, where the class in the DOM is not the class in the source — are
untested against a real model, and they are exactly where the fingerprints matter most. If your project
is one of those, run the second command above against a scratch copy and send the tool-call lines.

### 7.6 Getting back to free testing

```powershell
$env:CRUSORAI_BRIDGE_RUNNER = 'echo'    # and relaunch
```

Every later pass — the preview window, the inspect flow, Send to Crusor — works in echo mode, so do
that part for free (§8) and spend credits only on the turn.

## 8. Then the preview, in the same window **[host]**

The preview needs a proxy running for the **same folder** you opened — nothing starts it for you:

```powershell
cd D:\crusorAIagent\PulseAIRepo
python -m src.preview.server --workspace "D:\work\your-project" --port 8931 --endpoint-session ide
```

Wait for it to print the origin and the endpoint path, then work through
`CRUSOR_PREVIEW_LAUNCH_CHECKS.md` §1 → §8 in that window: the `Agent · Webview · Preview` chip, the
separate window, the render, Edit UI, the wireframe, the fix pins, the review sheet, and Send to
Crusor. Those steps are written as a table of *look at this → pass looks like → what a failure
means*, and every one of them is tagged **[code]** or **[host]**.

Two things worth knowing before you start, so a correct behaviour is not reported as a bug:

- a refusal to register is expected when the secret is missing or wrong — the window's origin is
  opaque, so the proxy gates registration on the per-run secret; the window itself always sends it;
- the composer showing the batch prompt is the contract working, not a bug: the engine prompt and
  the window's copy are pinned to each other by `test_preview_contract.py`.

## 9. Evidence and stop rules

Write evidence as **ASCII** (`Set-Content -Encoding ascii`; plain `Tee-Object` emits UTF-16 and turns
a 60 KB log into an unreadable blob). Never overwrite a previous run's directory.

```powershell
$evidence = 'bench-results\crusor-preview-app-test'
if (Test-Path $evidence) { throw 'Evidence directory exists - do not overwrite, pick the next round' }
New-Item -ItemType Directory -Path $evidence | Out-Null
Set-Content "$evidence\gate.txt" -Encoding ascii -Value "reached: <A|B|C|D>; result: <PASS|FAIL>; first failure: <gate + one line>"
git rev-parse HEAD        | Set-Content "$evidence\head.txt" -Encoding ascii
node --version            | Set-Content "$evidence\node-version.txt" -Encoding ascii
git status --short        # only the evidence directory should appear
git add -f $evidence      # bench-results\ is gitignored
git commit -m "evidence(preview): desktop app agent test - <PASS|FAIL at gate X>"
git push origin HEAD:arena/01a0ca7c-pulseairepo
```

Never commit a source change with it. If `git status --short` shows anything outside the evidence
directory, leave it in the tree uncommitted and say what is dirty.

Report, in one message:

1. `gate.txt`, and the head SHA you built;
2. Gate A's `Crusor errors: N   Crusor files in program: N`;
3. Gate B's last line (`67 passed`) — or the first failure, verbatim;
4. for a gate D failure: the pane text plus the last 20 lines of the console
   (`Help → Toggle Developer Tools`), not a screenshot of the whole screen;
5. which of the six sites in §1 your local patch had touched.

Stop rules: stop at the first failure, do not edit source to make a gate pass, do not retry a flaky
gate hoping for a different result, do not set `CRUSORAI_ALLOW_LIVE_AGENT_TEST`, do not force-push,
and do not upgrade a build PASS over a UI failure.
