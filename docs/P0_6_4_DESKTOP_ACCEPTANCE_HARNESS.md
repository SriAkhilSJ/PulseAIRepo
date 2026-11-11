# Crusor Desktop Acceptance Harness (P0.6.4)

Offline-first observability for the **real** Crusor Electron application. The
harness exists because previous milestones proved the Python pipeline with
scripts that called `ModelExecutionAdapter` directly: they never produced a
single artefact proving the desktop app itself was running, was attached over
CDP, or was driving the engine.

This package captures that evidence. It does **not** submit engineering
prompts and does **not** call a model provider.

## What it proves (and how)

| Layer | Evidence written | Source of truth |
| --- | --- | --- |
| Electron process | exe path + sha256, PID/PPID, image version, product.json identity, launch args, timestamps, exit code | the OS process table and the image itself |
| Debug endpoint | actual listener address + owning PID, `/json/version` | `Get-NetTCPConnection`, refuses any non-loopback bind |
| Renderer | target id, ws origin, page title/URL, `.monaco-workbench`, Electron UA, composer snapshot, screenshot | `Runtime.evaluate` **inside the real renderer** |
| Renderer console | unhandled `error`, `unhandledrejection`, `console.error/warn` | hooks installed in the live renderer |
| Worker/bridge | process tree under the app PID, `python -m src.bridge` PID, hello handshake, session mint, `workspace.bound`, clean shutdown, stderr tail | the real bridge over its real stdio protocol |
| Governance | verified pricing, input-token upper bound, max request cost vs ₹ budget, retry/failover posture | the production `PricingRegistry` / adapter helpers |
| Code OSS Invariant 7 | declared overlay hashes, drift, undeclared worktree changes | `desktop/SELECTIVE_MANIFEST.json` + git |

## Guarantees

1. **One immutable run id** (`RunContext.run_id`), frozen in `run.json`. A
   second run cannot adopt an existing evidence directory.2. **Append-only ledger** (`evidence.jsonl`). Records are never rewritten.
3. **No paid frames.** The bridge probe can only send frames on
   `PROBE_ALLOWED_FRAMES`; every provider-capable frame type (`prompt`,
   `oneshot`, `subagent_launch`, `inline_completion`, `next_edit_suggestions`,
   `voice_transcribe`, `skills_hub_op`, ...) raises `PaidCallRefused` before it
   reaches the pipe.
4. **Loopback-only CDP.** `assert_loopback` rejects non-local websocket URLs,
   and the port wait fails the lane if the endpoint is bound to `0.0.0.0` or a
   LAN address.
5. **The debugging port is discovered, never assumed.** Chromium's
   `DevToolsActivePort` file and the app's own `DevTools listening on ws://…`
   line are read back. This matters: the current Crusor build binds **9222**
   regardless of the requested port (see `diagnostics/p0_6_4/FINDINGS.md`).
6. **A crash is reported as a crash.** If the app exits before serving an
   endpoint, the lane fails immediately with the exit code and the fatal stderr
   lines — it does not sit out the timeout and then claim "slow start".
5. **No fabricated identifiers.** `record_dispatch` / `record_usage_receipt`
   raise `EvidenceIncomplete` unless the provider request id, reservation id
   and desktop turn id are all real.
6. **Honest correlation.** Records are joined on
   `(run_id, session_id, turn_id)` — never on a task name. A provider or
   mutation record without a matching `ui.submit` turn record is classified
   *disconnected*.
7. **A crash is reported as a crash.** If the app exits before serving an
   endpoint, the lane fails immediately with the exit code and the fatal stderr
   lines — it does not sit out the timeout and then claim "slow start".

## Usage

```powershell
# full capture: launch the app, attach, probe the bridge, check governance
python -m benchmarks.crusor_desktop_acceptance --port 9333

# offline lanes only (no window is opened)
python -m benchmarks.crusor_desktop_acceptance --skip-desktop

# keep the window open for inspection after capture
python -m benchmarks.crusor_desktop_acceptance --keep-app

# P0.6.5: validate every gate and type the prompt WITHOUT submitting (no credits)
python -m benchmarks.crusor_desktop_acceptance --live-turn --stop-before-submit

# P0.6.5: one real desktop turn (spends provider credits; <=5 dispatches, 1 attempt each)
python -m benchmarks.crusor_desktop_acceptance --live-turn --evidence-dir diagnostics/p0_6_5/live
```

`--live-turn` drives the real composer over CDP (focus, `Input.insertText`,
`rawKeyDown` Enter), waits for the panel's own **"Crusor ready"** chip, proves
worker→bridge ownership by process ancestry, requires the acceptance ledger to
have been written by that bridge process, then reads the turn manifest, journal,
financial state and mutation ledger the application itself produced. Every gate
is checked before submission, so a broken environment aborts without spending.

Outputs (`--evidence-dir`, default `diagnostics/p0_6_4/`):

- `run.json` — immutable run identity
- `evidence.jsonl` — append-only per-layer records
- `evidence.json` — merged summary + criteria classification
- `report.md` — human-readable report
- `screenshots/` — real renderer captures
- `logs/` — Electron stdout/stderr
- `user-data/` — isolated profile (never the user's real profile)

## Readiness findings for this checkout

`diagnostics/p0_6_4/FINDINGS.md` records what the harness found on the machine
it was built for. Two things are worth knowing before the first live turn:

- The gitignored build artifact `desktop/vscode/out/main.js` had been hand-patched
  with an Electron stub fallback that `src/main.ts` does not contain. With it in
  place the workbench window never got a renderer process. `out/` was regenerated
  from `src/` with `npm run transpile-client`. If the panel window is ever blank
  again, compare `out/main.js` with `src/main.ts` first.
- The app used to bind Chrome DevTools on 9222 no matter what port was passed.
  Root cause: VS Code re-applies every supported Electron switch from the
  **per-user** `~/<dataFolderName>-dev/argv.json`, which contained
  `"remote-debugging-port": "9222"`. The harness now launches with
  `VSCODE_PORTABLE` pointing at an acceptance-owned profile whose `argv.json`
  names the dynamically allocated loopback port, so the request is honoured and
  the user's real profile is never modified (`--port 0` is the default).

## What this harness deliberately does not do
- It does not type into `textarea.crusorai-composer-input` or submit a turn.
  Doing so in the next milestone is a separate, explicitly authorised step; the
  correlation seams (`ui.submit`, `provider.dispatch`, `provider.usage_receipt`,
  `finops.snapshot`, `mutation.receipt`, `render.response`) are already wired.
- It does not modify Electron/VS Code sources. The only files it writes live
  under the evidence directory.
- It does not repair a stale compiled workbench. If the bridge reports
  `DESKTOP WORKBENCH STALE`, that is recorded as a finding — re-emitting the
  bundle (`node scripts/emit-crusorai-bundle.mjs`) is a reviewed change of its
  own, not a side effect of an observation run.

## Tests

```powershell
python -m pytest src/tests/test_p0_6_4_desktop_observability.py -q
```

The suite covers run immutability, ledger append semantics, foreign-run
rejection, disconnected-record detection, three-state criteria classification,
provider-identifier enforcement, the paid-frame allowlist, CDP target
selection/loopback enforcement, renderer identity checks, Invariant 7 drift
detection, and offline budget arithmetic.
