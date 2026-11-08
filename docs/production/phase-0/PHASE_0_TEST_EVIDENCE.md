# Phase 0 — Test Evidence

**Rule:** Phase 0 did not execute application code. Everything below is either
(a) prior evidence already committed to the repository, or (b) a classification
of what that evidence actually proves.

---

## 1. Evidence executed before Phase 0 (not by this audit)

| Activity | Result | Source |
|---|---|---|
| Full desktop TypeScript compile | exit 0, 13 min, 731 resources | `diagnostics/live12_final_readiness/desktop_compile.log` |
| Contribution bundle emission | 42 files, 8 media, DI check ok | `diagnostics/live12_final_readiness/desktop_emit_bundle.log` |
| Provider-free battery | **366 collected, 366 passed in 678.32 s** | `diagnostics/live12_final_readiness/reliability_battery.log` |
| Artifact provenance | 50/50 sources, renderer/worker/exe hashes | `BUILD_MANIFEST.json`, `ARTIFACT_PROVENANCE.md` |
| Live11 run | 48/48 evidence files; duplicate submission + uncertain reservation | `diagnostics/generation_boundary/live_acceptance/live11_20261108/` |
| P0.6.9 verdict | **`P0.6.9_ACCEPTANCE_FAILED`** | `diagnostics/p0_6_9/ACCEPTANCE_MATRIX.md` |
| First LIVE12 launch | **`P0.6.6_LIVE_FAILED`** before any session | `diagnostics/live12_run_20261108_085953/` |
| LIVE12 retest | **not performed** | — |

### Important caveat

The 366-test battery imports `src.context.context_engine` and
`src.context.vector_memory`. The prior logs show **314** `_trigger_repairs`
invocations and successful `SetSecurityInfo` calls during those runs. The
battery is **provider-free but not environment-side-effect-free**. See
`PHASE_0_SECURITY_FINDINGS.md`.

---

## 2. Intentionally not run in Phase 0

```text
python -c "import src..."
pytest (any selection)
python scripts/agent_core_checkup.py
CrusorAI.exe / Electron / CDP harness
npm install / npm ci / npm run compile
provider calls or reservations
database writes or migrations
ACL / permission changes
```

No test command was executed by this audit. The findings above come from
committed evidence and plain-text inspection.

---

## 3. Evidence classification by audit area

| Area | Classification | What is actually proven |
|---|---|---|
| Repository baseline | **PROVEN** | HEAD `27b17f10`, branch and origin match |
| Production source unchanged by Phase 0 | **PROVEN** | No `src/`, `desktop/out`, or executable writes |
| Desktop compile | **PROVEN** | Prior `npm run compile` log, exit 0 |
| Desktop launch | **FAILED / PARTIALLY PROVEN** | First launch failed before workbench; native repair not retested |
| Electron/native bindings | **PROVEN** (filesystem) | 70 `.node` files present; `vsda` missing |
| Protocol v2 | **PROVEN** (code + offline tests) | Schema/generator and frame union exist |
| Exactly-once (code) | **PROVEN** (offline) | Ledger states, atomic claim, replay rejection, 25 tests |
| Exactly-once (live) | **UNPROVEN** | No completed live submission |
| Financial lifecycle (code) | **PROVEN** (offline) | Reserve/in-flight/uncertain/release, reconciliation |
| Financial lifecycle (live) | **UNPROVEN** | Live11 left an uncertain hold; no completed LIVE12 |
| Context engine | **PARTIALLY PROVEN** | Code and offline tests; security side effects proven; long-turn token cost documented |
| Completion/verification | **PARTIALLY PROVEN** | Code exists; P0.6.9 failed; harness is task-specific |
| UI streaming | **PARTIALLY PROVEN** | Frame handling exists; Live11 showed plan/Thinking |
| Visual tool cards | **UNPROVEN** | No mid-turn tool card captured in Live11; sampler not run |
| 24-hour performance | **UNKNOWN** | No soak run |
| Import-time security | **P0 FAILED** | Proven ACL modification via repair script |

---

## 4. CI surface

| Workflow | Runs | Notes |
|---|---|---|
| `.github/workflows/agent-core-checkup.yml` | `ubuntu-latest`, on `src/**` | Imports every module; on Windows it would execute the import-time payloads |
| `.github/workflows/e2e-core.yml` | e2e | inspect before enabling on Windows |
| `.github/workflows/long-session.yml` | `ubuntu-latest`, manual/push | Live provider session, USD cap; not a 24 h soak |
| `.github/workflows/diagnosability.yml` | diagnostics | |
| `.github/workflows/host-compatibility.yml` | host matrix | |
| `.github/workflows/verify-provider-key.yml` | key check | |

The checkup workflow is not a security gate: it does not assert that imports are
side-effect-free, and it does not run on Windows.

---

## 5. Coverage gaps that caused the current state

1. **No import-purity test.** The suite happily imports modules that spawn
   PowerShell and change ACLs.
2. **No launch smoke in the readiness matrix.** Compile + hashes passed while
   the app could not start.
3. **Task-specific acceptance.** The harness verifies only `duration.py`.
4. **No generic task profile** for ProjectFlow-style work.
5. **No 24 h soak** with token/cost/compaction evidence.
6. **No visual contract test** proving tool cards render.
7. **Full-suite scope.** The 366-test slice is not the whole engine suite; the
   historical full run had failures (see `AGENT_CORE_FULL_AUDIT_2026-11-01.md`).

---

## 6. Required regression tests (to be added in a fix phase)

| Test | Purpose |
|---|---|
| Import purity: `src.context.*` with subprocess/win32 patched to raise | Catch P0-SEC-01/02/03 |
| Static guard: no `WD`/`GA` SDDL, `SetSecurityInfo`, `runner.exe`, `repair_winsta`, `-ExecutionPolicy Bypass` in runtime code | Prevent regression |
| Windows launch smoke: build → launch → workbench ready | Close the launch gap |
| Generic acceptance profile: arbitrary task + artifact verification | Remove duration hardcoding |
| Bridge start process-tree: no `powershell.exe`, no repair child | Prove no hidden subprocess |
| Tool-card visual test: mid-turn DOM `tool_rows > 0` + screenshot | Prove visible rendering |
| Money reconciliation invariant: guard claims == invocations == settlements | Prove accounting |
| 24 h soak: bounded token/cost, no duplicate submission | Prove stamina |

---

## 7. Verification commands intentionally not run

```powershell
# not run in Phase 0
.\.venv\Scripts\python.exe -m pytest ...
.\.venv\Scripts\python.exe -c "import src.context..."
.\.venv\Scripts\python.exe scripts\agent_core_checkup.py
.\.venv\Scripts\python.exe -m benchmarks.crusor_desktop_acceptance --live-turn ...
npm run compile
```

```text
TEST_VERDICT: PRIOR_EVIDENCE_ONLY
PHASE_0_EXECUTIONS: 0
```
