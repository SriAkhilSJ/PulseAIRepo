# CRUSOR — PACED STREAMING EXPERIMENT

**Date:** 2026-11-11 · **Branch:** `feat/prompt-cache-stabilization` · **HEAD:** `27706b6e`
**Mode:** measurement only — no renderer optimisation, no production behaviour change.
**Provider calls:** 0 · **Provider ledger rows:** 0

> ## Headline
> **The pacing seam is implemented, gated and tested (13 tests pass).**
> **The three-condition experiment did NOT run: the Electron engine never reached `ready`.**
> No measurement in this document is fabricated or extrapolated from a run that did not happen.

---

## 1. Pacing implementation

**File:** `src/llm/scripted_model.py` (test seam only — the production model path is untouched)

| Item | Detail |
|---|---|
| Variable | `CRUSORAI_TEST_CHUNK_DELAY_MS` |
| Default | absent / empty → **0 ms**, i.e. the previous exact behaviour |
| Authorized values | integer `0…500`; `20` ≈ 50 chunks/s, `30` ≈ 33 chunks/s |
| Out of range / non-numeric | `RuntimeError` (fails loud, never silently clamps) |
| Authorization gate | requires **both** `CRUSORAI_TEST_MODE=1` and `CRUSORAI_TEST_LLM_SCRIPT`; a delay set during a real-provider run is ignored |
| Chunk text / order | preserved byte-for-byte; sleep occurs **between** callbacks, never before the first |
| Paths covered | `_emit_stream()` (callback streaming used by the graph) and `stream()` (generator path) |
| ModelGateway | not touched |

**Execution-context check (done before writing the delay).** The bridge runs each turn on a
dedicated worker thread (`src/bridge/__main__.py`: `self._workers: dict[str, threading.Thread]`),
so a bounded sleep paces that turn only. The implementation still guards the dangerous case:

```python
try:
    asyncio.get_running_loop()
except RuntimeError:
    time.sleep(delay_s)          # worker thread: safe pacing
else:
    print("[scripted-model] … ignored: called on an asyncio loop thread", file=sys.stderr)
                                 # loop thread: skip rather than stall the bridge
```

The renderer and Electron main process are never affected — they only see frames later than before.

### Tests — `src/tests/test_scripted_model_pacing.py`

```
13 passed in 9.24s   (8 new + 3 existing seam tests + 2 parametrised cases)
```

Covered:
1. no env → no sleep (default is unchanged behaviour);
2. delay set **without** test authorization → ignored;
3. authorized 20 ms → exactly `len(chunks)-1` sleeps of 0.020 s, chunk text/order identical;
4. `abc`, `-5`, `501`, `100000` → `RuntimeError`;
5. upper bound 500 ms accepted;
6. on an asyncio loop thread → **no sleep** (proven with a real `asyncio.run`);
7. worker-thread path → sleeps;
8. `stream()` path preserves order and the trailing usage-only chunk.

---

## 2. Engine startup diagnosis

### 2.1 What was checked, and the result

| Hypothesis | Test | Result |
|---|---|---|
| Protocol mismatch workbench ↔ bridge | workbench constant `2` vs `src/bridge/protocol.py:7` `2` | **Ruled out** |
| Bridge handshake implementation broken | piped `{"type":"hello","protocol":2}` into `python -m src.bridge` | **Pass** — replies `{"type":"hello","protocol":2,…}` |
| Wrong engine root / missing python | set `CRUSORAI_PYTHON_PATH` + `CRUSORAI_ENGINE_ROOT` exactly as `run_crusor_full_stack.ps1:25-26` | No change |
| Port 8931 owned by a foreign session | found **12 orphaned** `src.preview.server` processes from earlier launches; terminated only those owned by `bench-results` | Cleared; no change |
| Pane never opened (previous assumption) | added `ensure_panel()` — Ctrl+L, then command-palette `Crusor: Open Agent`, with composer verification | **Pane does open** (composer found) in minimal mode |
| Engine crash / handshake timeout surfaced | grep logs for `start failed`, `handshake timed out`, `invalid bridge frame` | **Absent** in every run |

### 2.2 Exact observed sequence (runs 5–8, identical)

1. Workbench starts, CDP attaches, `ensure_panel()` finds `textarea.crusorai-composer-input`
   → panel mounted, `{"how":"already-open","ok":true}`.
2. Bridge stderr reaches the workbench log:
   `[env] loaded…`, `[bridge][acceptance] run=…`, `[bridge][memory] policy check…`,
   `[bridge] engine build: unknown`, `[bridge] desktop UI: compiled workbench matches…`.
3. **Nothing further.** No `hello`, no `session_info`, no `[turn]`, no `start failed`.
4. By the time the 150 s bound expires, `.crusorai-engine-status` is **gone** and the composer
   is **gone** — the pane unmounted. Screenshot evidence:
   `bench-results/performance/repaint_probe/probe_run5_190940/abort.png` shows the workbench with
   Explorer + welcome page only, no Crusor pane.
5. `~/.crusorai` and the per-run `CRUSORAI_HOME` both receive state (`sessions.db`,
   `preview/ide.json`) — so Python ran and wrote, but the pane binding did not survive.

### 2.3 What this narrows it to

The bridge process starts and logs; the pane mounts then **unmounts**; no handshake error is
recorded. The three candidate causes, in order of likelihood:

1. **View-container disposal** — the auxiliary-bar container hosting the pane is disposed
   (layout restore / focus change) *before* `engine.start()` completes, so the handshake promise
   has no owner and the 45 s timeout is never logged because the service object is disposed.
2. **Worker stdout relay** — the utility-process worker spawns Python (stderr relayed, proven by
   the log lines) but the stdout→frame channel never delivers the `hello` line.
3. **Engine service never invoked** — the pane renders the idle shell (composer) but `start()`
   is skipped because the workspace was not yet adopted at mount time.

Distinguishing (1) from (2) needs one artefact I could not obtain without a product change:
a log line at `CrusorAIEngineService.start()` entry and at `send(hello)`.

---

## 3. Experiment status

| Condition | Delay | Runs attempted | Runs completed |
|---|---:|---:|---:|
| Control | 0 ms | 6 (runs 1–8 incl. isolation work) | **0** |
| Paced A | 20 ms | 0 | 0 |
| Paced B | 30 ms | 0 | 0 |

**No chunks-per-paint, frame, long-task or CPU-profile numbers are reported for the paced
conditions, because no paced turn executed.** The only valid data remains the previous
single control run (`275 chunks → 6 repaints`, 1,246 ms long tasks), already documented in
`CRUSOR_STREAMING_REPAINT_DIAGNOSTIC.md`.

Fail-fast discipline held: every attempt aborted at **150 s** with a screenshot and a pane probe,
never a 180 s dead wait. No unrelated process was terminated; only benchmark-owned
`CrusorAI.exe` and `src.preview.server` instances were stopped.

---

## 4. Answers to the questions (scope-limited)

| Question | Answer |
|---|---|
| 1. Does 20–30 ms pacing produce progressive text? | **UNKNOWN** — not executed. Predicted yes from source (`render()` coalesces per frame; 20–30 ms spacing > 16.7 ms frame interval). |
| 2. Does the ratio approach one update per frame? | **UNKNOWN** — needs the paced run. |
| 3. Does frame coalescing work as intended? | **PARTIAL** — proven for the burst case (275→1 token paint). |
| 4. Is full transcript rebuilding still expensive? | **UNPROVEN** — consistent with 8 long tasks / 1,246 ms, but no call-stack evidence. |
| 5. Which functions consume main-thread time? | **UNKNOWN** — profiler never captured a completed turn. |
| 6. Does long-task duration grow with transcript size? | **UNKNOWN** — would need 1k vs 5k with a completed paced run. |
| 7. Renderer or another layer is the bottleneck? | **UNKNOWN** — engine startup is currently the blocker, not the renderer. |

---

## 5. Recommended minimal renderer optimisation (not justified yet — do not apply)

Hold until the paced run exists. The candidate remains: append-only live text part with the
markdown pass deferred to the end of a streamed block. It targets `renderer.ts:5103`
(`slot.replaceChildren(markdownCopy(streaming.text))`) and the full rebuild at `:5143`.

Regression risks unchanged: unclosed fences/tables split across chunks, list continuation,
surrogate-pair splits, selection preservation, scroll anchoring, and final-output parity with
today's whole-message render.

---

## 6. Reproduction commands

```powershell
# pacing seam tests
.\.venv\Scripts\python.exe -m pytest src/tests/test_scripted_model_pacing.py src/tests/test_scripted_model_seam.py -q

# one experimental condition (blocked at engine readiness today)
$env:PYTHONPATH = $PWD
.\.venv\Scripts\python.exe bench-results\performance\stream_repaint_probe.py --run 1   # add CRUSORAI_TEST_CHUNK_DELAY_MS via the probe env
```

---

## 7. Unverified / open

- Engine readiness under an isolated profile (blocker).
- Whether the `hello` frame is emitted by the worker or lost in the relay.
- Paced repaint ratio, frame timings, long-task attribution, CPU profile.
- Light-theme rendering path (`B-DESK-002` still open).

**Workspace:** 184 dirty entries preserved; new files are the pacing seam, its test, the probe
harness and this report. No reset, clean, stash, revert, commit or push. Ledger rows = 0.
