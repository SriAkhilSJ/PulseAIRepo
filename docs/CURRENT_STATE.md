# CrusorAI - Current State

**Snapshot date:** 2026-11-09 (local; CI evidence 2026-11-09 UTC)
**Branch:** `feat/prompt-cache-stabilization`
**HEAD:** `638d4151efa5ba3ed0ea6f1ec7e7503663539990`
**Origin:** identical to HEAD at snapshot time
**Current phase:** Phase 2 desktop qualification r2 complete (`DESKTOP_PARTIAL`); desktop remediation committed; Agent Core graph blocked by a pre-existing import defect

> Canonical state is the committed HEAD. The working tree contains 175
> pre-existing entries that are not part of any commit; see section 5. Never
> treat those files as shipped behaviour.

---

## 1. Status summary

| Dimension | Status | Evidence |
|---|---|---|
| Production hardening Phase 0 | Complete | `a6455e25`, `docs/production/phase-0/` |
| Phase 1 source containment | Complete | `b95b1750`, `7a714e24` |
| Phase 1.1 guard hardening | Complete | `bb94f740`, `2204e320` |
| Phase 1.2 filesystem guard | Complete | `c32582db`, `38f06d8f` |
| Phase 1.3 CWD/mutation/allowlist | Complete | `c9b909d2`, `3c954480` |
| Phase 1.3.1 AST allowlist hardening | Complete and CI-green | `4a9e2ade` ... `b72d04c5`; run `42560871135` |
| Phase 1.3.2 AST binding/alias hardening | Complete and CI-green | `6c55f350`, `385925bf`; run `42563557065` |
| Phase 1.3.3 class/module structure hardening | Complete and CI-green | `1264d990`, `ba8c0c8b`; run `42571837431` |
| Phase 1.3.4 module declaration integrity | Complete and CI-green | `ac52ad26`, `00eabb3d`; run `42574847574` |
| Phase 1.3.4R helper ownership/body integrity | Complete and CI-green | `3cc3c374`, `85192f87`; run `42583627343` |
| Phase 1.3.4R2 async grant declaration count | Complete and CI-green | `90a2d2d1`, `831e6085`; run `42611296402` |
| Phase 1.4 Windows runtime qualification | **COMPLETE / QUALIFIED** | `0bf14d9c`, `71479fb6`; runs `42654054565`, `42654054623`; see `PHASE_1_4_WINDOWS_RUNTIME_QUALIFICATION.md` |
| Phase 1.4 fail-closed correction | **COMPLETE / QUALIFIED** | `5a51897c`, `e9b6ee02`; runs `42661726444`, `42661726660` |
| Phase 2 r1 desktop qualification | `DESKTOP_PARTIAL` | `165dc16f`; evidence `bench-results/phase-2-desktop-qualification-r1` |
| Phase 2 r2 desktop remediation | `DESKTOP_PARTIAL` | `73c4d0a7`, `638d4151`; evidence `bench-results/phase-2-desktop-qualification-r2` |
| Desktop GUI live acceptance | Not verified on this host | Headless limitation recorded in Phase 12.1.3 |
| Live model acceptance (P0.6.9/LIVE12) | Failed / not revalidated | Historical evidence only; see `docs/BUGS_AND_LIMITATIONS.md` |

## 1b. Phase 2 desktop qualification (latest)

**r2 remediation (commits `73c4d0a7`, `638d4151`) — `DESKTOP_PARTIAL`.**

- Focused renderer suite green: 194 passed, 7 skipped, 1 xfailed. The three
  brittle string pins were replaced with semantic assertions (prompt + context
  chips, typed prompt payload, subagent routing); the fourth finding (four raw
  font sizes) was fixed with existing type tokens plus a selector regression.
- Approval dock now fits the default 299 px auxiliary bar (0 px overflow,
  question 257 px, `Allow once` fully visible); measured in a live Electron run.
- Startup cancellation race fixed: single pending slot in
  `src/runtime/turn_control.py`, `mark_pending` before dispatch, consumed by
  `begin()`, early cancelled terminal before any model/echo work; 7 unit tests
  and a runtime probe prove `accepted=True pending=True` with no completion.
- Cancelled-before-execution turns no longer paint the yellow evidence warning:
  trace/report are recorded as `not_applicable`, receipt `persisted`
  (`src/runtime/evidence_capture.py` + regression test).
- Blocked: real approval execution and durable cold transcript replay. The
  Agent Core graph fails at HEAD with `ImportError:
  compact_assistant_tool_call_arguments` from `src.context.compaction`
  (`history_shaper.py:159-165` imports two names that do not exist anywhere).
- New visual defect: the Crusor pane ignores the built-in light theme (pane
  stays black on a light workbench).
- `Ctrl/Cmd+L` remains NOT PROVEN: OS input injection did not reach the app in
  this session (control chord also ignored); the command-palette command works.
- Worker restart and warm replay remain PASS; cold replay restore of messages
  is NOT EXERCISED.

Evidence: `bench-results/phase-2-desktop-qualification-r2/`.

## 3. What was just completed (Phase 1.3.4R)

Commit chain:

| Commit | Purpose |
|---|---|
| `3cc3c374` | Pin the exact 11-statement helper body and require `_grant_to_object` to be its single direct nested function; +11 tests. |
| `85192f87` | Record Phase 1.3.4R CI evidence in the Phase 1.3.4 document. |

Verified results:

| Check | Result | Exit |
|---|---|---|
| Full `test_security_containment.py` | 231 passed, 3 skipped in 90.28 s (234 collected) | 0 |
| Full guarded import | 1 passed in 31.32 s | 0 |
| Standalone agent-core checkup | 57 pass, 5 warn, 0 fail | 0 |
| Agent-core checkup tests | 19 passed in 204.89 s | 0 |
| CI-parity clean 3.14 venv | 231 passed, 3 skipped in 64.67 s | 0 |

CI evidence, `Security guard` run `42583627343` on `3cc3c374`:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129048047073` | 230 passed, 4 skipped |
| Security containment (windows-latest) | Windows | `129048047146` | 228 passed, 6 skipped |
| Security containment (macos-latest) | macOS | `129048046882` | 230 passed, 4 skipped |

The suite grew from 223 to 234 tests (+11). No product source changed. Full
details: `docs/production/phase-1/PHASE_1_3_4_MODULE_DECLARATION_HARDENING.md`
section 13.

### 2.1 Phase 1.3.4 (previous)

Commit chain:

| Commit | Purpose |
|---|---|
| `ac52ad26` | Pin the exact import manifest, 62-entry module declaration manifest, helper signature, 13 manager method declarations, and full eleven-structure completeness; +31 tests. |
| `00eabb3d` | Record Phase 1.3.4 CI evidence. |

Verified results:

| Check | Result | Exit |
|---|---|---|
| Full `test_security_containment.py` | 220 passed, 3 skipped in 23.47 s (223 collected) | 0 |
| Full guarded import | 1 passed in 8.84 s | 0 |
| Standalone agent-core checkup | 57 pass, 5 warn, 0 fail | 0 |
| Agent-core checkup tests | 19 passed in 66.72 s | 0 |
| CI-parity clean 3.14 venv | 220 passed, 3 skipped in 15.99 s | 0 |

CI evidence, `Security guard` run `42574847574` on `ac52ad26`:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129020138381` | 219 passed, 4 skipped |
| Security containment (windows-latest) | Windows | `129020138103` | 217 passed, 6 skipped |
| Security containment (macos-latest) | macOS | `129020138297` | 219 passed, 4 skipped |

The suite grew from 192 to 223 tests (+31). No product source changed. Full
details: `docs/production/phase-1/PHASE_1_3_4_MODULE_DECLARATION_HARDENING.md`.

### 2.2 Phase 1.3.3 (previous)

Commit chain:

| Commit | Purpose |
|---|---|
| `1264d990` | Validate every `ctypes.Structure` layout and module class body; exact DLL initialization; reject aliases and executable module assignments. |
| `ba8c0c8b` | Record Phase 1.3.3 CI evidence. |

Verified results:

| Check | Result | Exit |
|---|---|---|
| Full `test_security_containment.py` | 189 passed, 3 skipped in 20.37 s (192 collected) | 0 |
| Full guarded import | 1 passed in 9.39 s | 0 |
| Standalone agent-core checkup | 57 pass, 5 warn, 0 fail | 0 |
| Agent-core checkup tests | 19 passed in 62.67 s | 0 |
| CI-parity clean 3.14 venv | 189 passed, 3 skipped in 12.07 s | 0 |

CI evidence, `Security guard` run `42571837431` on `1264d990`:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129010742092` | 188 passed, 4 skipped |
| Security containment (windows-latest) | Windows | `129010742187` | 186 passed, 6 skipped |
| Security containment (macos-latest) | macOS | `129010741861` | 188 passed, 4 skipped |

The suite grew from 161 to 192 tests (+31). No product source changed. Full
details: `docs/production/phase-1/PHASE_1_3_3_MODULE_STRUCTURE.md`.

### 2.3 Phase 1.3.2 (previous)

Commit chain:

| Commit | Purpose |
|---|---|
| `6c55f350` | Replace permissive traversal with an exact 18-statement structural whitelist; reject protected aliases, rebinding, destructuring, walrus, loop/with targets, import/nested shadowing, module/attribute monkeypatching; validate all eight `GetSecurityInfo` arguments, both `LocalFree` calls, order, branches and return. |
| `385925bf` | Record Phase 1.3.2 CI evidence. |

Verified results:

| Check | Result | Exit |
|---|---|---|
| Full `test_security_containment.py` | 158 passed, 3 skipped in 48.01 s (161 collected) | 0 |
| Full guarded import | 1 passed in 22.15 s | 0 |
| Standalone agent-core checkup | 57 pass, 5 warn, 0 fail | 0 |
| Agent-core checkup tests | 19 passed in 77.56 s | 0 |
| CI-parity clean 3.14 venv | 158 passed, 3 skipped in 12.62 s | 0 |

CI evidence, `Security guard` run `42563557065` on `6c55f350`:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `128985028576` | 157 passed, 4 skipped |
| Security containment (windows-latest) | Windows | `128985028853` | 155 passed, 6 skipped |
| Security containment (macos-latest) | macOS | `128985028790` | 157 passed, 4 skipped |

The suite grew from 93 to 161 tests (+68 adversarial cases). No product source
changed. Full details: `docs/production/phase-1/PHASE_1_3_2_AST_BINDING_HARDENING.md`.

### 2.4 Phase 1.3.1 (previous)

Commit chain:

| Commit | Purpose |
|---|---|
| `4a9e2ade` | Strict AST allowlist: exact targets, values, receivers, arguments, allocation/free order. |
| `3450c790` | CI portability: skip Windows-only `ctypes.WinDLL` test on POSIX; run guard CI on Python 3.14. |
| `de4f8c0d` | Exact call set inside `_grant_to_object`; reject extra, aliased, helper, and dynamic calls. |
| `b974a5a1`, `b72d04c5` | Evidence and final Phase 1.3.1 documentation. |

Verified results:

| Check | Result | Exit |
|---|---|---|
| AST validation | OK | 0 |
| Static subset | 32 passed | 0 |
| Annotated + augmented subset | 2 passed | 0 |
| `setattr` + nested subset | 7 passed | 0 |
| Receiver subset | 3 passed | 0 |
| Ordering/allocation subset | 7 passed | 0 |
| Full `test_security_containment.py` | 90 passed, 3 skipped (38.38 s) | 0 |
| Full guarded import | 1 passed (22.92 s) | 0 |
| Standalone agent-core checkup | 57 pass, 5 warn, 0 fail | 0 |
| Agent-core checkup tests | 19 passed (153.93 s) | 0 |
| CI-parity clean 3.14 venv | 90 passed, 3 skipped (21.55 s) | 0 |

CI evidence, `Security guard` run `42560871135` on `de4f8c0d`:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `128976770082` | 89 passed, 4 skipped |
| Security containment (windows-latest) | Windows | `128976769886` | 87 passed, 6 skipped |
| Security containment (macos-latest) | macOS | `128976770003` | 89 passed, 4 skipped |

The final HEAD is a docs-only commit after the tested code commit; no product
or test code differs between `de4f8c0d` and `b72d04c5`.

## 3. What is implemented (high confidence)

Verified by source inspection in this audit:

- Code OSS fork at pinned upstream `6c27443ce6fdf6ac798c64025d45175e2e23c4b4`,
  product version 1.134.0, Electron 42.8.1.
- Crusor workbench contribution with renderer, session controller, preview,
  manager, skills hub, account, inline completion, and next-edit surfaces.
- Protocol v2 NDJSON bridge with 33 client methods and a typed event set
  (`src/bridge/protocol.py`).
- LangGraph state graph with task manager, planner, AI, tools, progress,
  recovery/tool-cycle limits, pivot, plan preview/reviser/cancel, finish gate,
  and finalize nodes (`src/graphs/chat_graph.py`).
- Tool waist by runtime capability (`src/tools/toolsets.py`): workspace read/
  write, execution, verification, targets/devices, research, media, skills,
  MCP, delegation.
- Context engine facade plus 18 named layers and compaction/budget modules
  (`src/context/context_engine.py`, `src/context/engine.py`).
- Provider factory with `groq`, `openai`, `gemini`, `nvidia`, `custom`, and
  `cheap` routes; auxiliary management calls default to the cheap tier
  (`src/llm/factory.py`, `src/config/settings.py`).
- Orchestrator routing in the bridge with
  `CRUSORAI_ORCHESTRATOR_ENGINE` defaulting to `orchestrator`
  (`src/bridge/__main__.py`).
- Execution broker and per-OS sandbox backends, including Windows
  AppContainer/Job Object support (`src/security/`).
- SQLite persistence in `~/.crusorai/sessions.db`, workspace
  `.crusorai/` ledgers, event journals, and JSONL financial records.
- 334 test modules under `src/tests/`, plus `tests/e2e/` and CI workflows.

## 4. What is incomplete or unverified

| Item | Status | Notes |
|---|---|---|
| Phase 2 | Not started | Do not start without an explicit new task. |
| Independent review of Phase 1.3.1 | Pending | Required by the phase instructions. |
| Full test suite on current HEAD | Not re-run in this documentation audit | Historical baselines only; see section 6. |
| Live provider acceptance | Not revalidated | P0.6.9 evidence recorded a failure; LIVE12 remains unrun/uncertain. |
| Desktop GUI acceptance | Not verified | Headless display constraint recorded in Phase 12.1.3. |
| Identity/RBAC enforcement in agent tool path | Not wired | `IdentityAwareToolAuthorizer` exists but is referenced only by identity code and tests. |
| Protocol events for intelligence artifacts | Missing | Architecture/impact/regression/verification reports have no server frames. |
| Machine-level WindowStation/Desktop ACL recovery | Unresolved | Carried forward from earlier security phases. |

## 5. Working tree (important)

Baseline before this documentation task: **175 entries**:

- **34 modified tracked files**, notably:
  - `src/tools/file_tools.py`, `src/tools/terminal_tools.py`,
    `src/workspace/mutation_broker.py`,
  - `src/req_001_module.py`, `src/req_002_module.py`,
  - 21 `apps/personal_finance/**` files,
  - 4 desktop lockfiles, 3 diagnostics reports, `scripts/transpile_crusorai.mjs`.
- **141 untracked files/directories**, mostly diagnostics, benches, generated
  artifacts, and response modules.

Critical nuance:

- At **HEAD**, `src/tools/file_tools.py` does not contain the
  `WorkspaceMutationBroker` wiring. The on-disk working copy does. Therefore the
  working tree contains an **uncommitted** mitigation for the file-mutation
  bypass. Do not document it as shipped and do not commit it without the owner's
  decision.
- This documentation task added 10 new untracked documentation files. They are
  intentionally not committed and are not part of the 175.

## 6. Test status

| Source | Scope | Result | Status |
|---|---|---|---|
| Phase 1.3.1 local + CI | Security suite | 90/90 executed tests pass, 3 Windows skips | Verified 2026-11-08/09 |
| Phase 1.4 final | Windows security | 232/3 on Python 3.11 and 3.14; 27/27 runtime tests on both; Windows runtime CI 27/27 each; three-platform security CI green | QUALIFIED |
| Agent-core checkup | 14 pipelines | 57 pass, 5 warn, 0 fail | Verified 2026-11-09 |
| Checkup regression suite | `src/tests/test_agent_core_checkup.py` | 19 passed | Verified 2026-11-08 |
| Phase 12.1.3 record | 395-test regression subset | 395/395 | Documented, not re-run |
| README (2026-10-27) | Full suite on `main` | 2,802 passed, 25 failed, 26 skipped, 1 xfailed | Historical; same 25 identities as baseline |

The 25 historical failures are not proven fixed. Do not claim a clean full
suite until a fresh full run is recorded in this file with a commit and exit
code.

## 7. Known warnings observed in the last checkup

The standalone checkup exits 0 but reports five warnings:

1. Five guarded imports reference packages absent from this environment
   (`hermes_state`, `agent.errors`); they fall back safely.
2. The checkup ran with an API key present, so keyless operation was not proven.
3. Tool results are bounded at 12,000 chars, but a 30-call turn can still spend
   roughly 90,000 tokens before reasoning.
4. The cost budget leg is off by default.
5. Compaction does not consult the prompt-cache plan, so a compaction can
   invalidate the cached prefix.

These are design observations, not regressions.

## 8. Canonical next action

1. Independent review of the Phase 1.4 fail-closed correction (`5a51897c`
   implementation, `e9b6ee02` docs).
2. Begin the next major block: desktop production qualification.
3. Decide whether to commit or discard the uncommitted mutation-broker wiring.
4. Commit or explicitly retain the local memory layer.

See `docs/handoffs/LATEST_HANDOFF.md` for commands and constraints.

## 9. Phase 1.3.4R2 async grant correction

Commit chain:

| Commit | Purpose |
|---|---|
| `90a2d2d1` | Count both `ast.FunctionDef` and `ast.AsyncFunctionDef` in the `_grant_to_object` uniqueness search; require the sole declaration to be synchronous and a direct child of the validated helper. |
| `831e6085` | Record the async-counting CI evidence in the Phase 1.3.4 document. |

Verified results:

| Check | Result | Exit |
|---|---|---|
| Full security suite | 232 passed, 3 skipped in 43.72 s (235 collected) | 0 |
| Full guarded import | 1 passed in 14.68 s | 0 |
| Standalone agent-core checkup | 57 pass, 5 warn, 0 fail | 0 |
| Agent-core checkup tests | 19 passed in 109.46 s | 0 |
| CI-parity clean 3.14 venv | 232 passed, 3 skipped in 31.21 s | 0 |

CI evidence, `Security guard` run `42611296402` on `90a2d2d1`:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129140099931` | 231 passed, 4 skipped |
| Security containment (windows-latest) | Windows | `129140099362` | 229 passed, 6 skipped |
| Security containment (macos-latest) | macOS | `129140099833` | 231 passed, 4 skipped |

The suite grew from 234 to 235 tests (+1). No product source changed. Full
details: `docs/production/phase-1/PHASE_1_3_4_MODULE_DECLARATION_HARDENING.md`
section 14.

## 10. Phase 1.4 Windows runtime qualification (PARTIAL)

Commit chain:

| Commit | Purpose |
|---|---|
| `838857ee` | Fix the fallback 1 MB output cap for oversized single lines; add the Windows-only runtime harness and Phase 1.4 evidence. |
| `7e0b83ff` | Record Phase 1.4 CI evidence. |

Verified runtime evidence:

- Default `WinSta0`/`Default` ACLs inspected read-only: Everyone and Interactive
  Users have full access; ALL APPLICATION PACKAGES is absent.
- No machine-level ACL modification was performed. Disposable WindowStation
  creation was blocked (WinError 5, no `SeTcbPrivilege`).
- AppContainer launch with the ACL helper skipped: genuine AppContainer token,
  Low integrity `S-1-16-4096`, Administrators deny-only, Job membership, and
  timeout termination.
- Disposable DACL deny blocked AppContainer read and write.
- Job Object limits: active process limit 1 denied a grandchild; 64 MB memory
  limit denied a 128 MB allocation; termination and cleanup passed.
- Output cap defect fixed: a 2 MB single line is now capped at 1,048,576 bytes.
- Python 3.14 security suite: 232 passed, 3 skipped. Python 3.11 subset:
  231 passed, 3 skipped; full guarded import fails on the known
  `platform.system()` spawn.

CI evidence, `Security guard` run `42618095589` on `838857ee`:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129162931614` | 231 passed, 4 skipped |
| Security containment (windows-latest) | Windows | `129162931217` | 229 passed, 6 skipped |
| Security containment (macos-latest) | macOS | `129162931678` | 231 passed, 4 skipped |

The Phase 1.4 verdict is **PARTIAL**: the production ACL-grant branch and
AppContainer network denial remain unproven, the AppContainer TMP contract is
not observed, and Python 3.11's full guarded import still fails. Full details:
`docs/production/phase-1/PHASE_1_4_WINDOWS_RUNTIME_QUALIFICATION.md`.

## 11. Phase 1.4 corrective follow-up

Commit chain:

| Commit | Purpose |
|---|---|
| `3cc8c780` | Replace AppContainer temp-file output with bounded pipes; replace fallback `readline()` with fixed 64 KiB binary chunks; 1 MiB per-stream retention; strengthen DACL/process/memory/output tests. |
| `3072e3cf` | Record corrective CI evidence. |

Verified results:

- AppContainer stdout/stderr now use anonymous pipes. Only child-side write
  handles are inheritable; readers drain 64 KiB chunks and retain at most
  1 MiB per stream. No output temp files are created.
- Fallback uses binary fixed-chunk reads; no `readline()` and no unbounded line.
- Both streams enforce independent 1 MiB caps; excess is drained.
- DACL test requires a successful baseline AppContainer start, then exact
  exit 1 / "Access is denied" for the denied read and write.
- Process-limit test asserts `OSError` WinError 1816.
- Memory test proves 128 MB succeeds under 512 MB and raises `MemoryError`
  under 64 MB; peak is recorded but no strict peak claim is made.
- Runtime harness: 19 passed with AppContainer opt-in.
- Security suite: 232 passed, 3 skipped; static 173; guarded import 1; checkup
  57/5/0; checkup tests 19.
- Python 3.11: 231 passed, 3 skipped excluding full import; full import still
  fails on `platform.system()`.

CI evidence, `Security guard` run `42646010564` on `3cc8c780`:

| Job | Platform | Job ID | Result |
|---|---|---|---|
| Security containment (ubuntu-latest) | Ubuntu | `129259325291` | 231 passed, 4 skipped |
| Security containment (windows-latest) | Windows | `129259325696` | 229 passed, 6 skipped |
| Security containment (macos-latest) | macOS | `129259325512` | 231 passed, 4 skipped |

Phase 1.4 remains **PARTIAL**: the output-bound and test-integrity findings are
closed, but the production ACL-grant branch and AppContainer network denial
remain unproven. Full details: `docs/production/phase-1/PHASE_1_4_WINDOWS_RUNTIME_QUALIFICATION.md` section 14.

## 12. Phase 1.4 final closure

Commit chain:

| Commit | Purpose |
|---|---|
| `3cc8c780` | Bounded AppContainer/fallback output capture. |
| `0bf14d9c` | Removed automatic WindowStation/Desktop ACL write; fixed Python 3.11 import-time `platform.system()`; added native network probe, TMP contract test, memory control, dedicated Windows runtime CI. |
| `71479fb6` | Final Phase 1.4 evidence and CI identifiers. |

Final decisions:

- **ACL:** automatic `_ensure_windowstation_desktop_access()` call removed. The
  production path never rewrites machine WindowStation/Desktop DACLs; an
  environment that cannot launch AppContainer fails closed. The helper remains
  for explicit operator provisioning only.
- **Network:** native Winsock control succeeded; AppContainer TCP connect timed
  out and the listener saw no connection. Denial is a silent kernel drop, not a
  Winsock error. UDP `sendto` returned success but no datagram was received.
- **Python:** 3.11 remains supported. `platform.system()` at import was replaced
  with `os.name == "nt"` in `windows_shell.py` and `terminal_tools.py`; both
  3.11 and 3.14 pass the full security suite and guarded import.
- **TMP:** AppContainer uses package-local `AC\Temp`; staging remains the
  file-delivery root. The runtime test asserts the package-local contract.
- **Memory:** 64 MB job limit denies a 128 MB allocation; `PeakJobMemoryUsed`
  remains ~140 MB, so hard peak-memory enforcement is not claimed.

Final CI:

- Security guard `42654054565` on `0bf14d9c`: Ubuntu `129287687682` 231/4,
  Windows `129287687039` 229/6, macOS `129287687623` 231/4.
- Windows runtime `42654054623`, job `129287686824`: **21 passed in 27.93 s**,
  including the native network probe.

Release decision: **WINDOWS SECURITY QUALIFIED** for the declared Windows 11 +
Python 3.11/3.14 contract, with the documented memory-accounting limitation and
silent-drop network behavior. This is not whole-product production readiness.

## 13. Phase 1.4 fail-closed correction

Commit chain:

| Commit | Purpose |
|---|---|
| `5a51897c` | Check all security-critical process-creation steps; fail closed on Job assignment/resume/attribute failures; no silent AppContainer downgrade; accurate capability reporting; six failure-injection tests; Python 3.11/3.14 runtime CI matrix. |
| `e9b6ee02` | Final correction evidence and CI identifiers. |

Final decisions and evidence:

- AppContainer process is created suspended; Job assignment must succeed before
  `ResumeThread`; assignment failure never resumes; `ResumeThread` must return
  previous suspend count 1.
- Attribute-list and security-capability failures return exit 127 and clean up
  pipes, handles, attribute list and Job Object.
- AppContainer provisioning failure raises by default. Job Object-only fallback
  requires `CRUSOR_ALLOW_JOB_OBJECT_FALLBACK=1` and reports false AC/network/
  low-integrity capabilities.
- TMP is package-local `AC\Temp`; staging remains the delivery root.
- Network evidence is TCP loopback only; denial is silent. UDP/DNS/non-loopback
  are not claimed.
- Python 3.11 and 3.14 both pass full security suite, guarded import and 27/27
  runtime tests.

Final CI:

- Security guard `42661726444` on `5a51897c`: Ubuntu `129314746085` 231/4,
  Windows `129314746216` 229/6, macOS `129314746483` 231/4.
- Windows runtime `42661726660`: Python 3.14 job `129314745800` 27 passed in
  24.16 s; Python 3.11 job `129314746236` 27 passed in 24.54 s.

Release decision: **WINDOWS SECURITY QUALIFIED** for the declared Windows 11 +
Python 3.11/3.14 contract, with the documented silent-drop TCP behavior and Job
Object peak-accounting limitation. This is not whole-product production
readiness.
