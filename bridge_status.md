# Bridge silence investigation — final status

## API key — working
One live call to Sarvam (`custom` provider → `https://api.sarvam.ai/v1`, model
`sarvam-105b-conversations`) returned `'\nOK'` in ~0.8 s (~21 tokens). Loaded
from `.env` (gitignored, not committed).

## Already verified
- Protocol v2 `hello` frame, engine `pulseai`, protocol 2.
- Echo-runner mechanics (deterministic, no model call).
- Real model at graph level (in-process `stream_agent`, real `OK` reply).
- Branded desktop launch, utility-process creation, optimized worker packaging.

## Root cause of the 420 s bridge silence — FOUND and FIXED
The real turn was **not** blocked on approval, and the key/provider were fine.

The faulthandler watchdog (`PULSEAI_BRIDGE_DIAGNOSTICS=1`, moved to the top of
`_run_turn` so it covers imports) captured the stuck thread stack:

```
Thread [bridge-turn-<sid>] (most recent call first):
  ... <frozen importlib._bootstrap> in create_module
  File "...\numpy\_core\multiarray.py", line 11 in <module>   <-- BLOCKED
  ... transformers\utils\... -> langchain_core\language_models\base.py
  File "D:\pulseAIagent\PulseAIRepo\src\bridge\__main__.py" in _run_turn
```

The `bridge-turn-*` worker thread deadlocked inside **numpy's C-extension init**
(`numpy._core.multiarray create_module`), pulled in via `transformers` through
the lazy `from src.graphs.chat_graph import stream_agent` in `_run_turn`.
Importing numpy/transformers on a **non-main thread** deadlocks on Windows;
the same imports complete in ~11 s on the main thread (fresh-process test).

**Fix (commit `57e79921`):** warm the heavy turn-path imports on the main
thread in the prompt handler before dispatching the turn worker, so the
worker's own imports are instant no-ops from `sys.modules`.

## Controlled real-model confirmation — PASS
One tiny prompt (`"Reply with exactly: OK"`), watchdog on, stdout/stderr
separated:

```
PASS hello protocol=2 engine=0.2.0-runtime
PASS session_info=slice-confirm
PASS turn_started=True
RESULT frames = [hello, session_info, turn_started, reasoning, token, telemetry, turn_done]
RESULT done.type=turn_done completed=True tokens=1 elapsed=65.8s (turn=53.1s)
RESULT reply='\nOK'
```

- First frame after `turn_started`: the bridge's own `reasoning` liveness frame
  ("Preparing workspace context…"), then a real `token`, `telemetry`, `turn_done`.
- stdout carried JSON frames only (raw-bytes probe: every line was a JSON frame).
- stderr held the graph diagnostics (`[ContextEngine] context window 32,768 ...`).
- No watchdog dump needed — the turn completed in 65.8 s, under the 60–90 s
  window. `_project_event` / forwarder stayed alive (turn_done flowed through it).
- Exact block location: `numpy._core.multiarray` create_module on the
  `bridge-turn-*` thread during the lazy `chat_graph` import.

## Tests
- New transport suite (no model calls): stdout purity, stderr blocking, frame
  validity under concurrent diagnostics, fake delayed turn, fake approval with
  exact-`tool_id` resolution, forwarder-exception `runtime_degraded`.
- 26 bridge tests pass (7 new transport + 19 existing); broader engine-focused
  suite 47 passed earlier.

## Commits (separate, per instruction)
- `cf5d1d9a` — transport isolation + tests (stdout ownership, locked emit,
  forwarder hardening, watchdog, stderr draining, 7 transport tests).
- `57e79921` — behavioral fix: main-thread import warm-up (numpy deadlock).

## Open / not verified
- Mid-turn cancel, approval-diff UI, crash/restart backoff, replay dedup:
  driver-ready but not re-run end-to-end with a live model (credit-conscious).
