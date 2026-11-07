# P0.6.4.1 — Desktop Readiness Finalization

**Preflight run:** `p0_6_4_20261107T134317_34bcaf55` (`diagnostics/p0_6_4_1/preflight/`)
**Provider dispatches:** **0** (no paid call was made in this milestone)
**Git:** branch `feat/prompt-cache-stabilization`, HEAD `6bfb6d6dc4e1d842d1b71b9c11b2fa861848fca7`, `desktop/vscode` worktree clean apart from the regenerated bundle below.

## A. Bundle regeneration

```
$ node scripts/emit-crusorai-bundle.mjs
[emit] compiler options inherited from src/tsconfig.json (target ES2024, experimentalDecorators=true)
[emit] copied 8 media file(s) to out/ ...
[emit] DI check ok (11 DI-injected file(s) carry __param)
[emit] wrote 42 file(s)
```

| Check | Result |
| --- | --- |
| Files added / removed | 0 / 0 |
| Files modified | 45 (3 with content changes, 42 EOL-normalisation only under `core.autocrlf=true`) |
| Content changes | `browser/SOURCES_HASH`, `browser/SOURCES_MANIFEST.json`, `browser/crusorAIRenderer.js` (trailing-whitespace normalisation the emitter documents) |
| Media byte-identity | 6 checked, 0 mismatches |
| `SOURCES_HASH` | `6d3594d3ab3ce2a5e8c4bd6695bcce3a177bb0bafb0c7091649c8a622c462f11` — matches independently recomputed sources |
| `SOURCES_MANIFEST.json` | 50/50 source entries present, hashes match |
| DI check | ok (11 files carry `__param`) |
| Scope | every changed path is under `desktop/vscode/out/vs/workbench/contrib/crusorai/` |
| Idempotency | second run produced 0 differing files |
| Unrelated files | none touched (`diagnostics/` evidence dirs only) |

Raw data: `baseline.json`, `regeneration.json`, `after_emit_1.json` in this folder.

The bridge now reports it itself:

```
[bridge] desktop UI: compiled workbench matches the pulled crusorai sources (sha256) — panel is current
```

## B. Acceptance-specific retry clamp

New module `src/llm/acceptance_guard.py`, activated **only** when
`CRUSORAI_ACCEPTANCE_RUN_ID` is set (the bridge does this at construction;
`CRUSORAI_ACCEPTANCE_MAX_DISPATCHES`, default 5).

Enforcement points (all inside existing choke points, no duplicated policy):

| Requirement | Implementation |
| --- | --- |
| `RetryLLMProxy.max_attempts = 1` | `RetryLLMProxy.__init__` → `clamp_max_attempts()`; every proxy built in the process, from any stage |
| SDK `max_retries = 0` | `enforce_sdk_single_retry(llm)` in `RetryLLMProxy.__init__`; forces 0 or raises `AcceptanceDisciplineError` (fails closed) |
| No automatic failover | no second attempt exists: the attempt loop is clamped to 1, and every attempt must claim a dispatch slot |
| ≤5 dispatches across the turn | `claim_dispatch()` immediately before `_invoke_provider` (before the `llm.request` telemetry too), shared by planning, implementation, aux and any other lane |
| 6th dispatch prevented pre-provider | `AcceptanceBudgetExceeded` is raised by the claim, outside the provider `try` block |
| Normal behaviour preserved | inactive guard → `clamp_max_attempts` is the identity, `claim_dispatch` returns `None`, retry policy untouched |
| Evidence | `AcceptanceGuard.snapshot()` + `write_evidence()` (path from `CRUSORAI_ACCEPTANCE_EVIDENCE_PATH`), also printed to stderr at bridge exit |

Coverage note: every chat provider in the engine is built by
`src/llm/factory.get_llm()` (planner, `chat_graph`, `model_adapter`, oneshot,
titling, `get_auxiliary_llm` → `RequestScopedAuxLLM._bind`), and each is wrapped
in `RetryLLMProxy` — the same place the clamp and the claim live. The five
`src/providers/*.py` modules are unused legacy singletons (no importer), noted
rather than claimed.

Tests: `src/tests/test_p0_6_4_1_acceptance_retry_clamp.py` — **11 passing**
(one attempt; retryable error does not retry; SDK retries forced to 0 and
read-only clients rejected; five-dispatch limit; normal mode keeps 3 attempts;
cross-stage shared budget with no unmetered path; env activation; evidence
ledger).

## C. Forced CDP port — root cause and resolution

**Root cause (evidence-based):** VS Code re-applies every supported Electron
switch from a **per-user** `argv.json`:

```js
// out/main.js
function getArgvConfigPath() {
  let dataFolderName = product.dataFolderName;         // ".crusorai-ide"
  if (process.env["VSCODE_DEV"]) dataFolderName += "-dev";
  return path.join(os.homedir(), dataFolderName, "argv.json");
}
...
app.commandLine.appendSwitch("remote-debugging-port", argvValue);
```

`C:\Users\Administrator\.crusorai-ide-dev\argv.json` contains:

```json
{ "enable-crash-reporter": true, "remote-debugging-port": "9222" }
```

That append runs after the launcher's switch and wins, which is why the port
was 9222 even with `--remote-debugging-port=9444`, and even with no switch at
all. It also explains why stock `electron.exe` + the same app tree produced
9222: the binary was never responsible.

**Resolution (non-destructive):** `VSCODE_PORTABLE` is the supported
redirection — pointing it at an existing directory makes VS Code read
`<dir>/argv.json` instead of the user's home. The harness now:

1. allocates a free loopback port (`allocate_loopback_port()`, `--port 0` default);
2. creates `diagnostics/p0_6_4_1/preflight/portable/argv.json` naming that port;
3. launches with `VSCODE_PORTABLE=<that dir>`;
4. still **verifies** the effective port from `DevToolsActivePort` / stderr and
   fails the lane on any non-loopback bind.

The user's own `~/.crusorai-ide-dev/argv.json` is untouched (recorded read-only
in the evidence as `electron.argv_config`).

Preflight proof: requested `51022`, bound `51022`, `port_overridden: false`,
listener `127.0.0.1:51022` owned by the app PID, no public bind.

## D. Provider-free desktop preflight

| Check | Result |
| --- | --- |
| Panel bundle current | `stale: false`, sha256 match |
| Real executable | `.build/electron/CrusorAI.exe`, pid recorded, sha256 |
| CDP | attached to `ws://127.0.0.1:51022`, target `vscode-file://…workbench-dev.html` |
| Workbench ready | `true`, `hasWorkbench: true`, title `crusor_p0_6_4_workspace_0v8f384l - CrusorAI IDE Dev` |
| Composer | `textarea.crusorai-composer-input`, count 1, visible, enabled, placeholder "Ask anything, / for commands, @ for context…" |
| Worker / bridge | Python descendants; handshake `crusorai` v0.2.0-runtime protocol 2; session minted; workspace bound; clean exit 0 |
| Renderer console | 0 unhandled errors, 0 rejections, 0 `console.error`, 3 upstream `theme-defaults` warnings |
| Provider dispatches | **0** |
| Shutdown | clean (0 leftover processes) |
| Shim absent | `out/main.js` line 7 = `import { app, protocol, crashReporter, Menu, contentTracing } from "electron";`; 0 `electronModule` occurrences; generated by the 8 324-file transpile |
| Invariant 7 | maintained; 45 changed files, all under `out/vs/workbench/contrib/crusorai/`; 0 undeclared, 0 drift |

Screenshots: `preflight/screenshots/renderer-workbench.png`, `renderer-composer.png`.

## Files changed by this milestone

- `desktop/vscode/out/vs/workbench/contrib/crusorai/**` — 45 regenerated files (3 content, 42 EOL)
- `src/llm/acceptance_guard.py` — new
- `src/llm/factory.py` — clamp + SDK check + dispatch claim (3 insertions)
- `src/bridge/__main__.py` — env activation + ledger flush
- `src/tests/test_p0_6_4_1_acceptance_retry_clamp.py` — new (11 tests)
- `src/tests/test_p0_6_4_desktop_observability.py` — +5 port tests (30 total)
- `benchmarks/crusor_desktop_acceptance/*` — dynamic port, portable profile, argv evidence, readiness gate
- `docs/P0_6_4_DESKTOP_ACCEPTANCE_HARNESS.md`, `diagnostics/p0_6_4_1/**`

Nothing was committed or pushed.
