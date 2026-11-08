# LIVE12 Preflight

**Mode: provider-free preflight only.** No live provider call, no Electron
acceptance run, no benchmark, no spend.

---

## 1. Repository

| Item | Value |
| --- | --- |
| Starting HEAD | `128fbc56fdf6dc16d98880c0d883087e30d8c22f` |
| Branch | `feat/prompt-cache-stabilization` |
| origin | `128fbc56fdf6dc16d98880c0d883087e30d8c22f` |
| local == origin | yes |
| Live11 repair commit | `128fbc56 fix(bridge): exactly-once submissions and orphaned reservation recovery` |

The working tree contains many pre-existing unrelated modifications (personal
finance app, root phase reports, etc.). They are **not** part of this preflight
and will not be staged. No reset, clean, stash or overwrite was performed.

---

## 2. Evidence integrity

| Manifest | Result |
| --- | --- |
| `diagnostics/p0_6_9/SHA256SUMS.txt` | **41/41 verified** |
| `diagnostics/generation_boundary/live_acceptance/live11_20261108/SHA256SUMS.txt` | **48/48 verified** |
| `diagnostics/live11_repair/SHA256SUMS.txt` | **19/19 verified** |

Historical Live9, Live10 and Live11 evidence are unchanged. Historical reports
and the failed P0.6.9 verdict are unchanged.

---

## 3. Electron environment

| Check | Result |
| --- | --- |
| `desktop/vscode/.build/electron/CrusorAI.exe` | present, 221,944,832 bytes |
| Product name | CrusorAI IDE |
| `out/.../crusorAIRendererService.js` contains the submission fix | yes (5 matching lines) |
| `node --check` on the generated renderer service | exit 0 |
| `npm run compile` (gulp → tsc) | **fails** on pre-existing missing `electron` / `DebugProtocol` / `TrustedHTML` type packages |
| Targeted `tsc6 -p src/tsconfig.crusorai-check.json` | exits 2 on upstream types; **no errors in `contrib/crusorai` files** |

The runtime artifact is present and the changed renderer JS parses. A clean
desktop rebuild cannot be verified in this environment because the installed
type packages are incomplete. This is a pre-existing environment limitation,
not a source error in the changed files.

---

## 4. Required controls

| Control | Status |
| --- | --- |
| Stable submission id | implemented |
| Duplicate IPC / session / prompt idempotency | implemented and tested |
| Completed-submission replay refused | implemented and tested |
| Durable submission state across restart | implemented and tested |
| Orphan `reserved` release | implemented and tested |
| Orphan `in_flight` → uncertain, hold retained | implemented and tested |
| Idempotent reconciliation | implemented and tested |
| Hard pre-dispatch budget refusal | verified offline (`budget_preflight.json`) |
| Auxiliary gateway reserves before client construction | verified offline |
| No current-process orphan reconciliation | implemented and tested |

---

## 5. Budget summary

See `BUDGET_REQUIREMENTS.md`.

| Quantity | Value |
| --- | --- |
| Live11 observed settled total | ₹0.037732 |
| Maximum per 8192-output call (measured pricing) | ₹0.153887 |
| 5-dispatch task ceiling | ₹0.769435 |
| Auxiliary max (64 output, measured) | ₹0.005179 |
| Conservative task + aux ceiling | **₹1.20** (₹1.00 task + ₹0.20 aux) |
| Hard pre-dispatch ceiling | **yes** |

---

## 6. Known blockers to READY

1. **Title path can block terminal.** In acceptance mode
   `_maybe_autotitle_session(wait=True)` runs before `turn_done`; its
   `emit(session_info)` calls `_engine_build()`, which can block for minutes
   (9.5 min in Live11). It cannot create a session/turn, but it can delay the
   terminal event and trigger renderer watchdogs. A LIVE12 run must either set
   `CRUSORAI_AUTOTITLE=off` or the `_engine_build` path must be bounded/cached.
   See `AUXILIARY_TITLE_AUDIT.md`.
2. **Clean desktop rebuild not verified.** Missing type packages in the
   environment; only the existing built artifact is verified.
3. **One pre-existing battery failure remains.**
   `test_bridge_transport.py::test_turn_done_survives_a_undrained_event_queue`
   fails in this checkout; the baseline bridge file reproduces the failure
   (`baseline_bridge_failure.log`). It is not caused by the Live11 repair, but
   it remains red.

---

## 7. Verdict

```text
LIVE12_NOT_READY
```

The Live11 exactly-once and financial-lifecycle controls themselves are ready
and tested. The blockers above are pre-existing environment/test issues and one
documented title-path risk. They must be explicitly accepted or resolved before
LIVE12 execution.
