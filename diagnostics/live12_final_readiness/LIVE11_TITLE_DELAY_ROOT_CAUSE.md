# LIVE11 Title Delay — Root Cause

## 1. Evidence identity

| Item | Value |
|---|---|
| Run | `p0_6_5_20261108T000751_06427b06` |
| Electron PID | 12804 |
| Bridge PID | 4356 |
| Engine root | `C:/Users/Administrator/Downloads/CRUSORAI/PulseAIRepo` |
| Bridge source path in stack | `...\PulseAIRepo\src\bridge\__main__.py` |
| Python | uv CPython 3.14.4 (`.venv` shim over `AppData\Roaming\uv\python\cpython-3.14...`) |
| Source commit | `563f5cc2` (`[bridge] engine build: 563f5cc2 2026-11-07 23:56:02 -0800`) |

`src/bridge/__main__.py` at Live11 (`563f5cc2`) and at `6959c862` is the same
file (SHA-256 `0857f33c…`). At both commits `_engine_build()` contains:

```python
subprocess.run(["git", "log", "-1", "--format=%h %ci"],
               capture_output=True, text=True, timeout=3, cwd=engine_root)
```

The earlier preflight statement "no timeout" was wrong. The timeout existed.

---

## 2. Actual timeline

| Time (UTC) | Event | Source |
|---|---|---|
| 08:08:18.933 | Startup `_engine_build()` returns `563f5cc2 …` and is logged | `electron.stderr.log` |
| 08:08:52.491 | Title provider invocation starts (`inv_03ac…`) | `provider_invocations.jsonl` |
| 08:08:54.976 | Title provider settles: 461/64, ₹0.004809 | same |
| 08:08:54.984 | Title model returned no usable text; local fallback | `electron.stderr.log` |
| 08:09:26.985 | 60 s watchdog stack: worker in `_engine_build` -> `emit` -> `_run` -> `_maybe_autotitle_session` | same |
| 08:18:13.263 | `turn.completed` (`completed=true`) | `runtime_events.db` |
| 08:18:13.360 | `[bridge] turn end … wall=586.3s` | `electron.stderr.log` |
| 08:18:14.556 | Electron stopped | `electron_shutdown` |

Title provider latency: **2.484 s**. The fallback was immediate. The block
began after the title text was available.

---

## 3. What blocked

The worker thread stack at 08:09:26.985 is unambiguous:

```text
_maybe_autotitle_session -> _run -> emit -> _engine_build
  -> subprocess.run -> communicate -> _communicate
  -> _readerthread (subprocess.py:1614, waiting)
```

`emit()` called `_engine_build()` for a `session_info` frame. The Git
subprocess did not return despite `timeout=3`; the reader threads remained
blocked and `_communicate` waited. The turn's terminal frame could not be
emitted until that call returned at the end of the window (~558 s after the
fallback).

**Mechanism:** on Windows, `subprocess.run(..., capture_output=True,
timeout=3)` can still block after the timeout if a descendant process inherits
the stdout/stderr pipes; `_communicate` waits for the reader threads to reach
EOF. The exact child tree of that Git invocation was not preserved, so the
descendant/pipe mechanism is an evidence-based inference, not a captured
process tree. The **blocking path itself** is directly evidenced by the stack
and timing.

**Call count:** every `session_info` frame calls `_engine_build()` (startup
`_log_build`, `session_create`, `session_list`, title ack). The preserved logs
show the startup call returning and the title-path call blocking; the exact
total number of calls is not logged. The defect is that a **frame emission**
could invoke a subprocess at all.

---

## 4. Hypotheses tested

| Hypothesis | Result |
|---|---|
| Stale Python process / older engine checkout | **Rejected for this path.** Stack path is the repo; build log is `563f5cc2`; `_engine_build` is identical at `563f5cc2` and `6959c862`. |
| Bundled/older engine artifact | No evidence; the bridge imports the repo source path shown in the stack. |
| Slow title-provider request | **Rejected.** Provider settled in 2.484 s; fallback printed immediately after. |
| Repeated subprocess path | **Not the cause of the 558 s block.** Repeated calls exist, but the stack shows one blocked call; the startup call returned. |
| Another blocking operation | **No evidence.** The turn end follows the title emit; the stack and timeline point to `_engine_build`. |

---

## 5. Repair

`src/bridge/__main__.py`:

- `_engine_build()` resolves **once at startup** and caches the value.
- `emit()` uses `_engine_build_cached()`; it never calls `subprocess` or
  `_engine_build`.
- The startup probe runs in a daemon thread with a hard wall-clock cap
  (`_engine_build_timeout_s`, default 2.5 s). If it does not finish, the cached
  value is the explicit string `"unknown"`.
- `_read_git_build()` keeps a 2 s subprocess timeout, `stdin=DEVNULL`,
  `stderr=DEVNULL`, and Windows `CREATE_NO_WINDOW`.
- A dangling probe thread is daemon-only and cannot hold frame emission or
  process exit.

Deterministic tests in `src/tests/test_live12_readiness.py` prove:

- repeated `session_info` frames never spawn a subprocess;
- `emit()` never calls the probe;
- a hung probe returns `"unknown"` in <1 s and is cached;
- unknown metadata is explicit;
- the original frame payload is preserved.

This removes the Live11 blocking path without suppressing the build identifier
or blocking startup forever.
