# P0.6.4 — Desktop Readiness Findings

**Run:** `p0_6_4_20261107T124907_e0724ae1`
**Evidence:** `diagnostics/p0_6_4/` (`run.json`, `evidence.jsonl`, `evidence.json`, `report.md`, `logs/`, `user-data/`)
**Mode:** offline only — **0 provider dispatches**, **0 paid frames**, no prompt submitted.
**Git:** `6bfb6d6d` on `feat/prompt-cache-stabilization`; `desktop/vscode` worktree clean.

## What this run proves

| Claim | Evidence |
| --- | --- |
| The real desktop binary exists and is launched by the harness | `electron.launch`: `desktop/vscode/.build/electron/CrusorAI.exe`, sha256 recorded, PID 23308, full argv, isolated `--user-data-dir` |
| The harness speaks to the **real** Python bridge | `bridge.handshake`: `engine=crusorai`, `protocol=2`, `engine_version=0.2.0-runtime`; `bridge.session`: `session-0a1617568f8f441ba7dc91d9a01719ac`, `workspace.bound`; `bridge.shutdown`: exit `0` |
| Offline safety is enforced, not promised | bridge probe allowlist refuses `prompt`/`oneshot`/`subagent_launch`/… (`src/tests/test_p0_6_4_desktop_observability.py`); `acceptance.offline_assertion` records `provider_dispatches: 0` |
| Budget arithmetic still works | `finops.preflight`: pricing verified ($0.05/1M in, $0.20/1M out), bound 156 tokens, ceiling 2048, max cost INR 0.038657 ≪ ₹5.00 |
| Code OSS Invariant 7 holds | `acceptance.invariant7`: all 5 declared overlay hashes match, `desktop/vscode` has 0 changed files, 0 undeclared changes |
| The bridge is honest about UI freshness | `bridge.workbench_freshness`: `stale = true` |

## Blockers found (pre-existing, not caused by this milestone)

### B1 — the workbench crashes at window creation, so no renderer ever exists

Every launch (4 independent runs, including one with no extra switches) ends the same way:

```
[main] TypeError: this._win.webContents.session.setProxy is not a function
    at CodeWindow.onConfigurationUpdated
       (desktop/vscode/out/vs/platform/windows/electron-main/windowImpl.js:755)
    at new CodeWindow (…/windowImpl.js:469)
    at WindowsMainService.openInBrowserWindow (…/windowsMainService.js:1053)
→ exit code 1
```

Consequence: no `BrowserWindow`, therefore no `.monaco-workbench`, no `textarea.crusorai-composer-input`, and no CDP **page** target. Criteria 2–5 and 9–10 of the desktop acceptance table are `NOT VERIFIED` for a real reason, not for lack of instrumentation.

Scope note: `src/vs/platform/windows/electron-main/windowImpl.ts` is **upstream VS Code**, not a declared overlay file. Fixing it is a reviewed change with an Invariant 7 decision; this milestone deliberately did **not** patch it.

Likely cause to investigate: the fork ships Electron `42.8.1`, where the default-session accessor no longer exposes `setProxy` while a `BrowserWindow`'s session still does. A guard (`typeof …setProxy === 'function'`) or an Electron↔upstream alignment is the shape of the fix.

### B2 — the build force-binds CDP on port 9222, ignoring the requested port

| Launch | Requested | `DevToolsActivePort` | stderr |
| --- | --- | --- | --- |
| harness run | 9333 | **9222** | `DevTools listening on ws://127.0.0.1:9222/…` |
| probe | 9444 | **9222** | same |
| probe | *no switch at all* | **9222** | same |
| stock `electron.exe` 42.8.1 | 9333 | 9333 | same |

So the port is not inherited from our arguments and not an Electron default: **this application build enables CDP on 9222 unconditionally**. No occurrence of `9222` exists in tracked sources, the compiled `out/` JS, `product.json`, `argv.json`, or the binary's strings, so the origin is not in this checkout's code and is recorded as an unexplained build-level default.

Mitigations already shipped in the harness: the endpoint is *discovered* (`DevToolsActivePort`, then the app's own stderr), never assumed; and any non-loopback bind still fails the lane. Security consequence to fix upstream: an always-on debug port on developer machines.

### B3 — the shipped Agent panel is stale relative to its sources

The bridge's own freshness gate reports:

```
DESKTOP WORKBENCH STALE: the shipped panel was emitted from DIFFERENT crusorai sources
(sha256 e7f9f650588c… != 6d3594d3ab3c…) — the Agent pane will render OLD cards
```

Independently recomputed: current sources hash `6d3594d3ab3ce2a5e8c4bd6695bcce3a177bb0bafb0c7091649c8a622c462f11`, shipped `e7f9f650588cfa04ce8598e401c291baa6949c29daf04a0b94e5fa1d624b0bad`. Repair is `node scripts/emit-crusorai-bundle.mjs` in `desktop/vscode`, which rewrites **594 tracked** files under `out/vs/workbench/contrib/crusorai/` — a reviewable change of its own, so it was not performed inside an observation run.

## Observation (not a blocker for P0.6.4, blocking for a live turn)

`provider.retry_posture`: `RetryLLMProxy._max_attempts = 5` in the default configuration (inner client `max_retries = 0`, no failover). A live acceptance run must force `_max_attempts = 1` exactly as P0.5.2 did, or a transient failure becomes five paid dispatches.

## What this changes about P0.6.2

P0.6.2's `PASS` was produced by a Python harness calling `ModelExecutionAdapter` directly; P0.6.3 classified the desktop interaction criteria as unverified. This run shows *why* they could never have been verified in this checkout: the window does not open. Recorded evidence now exists for that claim instead of an argument about it.

## Ordered next steps (each separately reviewable)

1. Fix B1 (`windowImpl` `setProxy` guard or Electron/upstream alignment) → window must reach `.monaco-workbench`.
2. Remove or parameterise B2's hardcoded 9222 endpoint.
3. Re-emit the panel bundle for B3 and confirm `SOURCES_HASH` matches.
4. Re-run `python -m benchmarks.crusor_desktop_acceptance` — expect the composer record and a screenshot.
5. Only then run the live desktop turn (P0.6.5), with `_max_attempts = 1`, ≤5 dispatches, ₹5 cap, and the correlation seams already wired (`ui.submit` → `provider.dispatch` → `provider.usage_receipt` → `finops.snapshot` → `mutation.receipt` → `render.response`).
