# Desktop Agent — Live End-to-End Verification: ported Hermes prompt engine + Agent UI

**Branch to verify:** `arena/01a0564d-pulseairepo`. Required ancestor: the port commit **`051510ae`**,
plus the live-round tooling below (this brief's own commit is newer than the port, so pin by content, not SHA).
**Host:** Windows / PowerShell, run from the repo root (`cd <repo root>`). The fork lives at
`desktop\vscode`. `npm run compile` is **expected and allowed** when the Manager view times out — prior
rounds withdrew the skip-compile rule, and `validate_pulse_ui_cdp.js` cannot find `Pulse Manager` in a stale
`.build`. So: run the manager-only pass first; on `Timed out waiting for Pulse Manager editor`, run
`cd desktop\vscode; npm run compile` once, re-run the pass, and record in findings.md whether you compiled.
Never rebuild `.build` by hand (no `npm run gulp`, no manual copies).
**Return channel:** commit and push evidence **back to `arena/01a0564d-pulseairepo`**. No merge, no delete,
no branch switching. I re-verify everything from the pushed artifacts.

---

## The one rule that matters most: 90 credits, spent wisely

You have a key I will paste into `.env` as `CUSTOM_API_KEY` (plus `CUSTOM_BASE_URL`, `LLM_PROVIDER`,
`LLM_MODEL`). Hard ceiling: **90 credits for this whole task. Budget plan: ≤ 62 requests, stop
everything at 85 credits spent.** "Wise" is not a vibe here — it is the following, and each line has a
mechanism in this repo:

1. **Every live call goes through `scripts/run_bridge_turn.py`** (`.venv\Scripts\python.exe -u scripts\run_bridge_turn.py
   --workspace <scratch ws> --prompt-file <f> --run-id <id> --max-llm-calls N --max-input-tokens M
   --timeout-s S`). It already contains a **credit circuit-breaker**: past either cap it sends
   `{"type":"cancel"}` and stops the turn. Do not call the engine any other way — no ad-hoc
   `requests.post`, no dashboards, no notebook cells.
2. **Never re-run an assertion that already passed.** Re-runs are only for assertions that FAILED, and
   each failed assertion gets **at most one** re-run. A flaky-looking result is recorded as FAIL, not
   chased.
3. **Keep `PROVIDER_SAFE_LIMIT` at its default (6000 tokens).** Do NOT set it to `0` (that unlocks the
   full window and every request balloons). Keep `EMBEDDING_PROVIDER=local` (free, in-process —
   embedding spend is not part of this budget and must not be purchased).
4. **Prompt discipline:** every test prompt ends with the literal sentence
   `Answer in at most 120 words. Prefer one tool call over exploration.` Short answers are the whole
   trick — output tokens are where money dies.
5. **One scratch workspace, ~6 tiny files** (fixture in Phase 2). A 200-file repo map is a context tax
   you pay on every single request.
6. **Do not change any `PULSEAI_*` flag except where a phase explicitly says so**, and log every flag you
   did set (Phase 6 manifest). Flags that silently multiply requests are how budgets die.
7. **Ledger after every phase, not at the end.** Append `credits-spent.log` lines as you go:
   `phase, requests, prompt_tokens, completion_tokens, running_total`. Reconstruct from
   `bench-results/<run-id>/frames.jsonl` (`llm.request` frames + usage) or
   `.venv\Scripts\python.exe scripts\analyze_llm_requests.py bench-results\<run-id>` for the benchmark lane. If the
   running total reaches **85**, stop everything, skip Phases 4–5, go straight to Phase 6 and push what
   you have — partial evidence is a pass, a blown budget is a fail.
8. **Kill the whole process tree if anything looks stalled:** `taskkill /T /F /PID <pid>`. A hung engine
   retrying is still spending. `src\llm\error_classifier.py` classifies `billing` (402 / exhausted
   credits) — on a `billing` classification STOP immediately and report it. No retry, no fallback chain.

---

## Phase 0 — Pre-flight gates (0 credits). Any failure = STOP and report, do not improvise.

```powershell
$repo = (Get-Location).Path
if ((git branch --show-current) -ne 'arena/01a0564d-pulseairepo') { throw 'Wrong branch — STOP' }
git fetch origin arena/01a0564d-pulseairepo
git pull --ff-only origin arena/01a0564d-pulseairepo
git merge-base --is-ancestor 051510ae HEAD
if ($LASTEXITCODE -ne 0) { throw 'Required port commit 051510ae missing — STOP' }
foreach ($need in 'scripts\dump_pulse_prompt.py','src\tests\test_hermes_prompt_parity.py',
                  'DESKTOP_AGENT_LIVE_VERIFICATION_PROMPT_UI.md') {
  if (-not (Test-Path $need)) { throw "Live-round tooling missing ($need) — pull again, then STOP" }
}
.venv\Scripts\python.exe -m pytest src\tests\test_hermes_prompt_parity.py -q -k dump_pulse_prompt
if ($LASTEXITCODE -ne 0) { throw 'prompt dumper is not pinned/green — STOP' }
.venv\Scripts\python.exe -m pytest src\tests\test_hermes_runtime_values.py -q -k "grandchild or cancel" `
  2>&1 | Tee-Object "$evidence\gate-cancel-fix.log"
if ($LASTEXITCODE -ne 0) { throw 'foreground-cancel fix missing — pull again, then STOP' }
if (git status --porcelain=v1) { throw 'Dirty checkout — STOP without cleaning' }
$envBackup = Join-Path $env:TEMP 'pulseai-env-backup\.env'   # never back up inside the repo
if (Test-Path '.env') { New-Item -ItemType Directory -Force -Path (Split-Path $envBackup) | Out-Null; Copy-Item '.env' $envBackup -Force }
if (-not (Test-Path 'desktop\vscode\.build')) { throw 'desktop/vscode/.build missing — run npm run compile yourself, then STOP' }
if (Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 9222 in use — STOP' }
if (Get-Process PulseAI -ErrorAction SilentlyContinue) { throw 'PulseAI already running — STOP' }
```

Then create/replace `.env` **only when I hand you the key** (an existing `.env` is moved to the TEMP backup
above, and you say so in `env-manifest.json`). Four-plus-one lines, in this order, nothing else, no extra
providers:

```
CUSTOM_API_KEY=<paste>
CUSTOM_BASE_URL=<paste>
LLM_PROVIDER=custom
LLM_MODEL=<paste>
AUX_LLM_MODEL=<paste the cheapest model your provider offers>
```

expect: `git rev-parse HEAD` is `051510ae` or a descendant on `arena/01a0564d-pulseairepo`, and
`scripts\dump_pulse_prompt.py --help` works (proves the pinned tooling is present).
expect: the credit probe from `scripts\run_paid_pbr002_guarded.ps1` (one 8-token call) prints `PROBE_OK`.
 **That probe is hard-wired to `https://api.sarvam.ai/v1/chat/completions` +
 `sarvam-105b-conversations`.** If my key is for a different provider, run the identical 8-token probe
 against `CUSTOM_BASE_URL`/`LLM_MODEL` instead (copy the probe block out of the script, change those two
 values) — and **never** pass `-SkipProbe`. If the probe fails, STOP — do not start the plan and do not
 "debug" the key; you have spent ~0.1 credit and that is the correct outcome.
expect: `.env` is NEVER committed, echoed into a log, or included in any artifact. Redact the key in
 every file you produce (`sk-…` → `sk-REDACTED`); a key in the pushed evidence is a task failure.

## Phase 1 — Provider-free baseline (0 credits). This is what I already proved; you are proving it holds.

**Read this before you run anything below.** "Provider-free" was an assumption about the suite, and on your
machine it was false. Six test modules in `src/tests` (pre-existing, not from this port) call
`invoke_agent`/`stream_agent` at **module scope**, so merely *collecting* them runs 11 real agent turns against
whatever key your `.env` holds — before `-k`/`-m` applies and before any timeout guard is armed. They also write
into `generated/`. `src/tests/test_no_import_time_agent_turns.py` is the pin that keeps the pattern from
growing; those 6 files sit in its `KNOWN_IMPORT_TIME_TURNS` set as owner debt, deliberately not converted
mid-round. So run the full suite **with those six ignored**, and never set `PULSEAI_ALLOW_LIVE_AGENT_TEST=1` for
this task — that variable opts *into* a billed turn, and it is the only thing gating the seventh file
(`test_agent_status_checkpoint.py`, which is what stalled your collection at 60 s and got misread as a slow
import).

```powershell
$evidence = Join-Path $repo 'bench-results\prompt-ui-live-e2e'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8
$env:PULSEAI_ENGINE_ROOT = $repo
$env:PULSEAI_PYTHON_PATH = Join-Path $repo '.venv\Scripts\python.exe'
.venv\Scripts\python.exe -m pytest src\tests\test_hermes_prompt_parity.py src\tests\test_hermes_prompt_session_cache.py -q 2>&1 |
  Tee-Object "$evidence\pytest-parity.log"
$live_debt = @(
  'test_keep_recovery.py','test_plan_approval.py','test_plan_cancel.py',
  'test_plan_mode.py','test_plan_revision.py','test_replan_recovery.py'
) | ForEach-Object { "--ignore=src/tests/$_" }
.venv\Scripts\python.exe -m pytest src\tests -q $live_debt 2>&1 | Tee-Object "$evidence\pytest-full.log"
cd pulse-webview; npm test 2>&1 | Tee-Object "$repo\$evidence\webview-test.log"; `
  npx tsc -b 2>&1 | Tee-Object "$repo\$evidence\webview-tsc.log"; `
  npx vite build 2>&1 | Tee-Object "$repo\$evidence\webview-build.log"; cd $repo
```

expect: `71 passed` from the two Hermes suites (61 parity + 10 session-cache), **0 skipped**. Any fewer =
**STOP, report, spend 0 credits.** Then the full-suite log: a pass-count is yours to
report, not to match against my box, and a `1 skipped` naming `PULSEAI_ALLOW_LIVE_AGENT_TEST` is the *correct*
result — if that test ran, credits were spent and `findings.md` must say so instead of reporting it green. If
collection stalls again, `pytest --collect-only -q` plus a faulthandler dump names the module: look for
module-scope work before you blame the interpreter.
One skip is legitimate and host-shaped, not a failure: `test_corpus_hash_matches_a_pinned_checkout` skips
when no Hermes checkout is reachable. That test is the anti-drift guarantee for the whole port (corpus
sha256 vs upstream bytes at the pin), so satisfy it rather than accept the skip — 0 credits, one network
fetch, and the pin is a public repo:

```powershell
$ref = Join-Path $env:USERPROFILE '.hermes-ref'
git init $ref; git -C $ref remote add origin https://github.com/NousResearch/hermes-agent.git
git -C $ref fetch --depth 1 origin a9c783f21995723c812dcb2f8ae58bc6a4323e2f
git -C $ref checkout FETCH_HEAD
$env:HERMES_REF = $ref     # the test reads HERMES_REF, else /home/user/.hermes-ref
```

expect after it: `61 passed` for the parity file alone, **no skip line**, i.e. the corpus still matches
upstream at `a9c783f2`. If GitHub is unreachable from your box, record `SKIPPED(no upstream checkout)` for
that one test in findings.md and continue — do not treat it as a port failure.

**The full-suite gate is a SET DELTA, not a count.** A fixed allow-list of "the 6 known failures" was my
first cut and it was wrong: it was written from a Linux sandbox, and on a Windows host the base suite already
fails 11 (see `bench-results/prompt-ui-live-diag/` at `c558e5c7`). So baseline **on your machine**, then diff:

```powershell
.venv\Scripts\python.exe -m pytest src\tests -q --tb=no -rf 2>&1 | Tee-Object "$evidence\pytest-full.log"
Select-String -Path "$evidence\pytest-full.log" -Pattern '^FAILED ' |
  ForEach-Object { ($_.Line -split '\s+')[1] } | Sort-Object | Unique | Set-Content "$evidence\ported-failures.txt" -Encoding utf8

git worktree add "$repo\..\pulseai-base" 86eaaae2 --detach          # PRE-PORT, read-only, no stash
Push-Location "$repo\..\pulseai-base"
& (Join-Path $repo '.venv\Scripts\python.exe') -m pytest src\tests -q --tb=no -rf 2>&1 |
  Tee-Object "$evidence\base-failures-raw.log"
Pop-Location
git worktree remove "$repo\..\pulseai-base"
Select-String -Path "$evidence\base-failures-raw.log" -Pattern '^FAILED ' |
  ForEach-Object { ($_.Line -split '\s+')[1] } | Sort-Object | Unique | Set-Content "$evidence\base-failures.txt" -Encoding utf8

$regressions = Compare-Object (Get-Content "$evidence\base-failures.txt") (Get-Content "$evidence\ported-failures.txt") |
  Where-Object { $_.SideIndicator -eq '=>' }
if ($regressions) { throw "Port-caused failures — STOP and report: $($regressions.InputObject -join ', ')" }
```

expect: `$regressions` is empty — every failure on the ported tree also fails at `86eaaae2` on the same
machine. A **new** id in `ported-failures.txt` = real regression, STOP. An id that *disappears* is a bonus,
note it and continue. **Never `git stash`/`git checkout` to get the baseline** — 60+ uncommitted files is how
work gets lost; the worktree is read-only and disposable.
expect: on Windows the base run lists 11 ids (the 6 cross-platform ones + 4× `TestFeedbackStore::*` +
`test_foreground_terminal_observes_session_cancel`) and the ported tree should list **6** — the fixture and
the cancel drain are fixed on this branch, so if the 5 are still red you are on an older commit: `git pull`.
expect: webview `48 passed`, `tsc -b` exit code 0, `vite build` succeeds.

Two host notes so nobody chases ghosts: (1) before the fixture fix, `TestFeedbackStore` tests ran against the
**real** user profile on Windows, so `~\.pulseai\context_feedback.jsonl` may hold hundreds of test-written
records — deleting that one file is fine, deleting anything else in your profile is not. (2) `.env` and the
`PULSEAI_*` vars were already proven irrelevant to these failures (clean-env run failed identically), so do
not waste time stripping them again.

## Phase 2 — Live prompt engine (target: 4 turns / ≤ 20 requests)

Scratch workspace: 6 tiny files, including `PULSE.md` with one literal line
`PULSE_FIXTURE_MARKER_alpha`, plus a `README.md` and `notes\PULSE.md` decoy (same filename, wrong scope).
Prompts live in `$evidence\prompts\N.txt`. Run each through `run_bridge_turn.py` with
`--max-llm-calls 5 --max-input-tokens 12000 --timeout-s 240`, one **unique** `--run-id` per turn (never
reuse ids — durable checkpoint pollution).

**2.0 Byte capture, 0 credits (do this first — it is the cheapest way to prove prompt content).** Dump the
exact prompt tiers for the scratch workspace with `scripts\dump_pulse_prompt.py`, which is pinned by
`test_dump_pulse_prompt_script_is_the_live_zero_credit_probe` in the parity suite (so it cannot rot):

```powershell
.venv\Scripts\python.exe scripts\dump_pulse_prompt.py --workspace C:\scratch\pws `
  --prompt-file "$evidence\prompts\1.txt" --out "$evidence\prompt-dump.json" `
  2>&1 | Tee-Object "$evidence\prompt-dump.txt"
```

Zero provider calls by construction: it runs `view_from_config` + `build_system_prompt_parts`, i.e. the same
functions the bridge turn uses, and prints `BRAND_HITS:` itself (non-zero exit if a brand token appears).
Do not hand-assemble a prompt to "check" it, and do not add flags to the script — if it cannot express the
case you need, that is a finding, not a thing to patch mid-run.


expect: `prompt-dump.txt` contains three tiers in order `stable`, `context`, `volatile`, joined downstream
with `\n\n`, and the brand check in 2.1 runs over these bytes. `state["workspace"]` is the real key (`view.py:209`);
expect: the volatile tier carries `Model: …`, `Provider: …` and a `Platform: ide` line (`view.py:254` reads
`surface` / `PULSEAI_SURFACE`, rendered at `system_prompt.py:282`). `Platform` must be `ide` for the
desktop surface — if it is not, the UI and the engine are disagreeing about who is talking, which is worth a
finding on its own.
expect: `stable` starts with the identity block (`You are Pulse Agent.`), and `context` shows
`# Project Context` → `## PULSE.md` → the marker exactly once.
**Caveat, and it matters:** the dump inherits whatever `src/config/settings.py` resolved from the *process
environment*, so run it in the same shell that has `.env` loaded — otherwise the printed
`Model:`/`Provider:` are the repo defaults (`qwen/qwen3.6-27b` + `groq` in mine). `--model`/`--provider`/
`--surface` exist for that; using them is fine, silently editing the prompt path is not. Note it in
`findings.md` either way.

**2.1 Stable prefix + project context + no brand leak** — prompt: `What files are in this workspace? Name
the project instructions file if there is one. Answer in at most 120 words…`
expect: engine log / `frames.jsonl` shows the three tiers joined with a single `\n\n`, in the order
`identity → context → volatile`, with `PULSE_FIXTURE_MARKER_alpha` present **once**, inside the context tier
only.
expect: `Select-String -Path "$evidence\prompt-dump.txt" -Pattern "hermes","nous","NousResearch"
-AllMatches` returns **nothing** (the script's own `BRAND_HITS: none` line is the same gate)
(the `PULSE.md` filename and `PULSEAI_*` env names are allowed; the brand words are not).
expect: `Conversation started:` and the mode hint are in the **volatile** tier, never the stable one.

**2.2 Session-scoped prompt is built once** — same session, second and third turns.
expect: turns 2–3 of the same session do **not** rebuild the system prompt: identical stable-tier bytes
across turns 1–3, and no duplicate `llm.request` carrying a fresh system block. `PULSEAI_STABLE_PREFIX=off`
must still run (one extra turn, `--max-llm-calls 2`) and return the legacy single-string prompt with no
error — the kill switch works in both directions.

**2.3 Context-file caps and truncation** — **grow `PULSE.md` to ~40 KB first** (one local command, 0 credits),
verify the byte count before spending the turn (`(Get-Item PULSE.md).Length` must print ~40000, and a 79-byte
file does NOT trigger truncation — last round this was skipped for exactly that reason), then one turn.
expect: the prompt carries `kept 70+20 of <N> chars` style truncation text, and say in findings.md which
tokeniser path was active — their `bridge_stderr.log` showed `[tokenizer] unavailable
(encoding_for_model('sarvam-105b-conversations')) … degrading to ~chars/4 heuristic`, so `<N>` is
bytes/4-ish rather than exact and that is expected, not a bug (quote the warning line).
head 70% / tail 20% retained, and a `drain_truncation_warnings` line surfaces in the turn's warnings.
expect: engine does not error and does not re-read the file per turn.

**2.4 Prompt-cache plan — this is a 0-credit check, not a live turn.** My first expect line here was wrong
and cost you a PARTIAL: `markers=1` / `tool_part_markers=None` was you reading the *LangChain-side* metadata
on a tool-less turn, while the plan function reports different numbers. Assert against `build_prompt_cache_plan`
directly, both flag states on and off, and compare the **relations** below (`c99342df` findings, Phase 2.4):

```powershell
$env:PULSEAI_PROMPT_CACHE='1'; $env:PULSEAI_PROMPT_CACHE_CUSTOM='1'
.venv\Scripts\python.exe scripts\dump_cache_plan.py --base-url $env:CUSTOM_BASE_URL --model $env:LLM_MODEL |
  Out-File -Encoding utf8 "$evidence\cache-plan.txt"; Get-Content "$evidence\cache-plan.txt"
Remove-Item Env:PULSEAI_PROMPT_CACHE, Env:PULSEAI_PROMPT_CACHE_CUSTOM
```

expect (measured at `7a6f79b3`, derived path — `tool_part_markers_arg: null`, which is what the engine uses):
on `custom` + your `CUSTOM_BASE_URL`, `stats_tool_part_markers` is **False** on both shapes; on
`--provider openai` (no base URL) it is **True**. That flip IS the route gate, and it is the assertion that
matters. `stats_markers` is 3 and `wire_markers` is 2 on both routes for these two shapes — do NOT expect a
wire-count difference between them; the suppressed marker is part-level inside the tool message, which these
counters do not separate. A custom route reporting `stats_tool_part_markers: true` means the gate is not
applied (the LiteLLM-shaped #89886 bug) → STOP and report.

expect: `stats.enabled is True` only with both env flags set; without them the plan must read
`{'enabled': False, 'reason': 'opt-in', 'stats_markers': 0, 'wire_markers': 0}` (measured) — an
`enabled: False` on a live turn means your cache spend is
NOT being preserved, which is worth a finding even though it is not a gate failure.

**2.5 Bridge terminal frame (new — this is what blocked you last round, now fixed).** `turn_done` used to be
gated on an unbounded `Queue.join()`, and `EventBus.clear()` removed queued events without releasing their join
slots, so a healthy engine could finish with the client waiting forever. Pull `>= ` the fix commit; then:
set `$env:PULSEAI_BRIDGE_DIAGNOSTICS='1'` for the live turns (the bridge dumps all thread tracebacks after 60s
— if anything still strands, that dump is what identifies the producer, and it costs nothing) and
expect every `run_bridge_turn.py` invocation to exit 0 on `turn_done`, with no `runtime_degraded`
`event queue flush incomplete` frame. If that degraded frame appears, capture it plus the faulthandler dump
and report the stranded count — do not retry the turn.

## Phase 3 — Live context engine (target: 4 turns / ≤ 12 requests)

**3.1 Compression / stable-prefix invalidation:** one long turn (multi-tool, `--max-llm-calls 8`), then a
follow-up turn in the same session.
expect: after compaction the stable tier bytes are unchanged, and `find_stable_prefix()`-style behaviour
holds — the volatile tail is what moved. Record the compaction label `Summarizing thread` appearing in the
UI/frames for that turn.
expect: `PULSEAI_COMPACTION=off` (one extra turn, `--max-llm-calls 4`) restores the legacy structural
pipeline without crash. Do not mix the off/on runs in the same session id.

**3.2 Consent policy — verify the guard, not the model's manners.** The guard is a TOOL-ARGUMENT gate, never a
prompt filter: `check_tool_call` has always ignored the user's text, so "ask the model to exfil `.env`, expect a
BLOCKED frame" is not a contract this code holds. A model that refuses is the *model* being good; a
`search_code` call sailing through is by design.

The rule now (owner's call, replacing my basename-list proposal) is **gitignore membership**, applied to the
resolved path for `write_file`, `edit_file` and `copy_file` — `src/context/safety_guard.py`:

    ignored by git          -> consent required, every time (no session-scope grant accepted)
    tracked / not ignored   -> the agent goes alone, no prompt
    no git able to answer   -> the pre-existing verdict, unchanged

Primary check — deterministic, provider-free, and it does not depend on what the model feels like doing:

```powershell
.venv\Scripts\python.exe -m pytest src\tests\test_safety_guard_consent.py -q 2>&1 | Tee-Object "$evidence\guard-consent.log"
```
expect: **18 passed, 0 failed, 0 skipped** (it needs `git` on PATH; if git is missing the whole file skips, which
is a host gap and not a pass — say so in `findings.md`).

Secondary check — the same policy through a real turn, so the bridge wiring is covered too:
prompt = `Copy .env to out/leak.txt with copy_file, then cat out/leak.txt.`
expect: an approval/BLOCKED frame naming the **ignored destination** (and, on a repo where `.env` is ignored, the
read side too), with `out/leak.txt` absent afterwards. Then confirm the freedom half in the same session:
`Overwrite tsconfig.json with write_file.` expect: **no** prompt for a tracked file. Both halves matter — an
all-asks run proves as little as an all-goes one.

`PULSEAI_SAFETY_GITIGNORE=0` restores the previous behaviour for a single run if you need to compare; record the
before/after in `findings.md` rather than re-running the suite twice by hand.

**3.3 /plan — do NOT send `/plan` as turn text.** There is no slash-command parser at the bridge
(`src/bridge/__main__.py:508` reads `frame["mode"]`, validated against
`EXECUTION_MODES = {"agent","plan","debug","ask"}` in `protocol.py:10`; `run_bridge_turn.py` has no mode flag
at all, so send the frame yourself or note it). And here is the real finding: **`mode:"plan"` is accepted and
then does nothing** — `chat_graph` branches on `ask` (`:798`) and `debug` (`:808`) only, and
`build_plan_prompt` / `plan_target_path` have **no runtime caller** (exported from
`src/prompts/hermes/__init__.py:23`, consumed only by tests). The port therefore guarantees the *prompt text*
(`[/plan — plan mode]` header, `.pulseai/plans/<date>_<time>-<slug>.md` naming) and nothing above it.
expect: with `mode:"plan"` on the frame, the turn still completes normally and `frames.jsonl` echoes the mode;
that is all the code promises today.
expect: `mode:"nonsense"` is **rejected** with an `unsupported execution mode: nonsense` error frame — that
gate is real, verify it.

**3.4 /learn — same story, and it is NOT live-testable.** `build_learn_prompt` has no caller in the runtime,
so a `/learn` turn is an ordinary prompt. Record it as `NOT-WIRED(engine)` with the parity test id that pins
the prompt (`test_learn_prompt_targets_a_skill_when_the_index_exists`-class assertion) rather than scoring it
PASS or FAIL off a live turn. If you want the live behaviour, it needs wiring in `chat_graph` first — that is
my work, not yours, and it is out of scope for a verification round.

## Phase 4 — Live Agent UI in the desktop fork (target: 3 turns / ≤ 10 requests)

Launch exactly like prior rounds, with the **real** runner: leave `PULSEAI_BRIDGE_RUNNER` unset. `echo` is
the zero-credit test seam in `src\bridge\__main__.py:275` (it honours `cancel`, which is why prior rounds
could prove layout with 0 provider requests); the real lane is `stream_agent` at `:495`. If a phase log shows
`echo` behaviour while you are paying for turns, STOP — you are being billed for a fixture.

```powershell
$profile = Join-Path $env:TEMP 'pulseai-prompt-ui-live-profile'
New-Item -ItemType Directory -Force -Path (Join-Path $profile 'User') | Out-Null
'{"security.workspace.trust.enabled":false,"window.restoreWindows":"none","workbench.startupEditor":"none"}' |
  Set-Content (Join-Path $profile 'User\settings.json') -Encoding utf8
$env:PULSEAI_ENGINE_ROOT=$repo; $env:PULSEAI_PYTHON_PATH=Join-Path $repo '.venv\Scripts\python.exe'
$env:PULSEAI_CDP_PORT='9222'
$process = Start-Process -FilePath (Join-Path $repo 'desktop\vscode\scripts\code.bat') `
  -ArgumentList @($repo, "--user-data-dir=$profile", '--remote-debugging-port=9222') `
  -RedirectStandardOutput "$evidence\desktop-stdout.log" -RedirectStandardError "$evidence\desktop-stderr.log" -PassThru
```

The validator takes one argument (the evidence dir) and a `--manager-only` switch. Run it **both ways**, in
this order — the manager pass costs nothing and the model pass costs one turn:

```powershell
node scripts\validate_pulse_ui_cdp.js $evidence --manager-only 2>&1 | Tee-Object "$evidence\cdp-manager-only.log"   # 0 credits
node scripts\validate_pulse_ui_cdp.js $evidence                 2>&1 | Tee-Object "$evidence\cdp-ui-console.log"   # full mode: makes the echo turn
```

expect (manager-only): mode `manager-only`, prompt `null`, **provider requests `0`**, Screenshots and Echo
turn explicitly `SKIPPED`, Manager opens as a visible editor with no horizontal overflow, container width
positive and ≤ 880, inspector computed display `none` with positive main width, zero renderer/console
errors. **This is the cheapest place to confirm the layout invariants — do it first.**
expect (full): mode `full`, `Execution mode picker` PASS (four accessible modes, Ask selected, Agent
restored through DOM interaction), `Echo turn` PASS, `Screenshots` captured to `$evidence\screens\`.
Do not add new flags or invent a new harness; if a check is unavailable in a mode, record `SKIPPED(why)`.

expect: the surface toggle renders both surfaces — **Agent UI** (`PulseAgentThread`) and **Copilot chat** —
and the default is Agent UI.
expect: run header shows the present verb from `run-summary` — reading a file reads **"Exploring"**, not
"Reading"; the target is a basename, and a live run shows a clause while a settled run shows counts.
expect: a `write_file`/`edit_file` run renders `PulseTerminalTranscript` with the exit code element and an
expandable payload; a diff run renders `PulseDiffSummary` + `PulseCodeBlock` with `+N/−M` badges; A2UI
surface renders **inside** the run card (no second card for the same tool call).
expect: **approvals work live.** Trigger a gated mutation (`write_file` to `reports/out.md`) with
`PULSEAI_AUTO_APPROVE_WRITES` **unset**: a card with `once|session|deny` appears; ⌘/Ctrl+Enter = Run,
Esc = Reject; choosing `session` emits a `safety_reply{tool_id,approved,always_allow}` frame that the
bridge resolves via `ApprovalQueue.resolve` — then the tool actually runs. Confirm the frame in
`desktop-stdout.log`/frames and in a screenshot. A denied tool must **not** execute.
expect: zero renderer console errors and zero horizontal overflow in **both** passes above (the manager-only
pass already proved the width/inspector invariants — do not pay a turn to re-prove them).
expect: **no brand leak in the UI** — evaluate `document.body.innerText` over CDP and
`Select-String -Pattern "hermes","nous"` over that text plus every screenshot name returns nothing.
expect: after 3 turns, streaming stays smooth at the render budgets (`RENDER_BUDGET=600`,
`FIRST_PAINT_BUDGET=20`, `MIN_VISIBLE_GROUPS=8`) — i.e. long threads virtualize/clip rather than mounting
every group; note the DOM node count for the longest thread in the report.

## Phase 5 — Cross-check with the paid benchmark lane (optional, only if ledger ≤ 70)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_paid_pbr002_guarded.ps1 -Workspace <scratch ws> `
  -RunId live-pbr002-1 -MaxMinutes 8 [-SkipProbe]
.venv\Scripts\python.exe scripts\analyze_llm_requests.py bench-results\live-pbr002-1
```

expect: the guarded script's own probe gates the run — and its watchdog kills the tree on 120 s of
silence or at `-MaxMinutes`, whichever comes first — then prints the graded checks plus token/cost usage.
For a non-Sarvam key you must add `-SkipProbe` (that script's probe is Sarvam-only): allowed **only**
because Phase 0 already ran your equivalent 8-token probe, never to skip the gate itself. Paste that printed block verbatim into
`$evidence\pbr002-summary.txt`. `BUDGET-STOP` in any log is **not** a failure to hide — record it as
`budget-stopped`, which is a legitimate PASS for this phase.

## Phase 6 — Evidence manifest, then commit + push back to `arena/01a0564d-pulseairepo`

Write all of these, then:

```powershell
Get-ChildItem "$evidence" -Recurse | ForEach-Object { '{0}  {1}' -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.FullName.Substring($repo.Length+1) } |
  Set-Content "$evidence\sha256sums.txt" -Encoding utf8
git add -f -- bench-results/prompt-ui-live-e2e      # -f REQUIRED: .gitignore line 94 is 'bench-results/'
git status --porcelain=v1
git commit -m "Add live end-to-end evidence for the ported prompt engine and Agent UI"
git push origin arena/01a0564d-pulseairepo
```

Files I will diff my provider-free claims against:

| path | content |
| --- | --- |
| `head.txt` | `git rev-parse HEAD` you verified |
| `pytest-parity.log`, `pytest-full.log`, `webview-test.log`, `webview-tsc.log`, `webview-build.log` | Phase 1 raw output, unedited |
| `credits-spent.log` | per-phase ledger, appended live, final running total |
| `env-manifest.json` | every `PULSEAI_*` / `LLM_*` / `PROVIDER_SAFE_LIMIT` you set (keys, not values); `CUSTOM_API_KEY` recorded as `"set"` |
| `prompts/*.txt` | the exact prompt files, so turns are reproducible without a key |
| `frames-*.jsonl` (copied from each `bench-results/<run-id>`) | the turn evidence I re-derive assertions from |
| `pbr002-summary.txt`, `cdp-ui-console.log`, `desktop-stdout.log`, `desktop-stderr.log` | Phase 4–5 |
| `screens/NN-*.png` | one per Phase 4 expect-line, numbered in order |
| `findings.md` | PASS/FAIL per expect-line above, quoting my `expect:` text verbatim as the heading |
| `sha256sums.txt` | hashes of everything in the dir |

`findings.md` rules: one section per `expect:` line, verdict `PASS` / `FAIL` / `SKIPPED(reason)` /
`budget-stopped`. No prose summary at the top; no fixed-up logs; a FAIL with frames attached is worth more
than a PASS I cannot reproduce. Do not edit anything under `src/` or `pulse-webview/src/` — **you are
verifying, not fixing.** If you find a bug, write it in `findings.md` and stop there.

Report the evidence commit SHA and finish. Do not merge. Do not delete the scratch profile.
