# LIVE12 Preflight (read-only)

Date: 2026-11-08. Preparation only: no Electron acceptance session, no task
submission, no provider reservation, no spend.

## 1. Repository state

| Item | Value |
|---|---|
| Repository | `SriAkhilSJ/PulseAIRepo` |
| Branch | `feat/prompt-cache-stabilization` |
| HEAD | `a010c5dfef8fa9fe3535c31418ef8e60bb8ff822` |
| origin HEAD | `a010c5dfef8fa9fe3535c31418ef8e60bb8ff822` |
| local == origin | yes |
| Runtime source-repair commit | `7d4a4cc587bde12d7fc89d5c0714d2ef4ac406ee` (ancestor) |
| Previous readiness baseline | `f12995255ad72204de5e1172054d1f62508287a9` (ancestor) |
| Runtime source changed after `7d4a4cc5` | no (`git diff 7d4a4cc5..HEAD -- src` empty) |
| `docs/P2-roadmap.md` unchanged | yes |

The working tree contains unrelated pre-existing user changes under
`apps/personal_finance/`, `src/tools/`, `src/req_*.py`, `src/workspace/` and
untracked tests. They are preserved and not staged by this task.

## 2. Prompt

| Item | Value |
|---|---|
| Actual prompt | `diagnostics/generation_boundary/live_acceptance/live11_20261108/prompt.txt` |
| Size | 876 bytes |
| SHA-256 | `a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8` |
| Expected SHA | exact match |
| Path named in authorization | `diagnostics/live11_20261108/prompt.txt` — **does not exist**; the verified file above is used and not modified |

## 3. Artifacts

| Artifact | Value |
|---|---|
| `SOURCES_HASH` computed == shipped | yes, `465a6bb15486775bb643684173b2dbb626d6e936c3e1797488c77d25a0c476a5` |
| Source manifest | 50/50 files, 0 missing, 0 unexpected, 0 mismatched |
| Renderer | `e3bf434b969a8e62279042d693708151dbe19941b973a66cc94a8920ac910394` |
| Worker | `05f842f4743c7a16df28751c20415b039f585100cad809798ee31a4eebd54683` |
| `CrusorAI.exe` | `49486b2ef4d940bdbf9985811a8ed2c808551d6e1353d1b3cf3a4c5b8c4fd6d4`, 221,944,832 bytes |
| `BUILD_INFO.json` | source commit `7d4a4cc5`, built 2026-11-08T15:15:00Z |
| `BUILD_MANIFEST.json` source commit | `7d4a4cc5`, ancestor of HEAD |

The final readiness HEAD is documentation/evidence after the desktop source
commit; the build's source commit is not required to equal HEAD.

## 4. Historical evidence and reservation

| Manifest | Result |
|---|---|
| `diagnostics/p0_6_9/SHA256SUMS.txt` | 41/41 |
| Live11 run `SHA256SUMS.txt` | 48/48 |
| `diagnostics/live11_repair/SHA256SUMS.txt` | 16/19 — three intentional source/artifact deltas documented in `HISTORICAL_MANIFEST_DELTAS.md` |
| `diagnostics/live12_acceptance/SHA256SUMS.txt` | 14/14 |
| `diagnostics/live12_final_readiness/SHA256SUMS.txt` | all entries verify |

Historical reservation `res_d7990e4d3dc3` is unchanged: `in_flight`,
₹0.167204, no usage/invocation/settlement. It is not released, settled or
included in any new run.

## 5. Environment chain (offline verification)

- `CRUSORAI_AUTOTITLE=off` is exported before launch.
- `launch_app` inherits `os.environ`; the harness does not add or override the key.
- The worker spawn spreads `process.env` into the Python child.
- `src/config/settings.py` loads dotenv with `override=False`.
- `BridgeServer._auxiliary_llm_allowed()` returns false before any store or
  provider access.
- Harness and bridge use the same off-values (`0/off/false/no`), pinned by test.

Hard budget controls were exercised offline in an isolated workspace:

- a ₹1.01 task reservation is refused at a ₹1.00 ceiling;
- an auxiliary gateway at a ₹0.00 ceiling refuses before client construction.

## 6. Blockers found and resolved offline

1. **Harness contradiction (resolved).** The harness required a settled
   `session_titling` record and a non-empty session title, which autotitle-off
   makes impossible, so a perfect run would have returned
   `P0.6.9_ACCEPTANCE_FAILED`. The harness now classifies titling-off runs with
   a stricter gate: zero `session_titling` records, empty title allowed, and the
   90 s auxiliary wait short-circuited. See `AUTOTITLE_OFF_VERIFICATION.md`.
2. **Verdict naming (resolved in procedure).** The harness keeps its historical
   `P0.6.9_*` strings; the acceptance report maps them to `LIVE12_*`. Mapping is
   documented in `LIVE12_ACCEPTANCE_PROCEDURE.md` §6.
3. **Prompt path (resolved).** The authorization's prompt path is absent; the
   verified `generation_boundary/...` file is used.
4. **Missing preflight file (resolved).** This file.

## 7. Process state

No `CrusorAI.exe`, Electron or acceptance process is running.

## 8. Remaining blockers

- **Launch smoke test not yet re-run.** The first authorized attempt crashed in
  Electron's main process because `@vscode/policy-watcher` had no native binding
  after `npm ci --ignore-scripts`. Eight native modules were restored offline
  from the local VS Code install; `vsda` remains unresolved and is not on the
  early startup path. The repaired launch has not been exercised.
- A new explicit authorization is required for another Electron session.

Execution still requires a separate written
`AUTHORIZE LIVE12 — ₹1.00`.

```text
LIVE12_INCONCLUSIVE_LAUNCH_REPAIRED_RETEST_REQUIRED
```
