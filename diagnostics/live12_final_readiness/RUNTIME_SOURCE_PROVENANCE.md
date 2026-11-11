# Runtime Source Provenance

## 1. Live11 engine source

| Item | Evidence |
|---|---|
| Engine commit | `563f5cc2` |
| Engine build log | `[bridge] engine build: 563f5cc2 2026-11-07 23:56:02 -0800` |
| Engine root | `C:/Users/Administrator/Downloads/CRUSORAI/PulseAIRepo` |
| Bridge source path | `...\PulseAIRepo\src\bridge\__main__.py` |
| Python | uv CPython 3.14.4 via repo `.venv` |
| Bridge PID | 4356 |

`src/bridge/__main__.py` at `563f5cc2` and `6959c862` is byte-identical
(SHA-256 `0857f33cb8033f955c5e6a1b53c863d115ad1b79883191183a5ff6fa055a9632`).
The `_engine_build()` implementation, including `timeout=3`, is identical.

No evidence supports a stale process, a bundled older engine, or a different
checkout for this path. The stack, build log and source all name the repo.

## 2. Current runtime source

The current working tree includes:

- Live11 exactly-once and financial repairs (`128fbc56`);
- preflight diagnostics (`f1299525`);
- this task's build-probe cache and tests (uncommitted until qualification).

The current `_engine_build()` no longer runs in `emit()`, and the probe is
bounded/cached. The bridge source SHA changes when this task is committed; the
build manifest records the exact final SHA.

## 3. Distinction from the desktop bundle

The Python engine is the repo source. The desktop panel is the compiled
`desktop/vscode/out` contribution bundle plus the pinned Electron runtime
(`desktop/vscode/.build/electron/CrusorAI.exe`).

Live11's blocking path was **engine runtime**, not the desktop bundle: the stack
is in `src/bridge/__main__.py`, and the emitted `session_info` frame was waiting
on `_engine_build()`. The desktop bundle's source hash is audited separately in
`ARTIFACT_PROVENANCE.md`.
