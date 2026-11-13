# CrusorAI - Current State

**Snapshot date:** 2026-11-12 (engineering audit + memory reconciliation)
**Branch:** `feat/prompt-cache-stabilization`
**HEAD:** `fb5bd528b40933346c4004a1490154683dc0d40e`
**Origin:** `origin/main` is 3 commits ahead (release follow-ups); no local push
**Verified condition of record:** `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` (F-01…F-15)
**Current phase:** P1-A checkpoint/session test isolation is fixed; P1-A-R2
closed the bridge `prior_checkpoints` and OTel cleanup leaks; P1-A-R3 closed the
final B-4 SQLite URI path-encoding defect. R3 is awaiting independent
acceptance. P1-B (collection errors and known test failures) remains the next
review-gated task. Production readiness is not claimed.

> Canonical committed state is HEAD. At the 2026-11-12 audit the working tree
> held **262 entries** (80 modified tracked, 182 untracked, 0 staged, 0
> deletions). The memory reconciliation added two documentation files, P1-A
> added the isolation changes and one handoff archive, P1-A-R2 added the
> bridge/OTel fixes and a second test module, and P1-A-R3 added the URI helper
> and a third test module, so the current count is **272** (84 modified,
> **188 untracked**, 0 staged, 0 deletions). Never treat those files as shipped
> behaviour.
>
> The 195/211/239/247-entry counts below are historical snapshots, not the
> current count. HEAD is unchanged at `fb5bd528`; nothing was reset, cleaned,
> checked out or committed by the audit or the memory reconciliation.

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
| Live engineering progress integration | **PASS (provider-free Electron, 16/16)** | `CRUSOR_PROGRESS_INTEGRATION_REPORT.md`; `.../logs/electron-progress/` |
| Engineering DAG completion recording | **PASS (deterministic + Electron)** | `CRUSOR_PLAN_COMPLETION_REPORT.md` |
| Plan outcome semantics (blocked/cancelled) | **PASS (provider-free Electron, 21/21)** | `CRUSOR_PLAN_OUTCOME_SEMANTICS_REPORT.md`; `.../logs/electron-progress/{04,05,06}-*.png` |
| Multi-turn engineering storage isolation | **FIXED** (invalid state transition) | `src/graphs/chat_graph.py` per-turn storage |
| 2026-11-12 engineering audit + memory reconciliation | **COMPLETE (documentation)** | `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` |
| 2026-11-12 P1-A test isolation repair | **DONE-VERIFIED** | `src/tests/test_checkpoint_isolation.py` (15 passed); real DB unchanged |
| 2026-11-12 P1-A-R2 review remediation | **DONE-VERIFIED** | B-1/B-2 fixed; 22 isolation + 4 bridge tests; real DB + sidecars unchanged |
| 2026-11-12 P1-A-R3 URI correction | **DONE-VERIFIED; awaiting acceptance** | B-4 fixed with `sqlite_readonly_uri`; 6 passed + 1 POSIX-only skip; real DB + sidecars unchanged |
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
- Historical r2 note (superseded 2026-11-12): the Agent Core graph import
  defect reported below was fixed at HEAD by `5197937a`; the graph imports and
  runs. The real remaining gaps are approval execution, light-theme fidelity
  and cold replay, not a compaction import error.
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

Committed later in `5197937a` (`feat(agent): finalize canonical runtime and
execution boundaries`), verified 2026-11-12. The 2026-11-10 note below described
the working tree at that time; it is history, not the current disposition. The
later 2026-11-11 visibility/card work remains uncommitted.

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
- One interactive owner: the bridge always calls `stream_agent`
  (`canonical_runtime=True`); `engineering_task_node` delegates to
  `EngineeringExecutionOrchestrator`. `CRUSORAI_ORCHESTRATOR_ENGINE` no longer
  selects an owner (`src/bridge/__main__.py:1640-1688`).
- Execution broker and per-OS sandbox backends exist, including Windows
  AppContainer/Job Object support (`src/security/`), but terminals and test
  execution are **not** routed through them by default (F-03).
- SQLite persistence in `~/.crusorai/sessions.db` (default; path now resolves
  `CRUSORAI_CHECKPOINT_DB`/`CRUSORAI_CHECKPOINT_HOME`/`CRUSORAI_SESSIONS_DB`/
  `CRUSORAI_HOME`, and the connection is lazy — F-05 P1-A). Workspace
  `.crusorai/` ledgers, event journals, and JSONL financial records remain.
- 363 `test_*.py` modules under `src/tests/`; at P1-A `pytest --collect-only`
  reported **4,968 tests and 3 collection errors** (15 isolation tests). P1-A-R2
  expands that module to 22 tests and adds 4 bridge regressions; P1-A-R3 adds 7
  URI regressions. The global collection was not re-run in R2/R3. CI workflows
  exist but are path-filtered (F-02).

## 4. What is incomplete or unverified

| Item | Status | Notes |
|---|---|---|
| Phase 2 | **2A and 2D implemented; 2B/2C not started** | Discovery, outside-workspace grants and guards are in the working tree; targeted edits and the repair loop are not (F-01). |
| Independent review of Phase 1.3.1 | Pending | Required by the phase instructions. |
| Full test suite on current HEAD | **Collection fails; full run not executed** | 4,953 tests collect with 3 errors; 3 known failures. See section 6 and F-02. |
| Live provider acceptance | Not revalidated | P0.6.9 evidence recorded a failure; LIVE12 remains unrun/uncertain. |
| Desktop GUI acceptance | **Passed for the provider-free Agent pane** | Real Electron UI exercised chat, engineering approve, denial and cancellation. Full TurnReceipt field rendering and live providers remain open. |
| Electron workbench panel | **Current** | `SOURCES_HASH` regenerated; bridge reports panel current. |
| Live provider cost/latency | **First bounded smoke measured** | 5 Velona calls, ₹0.092942 total; one successful task at ₹0.014704. Not a competitive benchmark. |
| Live output quality | Mojibake observed | `hello.md` contained emoji mojibake (`dY'<`, `�?"`); scope/verification unaffected. |
| Invocation ID consistency | Fix not live-reverified | Final call logged `inv-f417…` while ledger recorded `inv-6cd6…`; adapter fix applied after the 5-call cap. |
| 24-hour cloud readiness | Not proven | No deployment, uptime, recovery or monitoring evidence. |
| Identity/RBAC enforcement in agent tool path | **PARTIAL (vacuous)** | `IdentityAwareToolAuthorizer` is called only by the engineering adapter with a hard-coded superadmin (`model_adapter.py:837-851`); it cannot deny. F-07. |
| Engineering tool binding / targeted edits | **Missing (F-01)** | Generation binds no read/search/list/test tools; whole-file regeneration. |
| Execution defaults | **Unsafe by default (F-03)** | Terminal env inherited + sandbox opt-in; test execution bypasses the broker. |
| Product approval default | **`workspace_session`, not `ask` (F-04)** | LOW-risk mutations auto-approved; acceptance scripts force `ask`. |
| Checkpoint persistence | **PARTIAL (P1-A)** | Path resolves env overrides and opens lazily; tests isolate home/sessions/checkpoint. Retention/vacuum and 936.7 MB growth remain (F-05). |
| Turn observability receipts | **Dead (F-06)** | `src/observability/` package shadows `src/observability.py`; call site swallows the error. |
| FinOps cancellation/pricing | **Under-counts / asserted (F-08)** | Post-dispatch Stop records zero usage; pricing marked verified without provenance. |
| Code verification without tests | **Conditional (F-09)** | `VERIFIED` can be presence-based when `testing_required` is false. |
| Non-desktop entry points | **Not canonical (F-10)** | Dashboard/CLI omit `canonical_runtime=True`. |
| Generated source contamination | **Open (F-11)** | `src/req_001/002_module.py` tracked (+2,549 lines); 003–005 untracked. |
| Protocol events for intelligence artifacts | Missing | Architecture/impact/regression/verification reports have no server frames. |
| Machine-level WindowStation/Desktop ACL recovery | Unresolved | Carried forward from earlier security phases. |

## 5. Working tree (important)

Baseline at the qualification close: **239 entries**, all preserved. Snapshot:
`C:\Users\Administrator\AppData\Local\Temp\opencode\crusor-snapshot-20261110`
(binary patch + 1,669 files + SHA-256 manifest; secrets excluded).

At the 2026-11-11 agentic-visibility snapshot the working tree held **195
entries** (later per-turn card work brings it to **211**); the 239-entry record
above is historical. At the verified **2026-11-12 audit** it held **262
entries**: 80 modified tracked, 182 untracked, 0 staged, 0 deletions. After the
documentation reconciliation it was **264** (184 untracked); after P1-A it was
**269** (83 modified, 186 untracked); after P1-A-R2 it was **271** (84 modified,
187 untracked); after P1-A-R3 it is **272** (84 modified, 188 untracked). All
pre-existing user work is still
preserved. The largest text deltas are the generated `src/req_001_module.py` /
`req_002_module.py` (+2,549 lines, F-11), not product code.

- The Agent Runtime increments are **committed** at `5197937a`. The later
  2026-11-11 visibility/card work, compiled desktop artifacts, apps, diagnostics
  and the docs memory layer remain **uncommitted**.
- Important modified runtime files include `src/graphs/chat_graph.py`,
  `src/graphs/state.py`, `src/bridge/__main__.py`,
  `src/orchestration/{orchestrator,model_adapter,approval_gateway}.py`,
  `src/workspace/{risk_policy,mutation_broker}.py`,
  `src/finops/invocation_context.py`, `src/llm/{gateway,factory}.py`, and
  `src/context/context_engine.py`.
- New runtime/evidence files include `src/runtime/turn_receipt.py`,
  `src/workspace/approval_context.py`, `src/workspace/approval_digest.py`,
  `src/graphs/tool_policy.py`, `src/llm/gateway.py`, and the increment test
  suites.
- `desktop/vscode/out/vs/workbench/contrib/crusorai/**` was rebuilt by
  `npm run compile-client` for the B-DESK-006 renderer fix.
- Pre-existing user work (apps, diagnostics, benches, generated modules,
  uncommitted desktop artifacts) is preserved. Do not clean/reset/revert it.
- Generated engineering artifacts (`src/req_003..005_module.py` untracked;
  `req_001/002` tracked and modified) are contamination, not product code
  (F-11). Do not treat them as fixtures.

Critical nuance:

- At **HEAD** (verified 2026-11-12), `src/tools/file_tools.py` **does** route
  `write_file`/`edit_file` through `WorkspaceMutationBroker`; the file is
  unchanged in the working tree. B-001 is fixed at HEAD. The old "working copy
  only" claim was wrong and is superseded by this note.
- The `docs/` memory layer is tracked; the 2026-11-11/12 updates in this file
  are uncommitted.

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
| **2026-11-12 audit — collection** | full `src/tests` | **4,953 collected, 3 collection errors** (14.8 s) | **FAIL (exit 1)** |
| **2026-11-12 audit — security** | `test_security_containment.py` | **232 passed, 3 skipped** (32.57 s) | PASS (exit 0) |
| **2026-11-12 audit — bridge** | `test_bridge.py` | **37 passed, 2 failed** (140.33 s) | FAIL (exit 1) |
| **2026-11-12 audit — cards** | `test_agent_cards.py` | **10 passed, 1 failed** | FAIL (exit 1) |
| **2026-11-12 audit — outcomes/cards** | `test_plan_outcome_semantics` + `test_turn_card_association` | **29 passed** (10.15 s) | PASS (exit 0) |
| **2026-11-12 audit — discovery/grants** | Phase 2A + Phase 2D | **26 passed** (56.82 s) | PASS (exit 0) |
| **2026-11-12 audit — scope fidelity** | `test_scope_fidelity.py` | **7 passed** (22.14 s) | PASS (exit 0) |
| **2026-11-12 audit — checkup** | `scripts/agent_core_checkup.py` | **57 pass, 5 warn, 0 fail** | PASS (exit 0) |
| **2026-11-12 P1-A — checkpoint isolation** | `test_checkpoint_isolation.py` | **15 passed** (39.81 s) | PASS (exit 0) |
| **2026-11-12 P1-A — collection** | full `src/tests` | **4,968 collected, 3 errors** (6.91 s) | **FAIL (known)** |
| **2026-11-12 P1-A — core gate** | 20 prior modules + new module | **366 passed, 2 skipped, 1 xfailed** (193.28 s) | PASS (exit 0) |
| **2026-11-12 P1-A — graph/restart** | increment 2/3, plan completion, invocation reconciliation, session store/search | **139 passed** (59.40 s) | PASS (exit 0) |
| **2026-11-12 P1-A — session/acceptance** | session store/search + phase 12.1 | **35 passed** (9.20 s) | PASS (exit 0) |
| **2026-11-12 P1-A — security** | security containment | **232 passed, 3 skipped** (21.34 s) | PASS (exit 0) |
| **2026-11-12 P1-A — bridge** | `test_bridge.py` | **37 passed, 2 known failures** (157.60 s) | FAIL (known) |
| **2026-11-12 P1-A — evidence capture sample** | `test_runtime_evidence_capture.py` (3 selected) | **3 known failures** (2 Windows mode bits, 1 echo/degraded) | FAIL (pre-existing) |
| **2026-11-12 P1-A — real DB immutability** | `~/.crusorai/{sessions,runtime_events,verification}.db` | byte-identical before/after verification; sessions sha256 `5fc06788…`, size 937,684,992 | PASS |

The 25 historical failures are not proven fixed. The suite cannot currently be
collected in full (three modules fail at import), and three modules are red. Do
not claim a clean suite until a fresh full run is recorded here with a commit,
count and exit code (F-02).

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

The 2026-11-12 audit establishes this order. Do not start a later item while an
earlier one is red.

1. **Security defaults (F-03/F-04):** default to `ask`, route all process
   creation through `ExecutionBroker`, scrub child env, and add negative tests.
2. **Engineering capability (F-01):** Phase 2B — bind bounded read/list/search
   during generation, targeted edits, unconditional requirement-id rejection.
3. **Test/CI baseline (F-02/F-06):** fix the three collection errors, update the
   two bridge pins and the card-type pin, run the full suite, and gate it in CI.
4. **Persistence/observability (F-05/F-06):** checkpoint path/import isolation
   is fixed (P1-A); add retention/vacuum, decide workspace placement, and fix
   the `src/observability` collision.
5. **Authorization and money truth (F-07/F-08):** real principal, cancellation
   accounting, pricing provenance.
6. Decide the working-tree disposition (264 entries): commit reviewed work or
   retain explicitly. No commit is authorized by this audit.
7. Render the full canonical `TurnReceipt` in the Agent pane.
8. Live provider/paid-call acceptance remains blocked pending explicit
   authorization.

See `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` for evidence and
`docs/handoffs/LATEST_HANDOFF.md` for commands and constraints.

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

## 2026-11-11 — Agentic progress + plan outcome semantics (uncommitted)

Live engineering visibility is now wired end to end, and the existing plan card
carries truthful execution outcomes.

- **Progress integration.** `engineering_task_node` passes
  `EngineeringProgressReporter` as `on_progress` to `run_task_request`; each
  `DesktopVisibilityReporter` snapshot is projected onto the existing
  `agent.card` activity card (`<turn>:activity`) and `plan.created` plan card
  (`<turn>:plan`). Bounded (240/turn), deduplicated, cancellation-aware,
  exception-safe, redacted. No fabricated tool/file/test/verification/cost
  events. Bridge journals `agent_card` frames so progress survives reload.
  Report: `CRUSOR_PROGRESS_INTEGRATION_REPORT.md`.
- **DAG completion.** `AdaptiveContextManager.record_task_outcome` is the single
  settlement point: `COMPLETED` after the executor returns success, `FAILED`
  after a real failure/exception, `BLOCKED` for dependency/upstream halted work,
  `CANCELLED` for Stop-interrupted work. `record_task_completion` is idempotent;
  no completion is inferred from `DELIVERED`. Report:
  `CRUSOR_PLAN_COMPLETION_REPORT.md`.
- **Six-state plan contract.** The existing `CrusorAIPlanStepView` union and
  `PLAN_STATUSES` gained `blocked` and `cancelled`; strip glyphs are
  `debug-pause`/`stop-circle`, card marks `⊘`/`–`, with warning/disabled theme
  colors. No new card type, schema version or renderer. Old four-status cards
  remain valid. Report: `CRUSOR_PLAN_OUTCOME_SEMANTICS_REPORT.md`.
- **Multi-turn fix.** Every engineering turn previously shared one orchestration
  storage dir, so turn 2 loaded turn 1's `COMPLETED` state machine and failed
  with `cannot move from COMPLETED to UNDERSTANDING`. Storage is now per turn
  (`app_data_root(workspace)/orchestration/<task_id>`), isolating state,
  authoritative context and journal.
- **Provider-free Electron acceptance.** Three real-orchestrator turns
  (`CRUSORAI_ORCHESTRATOR_MOCK=1`, approval policy `ask`): completed (2/2),
  failed+blocked (1 failed, 1 blocked, 0 completed), cancelled (2 cancelled);
  all four states restored after reload. 21/21 checks PASS, FinOps ledger
  `rows=0`. Screenshots:
  `bench-results/phase-3.3-canonical-runtime/logs/electron-progress/`.
- **Tests.** Outcome semantics 16 passed; plan completion + progress +
  delegation/increment2/phase 12.1 = 80 passed; renderer/invocation/11.6/cards/
  protocol 194 passed, 1 skipped, 1 xfailed, 1 pre-existing failure; bridge
  64 passed, 2 pre-existing failures; `typecheck-client` exit 0; panel emitter
  wrote 43 files; card contract ok.
- **Working tree.** 195 entries, zero deletions, all pre-existing work
  preserved. Nothing committed or pushed.
- **Limitations.** Blocked vs intentional skip collapse (the scheduler has no
  intentional skip); node completion is a work-unit fact, not the final task
  verdict; multi-turn plan cards share the post-reload stack (existing renderer
  behaviour); no real-provider validation of these paths; two pre-existing
  `test_bridge.py` failures and the `test_agent_cards.py` card-type count
  mismatch remain.

## 2026-11-11 — Per-turn Agentic card restoration (uncommitted)

Cards now keep the turn that produced them through persistence, hydration and reload.

- **Root cause.** The renderer held one global `cards` map keyed by card id;
  `session_messages` loaded every journaled card into it and history rendering
  never passed cards into `assistantTurn()`. `hydrateTranscript()` had no turn
  identity, and the bridge returned messages without turn ids.
- **State model.** New `CrusorCardStore` (`common/crusorAICards.ts`) keys cards
  by `(turnId, cardId)` with stable per-turn order, idempotent updates/restore,
  and `clearTurn`/`clear`. The service holds a store plus `currentTurnId`;
  `resetSessionState` clears both; surface snapshots include `cardTurns`.
- **History identity.** The bridge stamps each projected message with the turn
  whose prompt produced it by matching the persisted human text against the
  journal's `turn.started.request.sha256`. `session_messages` dedupes cards by
  `(session, turn, card)` and pages the journal. Hydration attaches only each
  turn's `cardsFor(turnId)`; the renderer passes `cards`/`turnId` to history
  turns and marks sections with `data-turn-id`.
- **Legacy.** Journals without request hashes use ordinal association only when
  user-message and turn counts match exactly; otherwise a single hydrated turn +
  single bucket fallback; ambiguous cards stay in the store and are warned, never
  merged into the newest turn. Card schema is unchanged (v1).
- **Tests.** Node card contract extended for the store; new
  `test_turn_card_association.py` (13) and `test_turn_card_rendering.py` (7);
  focused 79 passed; renderer/protocol/cards 157 passed, 1 skipped, 1 xfailed,
  1 pre-existing failure; bridge 73 passed, 2 pre-existing failures;
  `typecheck-client` exit 0; emitter 43 files.
- **Electron.** PASS **32/32** checks with three turns (completed, failed+blocked,
  cancelled): each turn owns its own card ids and plan card; reload and a second
  hydration are identical; a full application restart restores all three turns
  with the same cards; `rows=0` provider invocations. Evidence:
  `bench-results/phase-3.3-canonical-runtime/logs/electron-progress/{acceptance.json,04-complete.png,05-failed-blocked.png,06-cancelled.png,05-after-reload.png,07-restarted.png}`.
- **Report.** `CRUSOR_TURN_CARD_RESTORATION_REPORT.md`.
- **Limitations.** Legacy multi-turn ambiguity is left unassigned; cards still
  render at the end of their turn (placement unchanged); journal paging reads the
  whole session journal.

## 2026-11-11 — Clean chronological Agentic timeline (uncommitted)

The user-facing conversation now hides internal-only cards and pins visible
cards into the turn timeline.

- **Rendering policy.** `CRUSOR_INTERNAL_CARD_TYPES = ['verification',
  'delivery', 'cost']`; `isUserFacingCard`/`userFacingCards` filter every
  `agentCardStack`, live and restored. The cards remain in the model, journal,
  receipts and FinOps records. Typed `tool` cards are suppressed when the turn
  already renders the matching tool row (no duplicate operation).
- **Timeline.** `CrusorAITurnPart` gained `{ kind: 'card'; cardId }`. Live cards
  are pinned at arrival; a late receipt card is inserted before the final
  assistant answer. Historical turns place the plan early and other visible
  cards before the final answer, preserving stored order. The final response is
  always last.
- **Evidence.** Electron acceptance PASS **40/40**, `rows=0`: three turns,
  reload, repeated hydration and full restart; no verification/delivery/cost
  card in the DOM (live or historical), while the journal still holds 3
  delivery + 1 verification + 3 cost cards across the three turns.
- **Tests.** Node card contract (policy + retention); timeline source contracts
  (11); turn-card suites 24; renderer/protocol/cards 161 passed, 1 skipped,
  1 xfailed, 1 pre-existing failure; workflow 28 passed, 1 pre-existing;
  `typecheck-client` exit 0; emitter 43 files.
- **Report.** `CRUSOR_AGENTIC_TIMELINE_REPORT.md`.
- **Limitations.** Historical interleaving uses anchors (checkpoint messages
  carry no per-event sequence); typed tool cards without a tool row fall back to
  the end; plan strip + plan card and approval dock + approval card remain as
  separate existing surfaces.

## 2026-11-11 — Real-provider E2E qualification (FAIL, stopped)

The first live qualification against the configured provider (`custom` /
`z-ai/glm-5.3-flash`, `https://velona.in/v1`) was stopped on request after Test A
was rejected **before dispatch**:

- `contract ambiguity: no public symbol is specified for the requested function`
  (`src/orchestration/contract.py:311-315`, `:522`) — the prompt's ordinary
  "a divide(a, b) function" phrasing is not parsed, so no plan, no tools, no
  edits, no tests, and **zero** provider calls for Test A.
- Two settled real calls did occur during Test B (6,264 in / 6,159 out,
  ₹0.143, 0 retries) before the run was stopped; that proves dispatch, not
  engineering work.
- Tests B and C are unproven, not disproven. UI streaming was judged
  unacceptable.
- **Spend:** ₹0.143 of a ₹50 cap. Authorisation closed.
- **Report.** `CRUSOR_REAL_PROVIDER_E2E_QUALIFICATION.md`; blocking defect
  recorded as B-LIVE-001 in `docs/BUGS_AND_LIMITATIONS.md`.

## 2026-11-11 — P0: contract extraction + honest failure states

- **B-LIVE-001 fixed.** `parse_prompt_contract` now reads natural language
  (`"Implement a divide(a, b) function"`, `"a function called divide"`, bare
  `divide(a, b)` in a creation clause, backticked method names) through five
  narrow clause-scoped patterns. Preservation/negation windows, parameter shape
  and stopwords prevent over-extraction; the ambiguity rules, plan validation,
  dispatch budgets and approvals are unchanged. Evidence:
  `src/tests/test_contract_natural_language.py` (20), LIVE7 regression intact.
- **B-LIVE-004 fixed (mission B-LIVE-002).** Turn outcome now comes from
  cancellation → canonical receipt → evidence status → `completed` → unknown
  (`common/crusorAITurnOutcome.ts`). A `completed:false` turn is `failed`, its
  message goes to the existing error row (the duplicate chunk is dropped), and
  the completion toast is not shown as success. Restored turns take their
  outcome from the journal's durable terminal row via
  `session_messages.turn_outcomes`; missing evidence is `unknown`, and hydrated
  tools are `recorded`, never `passed`.
- **Electron.** New `accept-crusorai-p0.mjs` (mock adapter only): **PASS 16/16**
  — natural-language request plans, genuine ambiguity still rejected, failed
  turn shows `Run failed` + error row live and after reload. Existing
  `accept-crusorai-progress.mjs` still **PASS 40/40**, `rows=0`.
- **Tests.** 267 passed / 1 skipped / 1 xfailed / 1 pre-existing failure
  (`test_all_required_card_types_are_declared`); contract suites 44 + 65;
  turn-outcome node contract ok; `typecheck-client` exit 0; emitter 44 files.
- **Report.** `CRUSOR_P0_CONTRACT_AND_FAILURE_REPORT.md`.
- **Limitations.** Restored failure text appears as transcript content plus the
  failed receipt (no per-message error flag yet); legacy journals show
  "Outcome not recorded"; B-LIVE-003 streaming and B-LIVE-002 ledger identity
  remain open; no real-provider run in this milestone.

## 2026-11-11 — P1A: incremental engineering model execution

- **Gateway.** `invoke_model(..., on_token=...)` consumes the provider's native
  stream, forwards deltas in order (cancellation checked between chunks), merges
  the chunks back into one response, and still returns usage for FinOps.
  Callers without `on_token` keep the exact non-streaming path.
- **Proxy.** `RetryLLMProxy.stream()` is single-attempt by design, registers the
  same abort handle as `invoke`, claims the acceptance slot, and reports
  `supports_streaming` so test doubles fall back honestly.
- **Adapter.** `_dispatch_code_prompt` wraps the one paid dispatch in a
  `GenerationActivity`: bounded deltas (4/s), a 3 s heartbeat (max 200), and a
  terminal close on completed/failed/cancelled. Updates carry session, turn,
  node and invocation ids — never prompt or model text.
- **UI mapping.** Live updates ride the existing `activity` card
  (`${turn}:activity`) as `ephemeral` frames the bridge does not journal; the
  graph also calls `progress.mark_generating(node_id)` so the plan shows the
  generating node `in_progress` instead of `0/2` while the model writes.
- **Evidence.** 20 deterministic tests (real loopback SSE transport + adapter +
  card/bridge) pass; Electron acceptance with the real orchestrator and a local
  SSE provider shows `Generating notes.md · 1s · 10 chars received` while the turn
  is running, `task_notes: is-in_progress`, and `Run cancelled` after Stop.
- **Report.** `CRUSOR_P1A_ENGINEERING_STREAMING_REPORT.md`.
- **Limitations.** Engineering model *text* stays internal by design; real
  provider chunk sizes/first-token latency remain unmeasured; one pre-existing
  stale cancellation test (`test_cancellation_stops_before_recovery`) still fails.

## 2026-11-11 — Conversational UI restored (card stack retired from the transcript)

- **Presentation policy.** Every typed agent card (`activity, plan, file_change,
  approval, tool, test_results, verification, delivery, cost`) is now internal:
  the transcript paints assistant Markdown, inline tool rows, the plan strip,
  the approval dock, thinking and error/receipt rows only. Backend generation,
  journaling, replay, receipts and FinOps are untouched.
- **Provenance.** PR #31 (`631ec58a`) added the cards in `f3528098`; the
  pre-merge renderer had no typed cards. No frontend commits followed the merge
  on this branch.
- **Streaming.** Progressive text was re-measured in Electron: 36 distinct,
  monotonically growing paints (`145 → 546` chars) before the turn ended; final
  Markdown (headings/list/code/inline) renders. The 160-char hold for
  tools-bound calls is unchanged (it predates PR #31 and prevents discarded
  pre-tool narration from flashing).
- **Evidence.** New `accept-crusorai-conversation.mjs` PASS 13/13 (stream, no
  cards, Markdown, cancel `Run cancelled`, reload). `accept-crusorai-p0.mjs`
  PASS 16/16 on the card-free UI. 181 renderer/protocol tests pass (1
  pre-existing card-type failure); typecheck 0; emitter 44 files.
- **Report.** `CRUSOR_CONVERSATIONAL_UI_RESTORATION_REPORT.md`.
- **Limitations.** Engineering turns still show no live prose (model output is
  a file body); the card-centric `accept-crusorai-progress.mjs` is superseded;
  tool-row restoration across restart needs a tool-bearing checkpoint fixture.

## 2026-11-12 — Agentic cards restored by owner decision

The card-free conversation from 2026-11-11 was **superseded** on owner
instruction (the cards were the desired "old" UI). Final policy:

- **Visible Agentic cards**: `activity`, `plan`, `file_change`, `tool`,
  `approval`, `test_results` — pinned chronologically into the turn.
- **Internal only**: `verification`, `delivery`, `cost` (still journaled,
  receipted, FinOps-tracked; never painted).
- **No status badge** (`RUNNING` / `COMPLETED`) on activity cards, and no plan
  outcome banner; the card shows the stage label + safe progress detail and the
  step list only.
- Engineering progress reaches the activity card through the existing
  `agent.card` frames (orchestrator stages + P1A generation heartbeat); the
  plan marks the generating node `in_progress`.
- Evidence: `accept-crusorai-streaming-engine.mjs` (activity card painted,
  5 real stages, internal cards 0, cancel `Run cancelled`, loopback SSE) and
  `accept-crusorai-conversation.mjs` (streaming text, Markdown, no internal
  cards/badges, reload).
- Historical note: the 2026-11-11 conversational restoration report describes
  the card-free state and is retained as history, not as current policy.

## 2026-11-12 — Real-provider backend qualification (terminal)

First real-provider engineering run without the UI, via
`stream_agent(canonical_runtime=True)` against `mini_math`:

- **Spend:** ₹0.4207 total (UI attempt ₹0.2392 + terminal ₹0.1815) of the ₹50 cap.
- **Provider path PASS:** 5 settled terminal calls, real tokens
  (15,929 in / 5,828 out), measured latency, `turn_id` = `turn-A/B/C`,
  receipts honest (`FAILED`, `FAILED`, `BLOCKED`).
- **Engineering FAIL:** A lost its source node and the reply was rejected as a
  malformed code fence; B "completed" by creating `src/req_001_module.py`,
  `src/req_003_module.py`, `tests/test_req_001_module.py` instead of editing
  `mini_math`; C blocked without running the failing tests (regression intact).
- **Root cause:** the engineering path binds **no tools** — no list/read/search,
  no test execution — so targets are guessed from requirement IDs.
- **Fixed in this pass:** `_ledger_record` now writes measured `latency_ms`.
- **Reports:** `CRUSOR_AGENT_CORE_ENGINEERING_QUALIFICATION.md` (map/audit) and
  `CRUSOR_AGENT_CORE_TERMINAL_QUALIFICATION.md` (results + Phase 2 scope).

## 2026-11-12 — Phase 2A: real workspace discovery before planning

The engineering path now inspects the workspace before it plans.

- **Tools.** `src/workspace/discovery.py` implements the only three read-only
  capabilities: `workspace.list_files`, `workspace.read_file`,
  `workspace.search`. Bounded depth/entries/bytes/lines/results/time; ignore
  set reused from `repo_map.IGNORED_DIRS`; containment delegated to
  `PathSafetyValidator`; symlinks never followed.
- **Evidence.** `src/workspace/evidence.py` lists, probes package directories
  named by the request, searches up to four derived terms, reads ≤4 bounded
  excerpts and ranks the results.
- **Planning.** `extract_contract` resolves targets as explicit mention →
  user-requested files → **discovered files** → synthesis (named from the
  request, never a requirement id). `__init__.py` is chosen only for export
  requirements. Ambiguity blocks the plan pre-dispatch. `validate_contract_plan`
  rejects requirement-id targets whenever evidence exists.
- **Lifecycle.** The orchestrator runs discovery inside STAGE 3
  (`PROJECT_DISCOVERY`), journals `WORKSPACE_TOOL_CALL`/`WORKSPACE_DISCOVERED`,
  honours cancellation, and adds `workspace_discovery` to the delivery.
  LangGraph and the orchestrator remain the only lifecycle owners.
- **Evidence run.** Disposable `mini_math` + mock mode: 5 files discovered,
  10 tool calls, journal order tool calls → discovered → contract → plan,
  contract targets `src/mini_math/ops.py` + `tests/test_ops.py`, 0 paid calls
  (with repairs disabled). Verdict `FAILED` — generation is unchanged; this
  phase only fixes targeting.
- **Tests.** `test_workspace_discovery_phase2a.py` 9 passed (A–H, including a
  graph-level ordering proof); 76 + 115 + 5 + 261 regression tests pass.
- **Spend.** One unintended repair dispatch (₹0.0601) in the first harness
  run; total programme ₹0.4808 of ₹50. Repairs are not gated by `mock_mode`
  (B-CORE-006).
- **Report.** `CRUSOR_PHASE_2A_WORKSPACE_DISCOVERY.md`.

## 2026-11-12 — Phase 2D: outside-workspace reads with a human grant

- **Trigger.** A request naming an absolute path or a `../` path outside the
  workspace (max 2 per turn) now asks the human once per exact path.
- **Approval.** `OrchestratorApprovalGateway.request_access` emits
  `tool.approval.request` with `name="workspace.access"`, the canonical path,
  operation and reason — same queue/dock as file writes, no new UI.
- **Grants.** `src/workspace/access_grants.py`: `read`/`write` separate,
  `once`/`turn` scope, exact-boundary matching, sensitive-name veto,
  turn-scoped only (nothing persisted).
- **Discovery.** Absolute paths inside the workspace are allowed; outside they
  return `access_required` until a grant exists. `../`, UNC, drive-relative,
  NUL, device names and symlink escapes stay hard rejections and never become
  prompts. A granted external file/folder is read into **context only** — it is
  never a plan target.
- **Writes.** Create/modify outside the workspace now work with a **write**
  grant plus the normal diff-bound mutation token (broker-enforced). Delete,
  rename and copy outside remain unsupported (B-CORE-007).
- **Tests.** `test_outside_workspace_access.py` 17 passed (allow/deny/timeout/
  cancel, once/turn, path-exact, sensitive, symlink, traversal, read vs write,
  broker modify, missing-token refusal, grant expiry, both orchestrator turns);
  Phase 2A suite 9 passed; 377 regression tests pass.
- **Spend.** Zero provider calls (`mock_mode=True`, repairs disabled). Programme
  total remains ₹0.4808 of ₹50.
- **Report.** `CRUSOR_PHASE_2D_OUTSIDE_WORKSPACE_ACCESS.md` §8.

## 2026-11-12 — Initial engineering audit + memory reconciliation

**Documentation-only. No source, dependency, git or provider change.**

The first source-based audit of the assembled product is recorded in
`docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md`. It establishes:

- **Working tree:** 262 entries at the audit (80 modified, 182 untracked, 0
  staged, 0 deletions) at HEAD `fb5bd528`; **264** after the documentation
  reconciliation and **269** after P1-A. The earlier 175/195/211/239/247 counts
  are historical.
- **Runtime ownership:** the bridge has one interactive owner
  (`stream_agent`); engineering is delegated from `engineering_task_node`.
  `CRUSORAI_ORCHESTRATOR_ENGINE` no longer selects an owner. B-DESK-001 is
  fixed at HEAD.
- **Mutation broker:** `write_file`/`edit_file` already route through
  `WorkspaceMutationBroker` at HEAD (`file_tools.py:508-538`); the old
  "uncommitted broker" claim was wrong.
- **Tests:** `pytest --collect-only` → 4,953 collected with **3 collection
  errors**; `test_bridge.py` → 2 failed / 37 passed; `test_agent_cards.py` → 1
  failed / 10 passed; security suite → 232 passed / 3 skipped; checkup → 57
  pass / 5 warn / 0 fail.
- **Engineering capability:** still generation+verification; no tools bound
  during generation, whole-file regeneration, requirement-id fallback in empty
  workspaces (F-01).
- **Unsafe defaults:** terminal execution inherits the full environment and is
  sandbox-optional; test execution bypasses the broker (F-03). The product
  bridge default is `workspace_session`, not `ask` (F-04).
- **Persistence/observability:** the checkpoint DB is hardcoded, import-time and
  unbounded (936.7 MB; F-05); `src/observability/` shadows
  `src/observability.py`, so turn receipts are dead (F-06).
- **FinOps/authorization:** RBAC is vacuous (F-07), cancellation under-counts
  spend and pricing provenance is asserted (F-08).

Findings F-01…F-15 are preserved with severity, status, source files, evidence,
impact and next action. Production readiness is still **not** claimed.

## 2026-11-12 — P1-A: test isolation repair (checkpoint/session storage)

**Status:** DONE-VERIFIED for the P1-A scope. F-05 is PARTIAL (retention/vacuum
and workspace placement remain open).

**Root cause.** `src/graphs/chat_graph.py` hardcoded
`~/.crusorai/sessions.db`, created the directory and opened the connection at
import, and ignored `CRUSORAI_HOME`/`CRUSORAI_SESSIONS_DB`/
`CRUSORAI_CHECKPOINT_HOME`. Separately, in-process bridge tests wrote
`crusor_sessions` rows to the real DB because conftest did not redirect the
durable session store. Both holes are closed.

**What changed.**

- `src/runtime/app_paths.py` — `session_db_path()` and
  `checkpoint_db_path()` centralise resolution. Checkpoint precedence:
  `CRUSORAI_CHECKPOINT_DB` > `CRUSORAI_CHECKPOINT_HOME` >
  `CRUSORAI_SESSIONS_DB`/`_PATH` > `CRUSORAI_HOME` > default.
- `src/graphs/chat_graph.py` — `_LazySqliteConnection` wraps `SqliteSaver`;
  importing the graph opens nothing; the first checkpoint operation creates the
  DB and applies WAL/busy_timeout/synchronous. `memory.setup()` no longer runs
  at import.
- `src/runtime/session_store.py` — uses the shared `session_db_path()`
  (behaviour unchanged).
- `src/runtime/app_paths.py` — `workspace_app_data_root()` honours
  `CRUSORAI_HOME`, so per-workspace orchestration/test-report directories also
  stay under the test home.
- `src/tests/conftest.py` — pins `CRUSORAI_HOME`, `CRUSORAI_SESSIONS_DB` and
  `CRUSORAI_CHECKPOINT_HOME` to a throwaway runtime root and clears
  `CRUSORAI_CHECKPOINT_DB`.
- `src/tests/test_checkpoint_isolation.py` — 15 regression tests: precedence,
  import laziness, real `SqliteSaver` tables, cross-process restart, fixture
  isolation, real-user-data immutability.

**Verification.**

| Check | Result |
|---|---|
| `pytest src/tests/test_checkpoint_isolation.py` | **15 passed**, 39.81 s, exit 0 |
| Core gate (20 modules + new module) | **366 passed, 2 skipped, 1 xfailed**, 193.28 s, exit 0 |
| Graph persistence/restart | **139 passed**, 59.40 s, exit 0 |
| Session store/search + phase 12.1 | **35 passed**, 9.20 s, exit 0 |
| Security containment | **232 passed, 3 skipped**, 21.34 s, exit 0 |
| Agent-core checkup | **57 pass / 5 warn / 0 fail**, exit 0 |
| Bridge sidecar | **37 passed, 2 known failures**, 157.60 s, exit 1 |
| `test_runtime_evidence_capture` sample | 3 pre-existing failures, 97 passed |

**Real application data (verified unchanged after P1-A/R2/R3).**

| File | Size (bytes) | mtime_ns | sha256 |
|---|---|---|---|
| `~/.crusorai/sessions.db` | 937,684,992 | 1794499990403343400 | `5fc06788a9ad9928dc5a127d4bb9fc0ec3b50706733722540e26df321bf4b4ec` |
| `~/.crusorai/sessions.db-wal` | 0 | 1794502143976032500 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `~/.crusorai/sessions.db-shm` | 32,768 | 1794503871329186200 | `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb` |
| `~/.crusorai/runtime_events.db` | 44,466,176 | 1794500418798410200 | `d6e879239e9a6772dfd55e8ceb2241e687f4e7bb5d6220054f46e3ed84bb1543` |
| `~/.crusorai/runtime_events.db-wal` | 725,152 | 1794500576503332000 | `df9f74873aa3db6aa612198ec6c53b2fdaf3aa3030a1f1ce1075eeeaf46b2e45` |
| `~/.crusorai/runtime_events.db-shm` | 32,768 | 1794504487985532100 | `67dea1a5af83ccf148aa47b395c9cdf8bc6acb4243c02cda64374dac32f41948` |
| `~/.crusorai/verification.db` | 835,584 | 1794500242548333800 | `719066a8ca60ff48c1b15270bdcd9d866d7829afdcd363c4ba32339c5c05acb3` |
| `verification.db-wal` / `-shm` | absent | — | — |
| `*.db-journal` (all three) | absent | — | — |

The isolated test DB is created under the per-session
`crusorai-test-runtime-*` temp root; subprocess tests also prove a checkpoint
survives a second process and is read back from that path.

**P1-A-R2 remediation (2026-11-12).** The independent review rejected P1-A for
two remaining real-DB leaks; both are fixed without reverting the lazy
checkpointer:

- `src/bridge/__main__.py::_prior_checkpoint_count` now defaults to the
  graph's captured `_CHECKPOINT_DB` when that module is already imported,
  otherwise `checkpoint_db_path()` (the graph's exact env contract); an explicit
  `db_path` is only a caller override. `session_create` therefore reports
  `prior_checkpoints` from the configured checkpoint DB, never the developer's
  home DB.
- `src/tests/test_otel_tracing.py::_drop_checkpoints` now resolves
  `chat_graph._CHECKPOINT_DB`, refuses the real home path, and uses
  `SqliteSaver.delete_thread()` on the graph's own saver (fallback SQL only
  against the isolated file). Stale "bound at import" comments removed.
- `src/tests/test_checkpoint_isolation.py` grew to **22 tests**: full SHA-256 +
  existence/size/mtime for all nine `.db`/`-wal`/`-shm` files and journals;
  invalid-path coverage (directory target, parent-is-file, nested parent,
  writable custom path, fail-closed without home fallback); a B-2 cleanup
  regression.
- `src/tests/test_prior_checkpoint_isolation.py` (new, **4 tests**) drives real
  bridge subprocesses: custom checkpoint DB wins over custom session DB,
  custom session DB works without a checkpoint override, `session_resume`
  stays isolated, and a missing override reports zero instead of falling back
  to a decoy home DB.

| R2 check | Result |
|---|---|
| `pytest src/tests/test_checkpoint_isolation.py` | **22 passed**, 56.50 s, exit 0 |
| `pytest src/tests/test_prior_checkpoint_isolation.py` | **4 passed**, 26.10 s, exit 0 |
| P1-A targeted 36-test receipt (now 43 with 7 new isolation tests) | **43 passed**, 102.62 s, exit 0 |
| Final R2 receipt (22 isolation + 4 B-1 + 11 plan + 1 workspace + 2 bridge + 7 session) | **47 passed**, 181.89 s, exit 0 |
| Persistence/restart subset (increment 2/3, invocation reconciliation, session store/search) | **72 passed**, 27.81 s, exit 0 |
| B-1 + B-2 + real-data before/after re-run | **6 passed**, 40.26 s, exit 0; no real DB/sidecar/workspace changes |
| Final 47-test real-data before/after | **no changes** to 9 main/sidecar files, 3 journal paths or 61 workspace directories |

Invalid checkpoint paths fail closed with no fallback: an existing directory
target raises `sqlite3.OperationalError`; a file used as a parent raises
`FileExistsError`/`NotADirectoryError`; a missing nested parent is created
lazily on first use. The full `test_otel_tracing.py` module was not executed in
R2; its corrected cleanup is covered by the new B-2 regression.

**P1-A-R3 URI correction (2026-11-12).** The final independent review rejected
P1-A on B-4: `_prior_checkpoint_count` built `f"file:{db}?mode=ro"`, so a legal
`#` truncated the path. With intended DB 2 rows and a decoy at the truncated
path 1 row, the bridge returned 1.

- `src/runtime/app_paths.py` adds `sqlite_readonly_uri(db_path)` =
  `Path(db_path).resolve().as_uri() + "?mode=ro"`. This keeps absolute path
  resolution, Windows/POSIX compatibility, read-only mode and the 2.0 s timeout,
  while encoding `#`, `?`, `%`, spaces and Unicode.
- `src/bridge/__main__.py::_prior_checkpoint_count` uses the helper; path
  precedence and the graph captured-path preference are unchanged.
- `src/tests/test_checkpoint_uri_isolation.py` (new, 7 tests) drives the real
  bridge for `#` + decoy, spaces, `%` and Unicode; asserts URI encoding for `?`
  and runs the actual `?` filename case on POSIX (skipped on Windows, which
  forbids `?` in filenames); proves read-only writes raise and the DB hash is
  unchanged.

| R3 check | Result |
|---|---|
| `pytest src/tests/test_checkpoint_uri_isolation.py` | **6 passed, 1 skipped**, 25.55 s, exit 0 |
| URI + prior-checkpoint + isolation suite | **32 passed, 1 skipped**, 109.47 s, exit 0 |
| `pytest src/tests/test_session_pipeline.py` | **7 passed**, 51.52 s, exit 0 |
| `pytest src/tests/test_otel_tracing.py` | **7 passed**, 8.96 s, exit 0 |
| B-4 repro (intended 2, pre-`#` decoy 1) | **2**; old code returned 1 |
| Read-only probe | `DELETE` → `OperationalError`; hash unchanged |
| Real DB/sidecars/workspaces | no changes across the verification run |

**Remaining limitations.** No VACUUM/prune/retention; the real `sessions.db` is
still 937 MB and 426 `code_index_*.db` files are ~1.88 GB. Workspace-specific
checkpoint placement was not introduced. `test_runtime_evidence_capture` has 3
pre-existing failures (two Windows mode-bit assertions and one echo
`runtime_degraded` expectation). Bridge frame/signature pins remain known red.


---

## 2026-11-12 (later) — Implementation start: reconciliation, T-06, T-17 (partial)

**Branch:** `wip/working-tree-2026-11-12` (cut from `docs/engineering-handoff-prd-001` @ `7e4bb7ad`)
**Reconciliation:** R1 `40b02500` · R2 `fc511e67` · R3 `2ec62a2c` · R4 `952dbd45`
**Tickets:** T-06 `823aa7cf` (+ corrective follow-up) · T-17 part 1 `19682792`

- Working-tree reconciliation R1–R4 is committed: 492 files across audit baseline, agent code + untracked
  siblings + tests, desktop contrib, and memory/evidence.
- **39 entries remain intentionally untracked:** 11 generated `req_*` modules (F-11 contamination, R5
  review-only) and 28 private-runtime directories. 1,220 Electron user-profile files were excluded from git
  by policy; all remain preserved in the R0 backup at `C:\CrusorBackups\PulseAIRepo\2026-11-12\R0`.
- **T-06 complete.** `src/observability.py` moved to `src/observability/receipts.py` (git mv) and re-exported
  from the package. `from src.observability import record_turn_receipt` now resolves; F-06 is fixed at the
  import layer. Receipt *emission* is T-07 and is not done.
- **T-17 part 1 complete.** `deduplicate_streaming_usage` implemented in `src/llm/factory.py`; the two
  modules that failed collection now pass 22/22. Full collection: **5,012 tests, 0 errors** (was 4,986 with 3).
- **Not done:** T-01…T-05, T-07…T-16, T-18, T-19…T-21. T-18 (CI gate) is the next unblocked ticket.
- No merge to `main`. No public release. No provider spend beyond one 2-token probe earlier.



---

## 2026-11-12 (T-18) — CI truth gate: **PARTIAL**

**Commits:** `caeca301` (rename + parity-test corrective) · `1ddb6143` (workflow enforcement)

- `ci/agent-core.yml` now lives at `.github/workflows/agent-core.yml`. The two `--ignore` flags and the
  non-blocking `desktop-panel-parity` job are gone; the blocking job runs
  `bash scripts/run_tests.sh src/tests` on py3.11. Nothing in the workflow can conceal a failure.
- **Red-on-red: PROVEN.** A temporary failing test produced `1 failed, 4 passed`, exit code **1**; the file
  was removed and `git status` for that path is empty.
- **Green-on-green: NOT PROVEN.** Two blockers, both real:
  1. `test_copilot_parity_permission_diff.py::test_approval_dock_renders_inline_diff_and_warning` fails:
     it requires `crusorai-approval-diff-preview` / `-header` in the renderer and CSS; neither exists. The
     approval dock now renders stats + a "Review change" button that opens the native diff editor. This is a
     **UI contract decision**, not test drift: either the inline preview is restored or the contract is
     updated. Not decided unilaterally.
  2. `test_degraded_memory.py` hangs >120 s when run alone, with both a fresh and the real HOME. It blocks any
     full-suite run, locally and in CI.
- The background full-suite run reached 17% before the hang: the approval-dock failure above, everything else
  passing to that point. Local `bash` is WSL without a distro, so the runner environment was replicated in
  PowerShell — this is local Windows evidence, not a GitHub-hosted run.
- No push (not authorised). `origin/main` unchanged.



---

## 2026-11-12 (T-18 continued) — Option B UI restored, hang fixed, **still PARTIAL**

**Commit:** `c2a36e32`

- **Inline diff preview restored** in the approval dock (`crusorai-approval-diff-preview` /
  `-header`), rendering the real proposed diff through the existing `diffPreview` renderer. Display-only: no
  handler, no approval side effect; "Review change" still opens the native multi-diff. Evidence:
  `test_copilot_parity_permission_diff` **6/6 passed**.
- **`test_degraded_memory` hang fixed.** Faulthandler showed `finalize_node → _verification_receipt_status →
  audit_workspace` reading every source file because the test passed `workspace="."`. The test now uses
  `tmp_path` with one small file — same code path, bounded input. Evidence: **3 passed in 7.17 s** (previously
  hung >120 s).
- **Full authoritative run: 97% in ~40 minutes, then killed by the harness cap.** Not green. Remaining
  failures are pre-existing and unrelated to CI:
  - `test_unknown_tool_validation.py::test_hermes_dialect_name_is_repaired_and_executed` (1)
  - `test_user_interest.py` (6) — task-manager interest/mode assertions returning `''`
  These need their own ticket; they are product behaviour, not gate wiring.
- **Runtime risk:** the suite exceeded 40 minutes on this host. The workflow's `timeout-minutes: 30` may be too
  low for Linux CI as well; must be measured on a real runner before claiming green.
- Product requirement for the full change-review experience recorded in
  `pm/09-AGENTIC-CHANGE-REVIEW-REQUIREMENT.md` (CR-1…CR-9); CR-5…CR-8 explicitly out of T-18.



---

## 2026-11-12 (T-22) — seven failures triaged and fixed

**Commit:** `242decbb` · **Tests:** 73 passed, 7 skipped across affected modules

- **Origin proven, not assumed:** all 7 tests also fail in a clean worktree at `7e4bb7ad` (before R2).
  R2 did not cause them.
- **Root cause 1 (6 failures, product regression):** `_turn_scoped_resets()` returned
  `task_action=""`, `task_status`, `task_completed`, and every `task_manager_node` branch expanded it
  **after** setting the real values. The reset overwrote them, so `after_task_manager` always saw `""` and
  `plan_cancelled`, `approval_without_plan`, `execute_approved_plan`, `revise_plan` were unreachable.
  Fixed by removing the three keys from the reset and giving three branches explicit values.
- **Root cause 2 (2 failures, one security-relevant):** `SafeToolNode` classified names for the mutation
  boundary **before** `_repair_tool_call_names`. The alias `run terminal` therefore bypassed
  `_GRAPH_MUTATION_BLOCKED` (raw name not in the set) and reached a **confirmation prompt** instead of being
  denied. Names are now canonicalized first; both alias and canonical names are in the blocked set, so the
  reorder is fail-closed. The denial keeps the repaired assistant message in history.
- **Tests updated only where the old assertion encoded the weaker behaviour**, each with a comment naming the
  reason; a regression guard `test_turn_scoped_resets_do_not_clobber_task_action` was added.
- **Linux CI qualification: NOT PERFORMED.** No WSL distribution and no Docker on this host. The 30-minute
  workflow timeout is unvalidated for Linux; the Windows run must not be cited as Linux evidence.
- **T-18 remains PARTIAL.** Full-suite green is being re-run after these fixes.

