# Live11 Root Cause — Duplicate Submission and Orphaned Reservation

Status: **provider-free forensic reconstruction**. No provider was called for
this report.

Run: `p0_6_5_20261108T000751_06427b06`

---

## 1. Observed timeline (UTC)

| Time | Event | Evidence |
| --- | --- | --- |
| 08:07:51.537 | Harness starts; one Electron launch (PID 12804) | `evidence.json` |
| 08:08:20.623 | One composer Enter; composer clears (`method=enter`, no send-button click) | `stages.ui_submission` |
| 08:08:26.978 | First turn manifest appears; prompt SHA matches | `stages.turn_manifest` |
| 08:08:28.244 | Source provider call starts | `provider_invocations.jsonl` |
| 08:08:32.379 | Source settles: 513 in / 1155 out, ₹0.023767 | same |
| 08:08:42.777 | Tests provider call starts | same |
| 08:08:49.094 | Tests settle: 692 in / 326 out, ₹0.009156 | same |
| 08:08:52.481 | `TASK_DELIVERED` — `COMPLETED` | first-turn journal |
| 08:08:54.976 | Title call settles: 461 in / 64 out, ₹0.004809; local title fallback | same / console |
| 08:09:27 | Bridge watchdog stack: worker blocked in `_engine_build` | `logs/electron.stderr.log` |
| 08:18:13.263 | First turn `turn.completed` (`completed=true`, 588.625 s) | `runtime_events.db` |
| 08:18:13.438 | **Second session** `session-93a28e6c…` starts with the same prompt | `sessions.db`, journal |
| 08:18:13.550 | Second turn `TASK_INITIALIZED`; plan 2 units | second-turn journal |
| 08:18:13.593 | Reservation `res_d7990e4d3dc3` created (₹0.167204, 11598 tokens) | canonical `sessions.db` |
| ~08:18:13.6 | Reservation becomes `in_flight`; source worker starts | finops JSON |
| 08:18:14.013 | Harness observes first-turn terminal | `stages.turn_terminal` |
| 08:18:14.556 | Electron stopped; second worker killed | `electron_shutdown` |

The first turn genuinely completed. The second turn never reached a terminal
state and was killed by the harness's normal app shutdown.

---

## 2. The 9.5-minute delay: contributing condition, not proven submit cause

After the title call, `_maybe_autotitle_session()` invokes
`self.emit({"type": "session_info", ...})`. `BridgeServer.emit()` enriches every
`session_info` with `_engine_build()`, which runs a subprocess
(`src/bridge/__main__.py:2596` in the Live11 build). That subprocess blocked for
about 9.5 minutes:

```text
_maybe_autotitle_session -> _run -> emit -> _engine_build -> subprocess.run
```

The first turn's terminal frame could not be emitted until that call returned.
It also delayed the harness's terminal observation.

**Proven:** the delay exists, is inside the title/`session_info` path, and held
the first turn open for 586.3 s.

**Not proven:** that the delay *caused* the second submission. The harness
recorded exactly one Enter and no send-button click. The second session began
0.17 s after `turn.completed`, which is consistent with a queued/replayed
renderer submission being released at completion, but the exact renderer event
is not present in the preserved evidence. The repair therefore does not rely on
removing the delay; it enforces idempotency at the session/turn boundary.

**Fix applied separately:** the title/emit path remains governed and accounted,
but a slow title can no longer delay the terminal frame's financial/terminal
truth indefinitely because shutdown and restart reconciliation now resolve
orphaned state. (A future change could move `_engine_build` off the critical
path; that is not part of this narrow repair.)

---

## 3. Exact boundary where the second session was created

Before the repair, `BridgeServer.handle()` resolved a session id with
`_session()` for `session_create` frames. With no `session_id` in the frame,
`_session()` always minted a new id:

```python
sid = normalize_id(requested, prefix="session")
self._sessions[sid] = {"session_id": sid, "workspace": workspace}
```

The `session_create` handler then emitted `session_info`, and the renderer's
`session_info` handler started any `pendingPrompt`. There was **no idempotency
key** anywhere on this path: two `session_create` frames from one logical
submission produced two sessions; the second `prompt` produced a second turn and
a second provider reservation.

This is the boundary the repair protects:
`session_create`/`prompt` dispatch, before `_session()` mints and before the
turn worker starts.

---

## 4. Why the reservation stayed `in_flight`

`_dispatch_code_prompt()` performs:

```text
reserve() -> mark_in_flight() -> llm.invoke() -> usage -> commit/release
```

`mark_in_flight()` persists the state before the wire call. When Electron was
stopped, the worker died with no response, so neither `commit_reservation()` nor
`mark_uncertain()` ran. The next process never loaded that task's FinOps file
because no turn for `turn-9005244…` was resumed.

Result:

```text
res_d7990e4d3dc3  amount=₹0.167204  status=in_flight  spent=₹0
```

No usage receipt existed, so the call could not be settled. It was also never
classified uncertain because the process died before the adapter's exception
path could run.

The repair distinguishes the states explicitly:

| Persisted state | Meaning | Startup action |
| --- | --- | --- |
| `reserved` | dispatch never started (`mark_in_flight` not reached) | release |
| `in_flight` | dispatch may have reached the provider | uncertain, hold retained |
| `reconciled` | authentic usage settled | never settle again |
| `released` | proven no charge | terminal |
| `uncertain` | outcome unknown | retained until reconciled |

See `FINANCIAL_LIFECYCLE.md`.

---

## 5. Historical outcome preserved

Live11's original evidence is untouched:

- settled spend ₹0.037732;
- 3 invocation records, all settled;
- 4 guard claims;
- 1 in-flight reservation ₹0.167204;
- upper-bound exposure ₹0.204936;
- no duplicate settlement, no hidden completed invocation.

The repair changes future behavior, not the historical record. P0.6.9 remains
`P0.6.9_ACCEPTANCE_FAILED`; generation recovery remains unproven live.
