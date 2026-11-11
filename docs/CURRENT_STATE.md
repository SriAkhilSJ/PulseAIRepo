# CrusorAI - Current State

**Snapshot date:** 2026-11-10 (local)
**Branch:** `feat/prompt-cache-stabilization`
**HEAD:** `604605b2a02b3b1b6960f7959f4c122aeeed8bd4`
**Origin:** identical to HEAD at snapshot time
**Current phase:** Product qualification: scope-fidelity fixes + first live Velona Electron coding task passed (COMPLETED/VERIFIED, one file); production readiness still not claimed

> Canonical committed state is HEAD. The working tree contains 239 entries
> that are not part of any commit; see section 5. Never treat those files as
> shipped behaviour.

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
| Phase 3.1 orchestrator approval | **PASS (bounded)** | `efda16c9`, `b5277512`; evidence `bench-results/phase-3-approval-integration` |
| Phase 3.2 planner/contract closure | **PASS (bounded)** | `7879e066`, `604605b2`; evidence `bench-results/phase-3.2-planner-contract-closure` |
| Agent Runtime Increment 1 (canonical LangGraph + delegation) | **PASS (bounded)** | `bench-results/phase-3.3-canonical-runtime/EVIDENCE.md` |
| Agent Runtime Increment 2 (context/tools/approval/mutation) | **PASS (bounded)** | `.../INCREMENT2_EVIDENCE.md` |
| Agent Runtime Increment 3 (delivery/persistence/FinOps) | **PASS (runtime gates)** | `.../INCREMENT3_EVIDENCE.md` |
| Product scope fidelity + live Velona task | **PASS (n=1 live smoke); not production-ready** | `.../QUALIFICATION_REPORT.md`; `logs/live-e2e4/` |
| Desktop GUI live acceptance | **PASS (provider-free Electron E2E)** | `bench-results/phase-3.3-canonical-runtime/DESKTOP_REPAIR_EVIDENCE.md`; screenshots under `logs/desktop-e2e/` |
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

## 1c. Agent Runtime increments 1–3 (2026-11-10)

The three-increment migration in `docs/ARCHITECTURE.md` §14 is implemented.

- **Increment 1**: LangGraph (`stream_agent`) is the only interactive owner;
  the bridge no longer selects the orchestrator; `engineering_task_node`
  delegates to `EngineeringExecutionOrchestrator` with
  `EngineeringTaskRequest → DeliveryContract`; B-DESK-001 compaction exports
  repaired; graph-side direct mutations fail closed.
- **Increment 2**: one context lifecycle
  (`ContextEngine.build_engineering_context`), one model gateway
  (`src/llm/gateway.py`), explicit tool side-effect classification, and
  digest-bound approval tokens consumed by `WorkspaceMutationBroker`.
  `write_file`/`edit_file` are enabled through the broker; shell/opaque/other
  mutations stay disabled.
- **Increment 3**: one canonical `TurnReceipt` persisted in the checkpoint and
  emitted on `turn_done`; one FinOps invocation ledger per workspace; approval
  tokens bind session/turn/content digest/workspace precondition/expiry/single
  use; B-DESK-006 fixed; the old bridge orchestrator branch removed.

Runtime evidence (provider-free):
- core runtime 155 passed; bridge sidecar 38 passed / 1 pre-existing failure;
  security containment 232 passed / 3 skipped; eval/P0 49 passed / 5
  pre-existing failures;
- restart replay: approve `COMPLETED`, deny `DENIED`, cancel `CANCELLED`, same
  receipt id after process restart, workspace empty on deny/cancel;
- stale-workspace approval tests pass (A→B approved, external A→C, B refused);
- **Desktop repair (2026-11-10)**: the real Agent pane now opens. Root cause was
  `chatSessionRoutingProviderService` being registered only by the separate
  sessions app entry; the workbench chat contribution now imports the real
  singleton. The stale panel was fixed by running
  `node scripts/emit-crusorai-bundle.mjs` after compile. CDP was available on
  port **9222**. Through the actual UI: chat prompt/response, engineering
  diff approval + broker write + report, denial (`Run denied`, 0 landed) and
  cancellation (`Run cancelled`, 0 landed) all passed. Evidence:
  `DESKTOP_REPAIR_EVIDENCE.md`, `logs/desktop-e2e/`.
- **Product qualification (2026-11-10)**: fixed two scope leaks — an explicit
  `.md` request was classified SOURCE (synthesizing `src/req_001_module.py`),
  and a “Do not create … tests” sentence became a TEST requirement. Scope tests
  pass 7/7. First live Velona task through the real Electron UI created exactly
  `hello.md`, was independently VERIFIED, recorded one approval/one mutation,
  one provider invocation (3013 in / 38 out), cost ₹0.014704, and a COMPLETED
  TurnReceipt. Total live spend across 5 bounded calls: ₹0.092942. See
  `QUALIFICATION_REPORT.md`; not production-ready.

No commit or push was made for these increments.

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
| Desktop GUI acceptance | **Passed for the provider-free Agent pane** | Real Electron UI exercised chat, engineering approve, denial and cancellation. Full TurnReceipt field rendering and live providers remain open. |
| Electron workbench panel | **Current** | `SOURCES_HASH` regenerated; bridge reports panel current. |
| Live provider cost/latency | **First bounded smoke measured** | 5 Velona calls, ₹0.092942 total; one successful task at ₹0.014704. Not a competitive benchmark. |
| Live output quality | Mojibake observed | `hello.md` contained emoji mojibake (`dY'<`, `�?"`); scope/verification unaffected. |
| Invocation ID consistency | Fix not live-reverified | Final call logged `inv-f417…` while ledger recorded `inv-6cd6…`; adapter fix applied after the 5-call cap. |
| 24-hour cloud readiness | Not proven | No deployment, uptime, recovery or monitoring evidence. |
| Identity/RBAC enforcement in agent tool path | Not wired | `IdentityAwareToolAuthorizer` exists but is referenced only by identity code and tests. |
| Protocol events for intelligence artifacts | Missing | Architecture/impact/regression/verification reports have no server frames. |
| Machine-level WindowStation/Desktop ACL recovery | Unresolved | Carried forward from earlier security phases. |

## 5. Working tree (important)

Baseline at the qualification close: **239 entries**, all preserved. Snapshot:
`C:\Users\Administrator\AppData\Local\Temp\opencode\crusor-snapshot-20261110`
(binary patch + 1,669 files + SHA-256 manifest; secrets excluded).

- The Agent Runtime increments added/modified runtime, tests and compiled
  desktop workbench artifacts. These remain **uncommitted**.
- Important modified runtime files include `src/graphs/chat_graph.py`,
  `src/graphs/state.py`, `src/bridge/__main__.py`,
  `src/orchestration/{orchestrator,model_adapter,approval_gateway}.py`,
  `src/workspace/{risk_policy,mutation_broker}.py`,
  `src/tools/file_tools.py`, `src/finops/invocation_context.py`,
  `src/llm/{gateway,factory}.py`, and `src/context/context_engine.py`.
- New runtime/evidence files include `src/runtime/turn_receipt.py`,
  `src/workspace/approval_context.py`, `src/workspace/approval_digest.py`,
  `src/graphs/tool_policy.py`, `src/llm/gateway.py`, and the increment test
  suites.
- `desktop/vscode/out/vs/workbench/contrib/crusorai/**` was rebuilt by
  `npm run compile-client` for the B-DESK-006 renderer fix.
- Pre-existing user work (apps, diagnostics, benches, generated modules,
  uncommitted broker wiring) is preserved. Do not clean/reset/revert it.

Critical nuance:

- At **HEAD**, `src/tools/file_tools.py` does not contain the
  `WorkspaceMutationBroker` wiring; the working copy does. Treat it as
  uncommitted work, not shipped behaviour.
- The `docs/` memory layer itself is untracked.

## 6. Test status

| Source | Scope | Result | Status |
|---|---|---|---|
| Phase 1.3.1 local + CI | Security suite | 90/90 executed tests pass, 3 Windows skips | Verified 2026-11-08/09 |
| Phase 1.4 final | Windows security | 232/3 on Python 3.11 and 3.14; 27/27 runtime tests on both; Windows runtime CI 27/27 each; three-platform security CI green | QUALIFIED |
| Agent-core checkup | 14 pipelines | 57 pass, 5 warn, 0 fail | Verified 2026-11-09 |
| Checkup regression suite | `src/tests/test_agent_core_checkup.py` | 19 passed | Verified 2026-11-08 |
| Phase 12.1.3 record | 395-test regression subset | 395/395 | Documented, not re-run |
| README (2026-10-27) | Full suite on `main` | 2,802 passed, 25 failed, 26 skipped, 1 xfailed | Historical; same 25 identities as baseline |
| Increment 3 core runtime | Phase 3.1/3.2/11.6/compaction/bridge/Inc1/Inc2/Inc3 | **155 passed** | Verified 2026-11-10 |
| Increment 3 bridge sidecar | `src/tests/test_bridge.py` | **38 passed, 1 pre-existing failure** | Verified 2026-11-10 |
| Increment 3 security | `test_security_containment.py` | **232 passed, 3 skipped** | Verified 2026-11-10 |
| Increment 3 eval/P0 | evals, Attempt11, autonomous, P0.3/P0.4, adapter | **49 passed, 5 pre-existing failures** | Verified 2026-11-10 |
| Desktop repair core | Phase 3.1/3.2/11.6/compaction/bridge/Inc1/Inc2/Inc3 | **155 passed** | Verified 2026-11-10 |
| Desktop repair security/evals | security, evals, Attempt11, autonomous | **260 passed, 3 skipped, 3 pre-existing failures** | Verified 2026-11-10 |
| Desktop static/renderer | startup registration + renderer architecture | **120 passed, 1 skipped, 1 xfailed** | Verified 2026-11-10 |
| Product qualification core | runtime, scope fidelity, desktop static | **282 passed, 1 skipped, 1 xfailed** | Verified 2026-11-10 |
| Live Velona Electron task | exact one-file prompt | **COMPLETED / VERIFIED**, 1 invocation, ₹0.014704 | Verified 2026-11-10 |

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

1. Decide the working-tree disposition: commit the Agent Runtime + desktop
   repair + memory layer, or retain as reviewed uncommitted work. No commit was
   authorized.
2. Render the full canonical `TurnReceipt` (not only the delivery report) in the
   Agent pane.
3. Run a full-suite baseline on HEAD + working tree and classify every failure.
4. Live provider/paid-call acceptance remains blocked pending explicit
   authorization.

See `docs/handoffs/LATEST_HANDOFF.md` for commands, evidence paths and
constraints.

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

## 2026-11-10 — Product quality & streaming UI (uncommitted)

- HEAD `604605b2a02b3b1b6960f7959f4c122aeeed8bd4`; branch
  `feat/prompt-cache-stabilization`; origin 0/0; no commit/push.
- Working tree 273 entries (101 modified, 172 untracked); the previous 239-entry
  snapshot remains valid and untouched.
- UTF-8: provider-free byte-level tests cover emoji, Devanagari, Japanese,
  smart punctuation, backslashes, multiline Markdown and CRLF rejection across
  gateway, protocol, broker and file tools (4/4).
- Invocation identity: gateway id is adopted by the adapter, ledger and receipt;
  replay rows count once; distinct retries stay distinct (6/6).
- Workspace isolation: one-file tasks leave only the requested file; FinOps,
  diagnostics, journals, baselines, contracts, reports and sessions live under
  app data (1/1).
- Streaming/UI: versioned `agent_card` contract with nine card types, renderer
  re-validation, text-only painting, unknown-card fallback; genuine Electron
  acceptance passes 15/16 checks with screenshots.
- Known limitation: renderer reload with the scripted fixture shows no durable
  transcript because the fixture bypasses LangGraph's checkpointer; production
  replay remains covered by Increment checkpoint tests, not by this fixture.
- Evidence: `bench-results/phase-3.3-canonical-runtime/PRODUCT_QUALITY_EVIDENCE.md`.

## 2026-11-10 — Final Agent Core qualification (uncommitted)

- Provider fixture now runs at the model-provider boundary and falls through to
  the real LangGraph turn/checkpointer; the bridge bypass is gone.
- Electron reload restored the transcript and cards from checkpoints/journal:
  session `session-59d8…`, 8 checkpoint rows before/after, no turn re-execution.
- Evidence manifest is versioned, COMPLETE (10 artifacts) and hash-verified;
  manifest self-hash convention uses `EVIDENCE_MANIFEST.sha256`.
- Invocation identity is proven across graph chat, gateway, ledger, TurnReceipt
  and cost card; engineering/repair ledger semantics covered provider-free.
- Focused regressions: 196 passed / 1 skipped / 1 xfailed; 263 passed / 4 skipped.
- Remaining: full engineering dispatch is not provider-free end-to-end; one
  Windows 8.3 path-alias shadow-checkpoint test fails (environment limitation).
- Report: `bench-results/phase-3.3-canonical-runtime/FINAL_AGENT_CORE_QUALIFICATION.md`.
- Live verification (₹25 owner cap): chat `inv-8d717e667d854dfe` and engineering
  `inv-ce47c37e93364048` matched gateway/ledger/receipt; engineering COMPLETED +
  VERIFIED, exact UTF-8 `hello.md`, ₹0.017109 settled, 1 approval/1 mutation.
  Chat cost was provider-unknown and is preserved as unknown (0.0 defect fixed).
- Evidence: `logs/live-final/`; the ₹25 cap was not approached.

## 2026-11-11 — Agent Core closure (uncommitted, architecture frozen)

- Engineering implementation dispatch proven through the real graph →
  orchestrator → adapter → gateway → ledger → receipt with a provider-boundary
  fixture; receipt/ledger ids match.
- Combined Electron engineering acceptance PASS: one `acceptance.md`, approval,
  mutation, plan/file/verification/delivery cards, VERIFIED, reload and fresh
  bridge restart with no duplicate execution.
- Fresh bridge-process restart PASS: old PID exited, new OS process started,
  transcript/cards restored, checkpoint count unchanged.
- Windows path identity fixed with `PathSafetyValidator.canonical_path`
  (`realpath`/final-path canonicalization); 6 native alias/junction tests pass.
- Repair dispatch remains PARTIAL: no scripted failed-verification repair loop
  was produced; ledger/retry semantics are covered provider-free.
- Regression: 205 passed / 1 skipped / 1 xfailed targeted; 287 passed / 4 skipped
  desktop/security/path/shadow.
- Report: `bench-results/phase-3.3-canonical-runtime/FINAL_CLOSURE_REPORT.md`.
