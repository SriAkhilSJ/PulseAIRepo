# CrusorAI - Phase Tracker

**Snapshot:** 2026-11-12 (`feat/prompt-cache-stabilization`, HEAD `fb5bd528`)
**Updated:** 2026-11-12 — P1-A checkpoint/session test isolation repaired (§8);
P1-A-R2 closed the independent-review B-1/B-2 leaks (§8a); P1-A-R3 fixed the
B-4 SQLite URI path encoding and awaits acceptance (§8b); P1-B remains gated on
review.
**Purpose:** one place to see what was attempted, what was verified, and what is
still open.

---

## 1. Status legend

| Status | Meaning |
|---|---|
| DONE-VERIFIED | Acceptance criteria met, with command/CI evidence and a commit. |
| DONE-DOCUMENTED | The phase record says complete, but this audit did not re-run it. |
| PARTIAL | Some criteria met; gaps are named. |
| FAILED | A criterion failed; evidence is preserved. |
| NOT STARTED | No work authorized or performed. |
| GATE | Waiting on review or a decision. |

## 2. Production hardening phases (current line)

| Phase | Goal | Start | End commits | Status | Evidence |
|---|---|---|---|---|---|
| 0 | Baseline, architecture map, blockers, security findings | `27b17f10` | `a6455e25` | DONE-VERIFIED | `docs/production/phase-0/` (5 docs) |
| 1 | Remove import-time ACL/security payloads; contain source | `a6455e25` | `b95b1750`, `7a714e24` | DONE-VERIFIED | `docs/production/phase-1/PHASE_1_SECURITY_CONTAINMENT.md` |
| 1.1 | Guard hardening: import side effects, process spawn, writes | `7a714e24` | `bb94f740`, `2204e320` | DONE-VERIFIED | `PHASE_1_1_GUARD_HARDENING.md` |
| 1.2 | Filesystem guard: CWD, mkdir, unlink, truncate, fdopen | `2204e320` | `c32582db`, `38f06d8f` | DONE-VERIFIED | `PHASE_1_2_FILESYSTEM_GUARD.md` |
| 1.3 | Strict AppContainer AST allowlist and mutation checks | `38f06d8f` | `c9b909d2`, `3c954480` | DONE-VERIFIED | `PHASE_1_3_FINAL_GUARD_HARDENING.md` |
| 1.3.1 | Reject alternate AST mutations, fake receivers, bad order; cross-platform CI | `3c954480` | `4a9e2ade`, `3450c790`, `de4f8c0d`, `b974a5a1`, `b72d04c5` | DONE-VERIFIED | `PHASE_1_3_1_AST_ALLOWLIST_HARDENING.md`; CI `42560871135` |
| 1.3.2 | Exact structural whitelist; reject aliases, rebinding, destructuring, walrus, shadowing, monkeypatching; full API contract | `b72d04c5` | `6c55f350`, `385925bf` | DONE-VERIFIED | `PHASE_1_3_2_AST_BINDING_HARDENING.md`; CI `42563557065` |
| 1.3.3 | Validate structure class bodies and module DLL initialization; reject class-body execution and aliases | `385925bf` | `1264d990`, `ba8c0c8b` | DONE-VERIFIED | `PHASE_1_3_3_MODULE_STRUCTURE.md`; CI `42571837431` |
| 1.3.4 | Pin imports, module declarations, helper and manager method manifests, and structure completeness | `ba8c0c8b` | `ac52ad26`, `00eabb3d` | DONE-VERIFIED | `PHASE_1_3_4_MODULE_DECLARATION_HARDENING.md`; CI `42574847574` |
| 1.3.4R | Pin the ACL helper body; require the grant function to be its direct nested child | `00eabb3d` | `3cc3c374`, `85192f87` | DONE-VERIFIED | Same document, section 13; CI `42583627343` |
| 1.3.4R2 | Count async grant declarations; require the sole grant to be synchronous and helper-owned | `85192f87` | `90a2d2d1`, `831e6085` | DONE-VERIFIED | Same document, section 14; CI `42611296402` |
| 1.4 | Windows runtime qualification: ACL architecture, AppContainer/Job Object runtime, network, Python 3.11/3.14 | `831e6085` | `0bf14d9c`, `71479fb6` | **DONE-VERIFIED / QUALIFIED** | `PHASE_1_4_WINDOWS_RUNTIME_QUALIFICATION.md`; runs `42654054565`, `42654054623` |
| 1.4R | Bounded output capture and runtime test integrity | `7e0b83ff` | `3cc8c780`, `3072e3cf` | DONE-VERIFIED | Same document, section 14; CI `42646010564` |
| 1.4C | Fail-closed AppContainer startup, no silent downgrade, capability reporting, 3.11/3.14 runtime CI | `71479fb6` | `5a51897c`, `e9b6ee02` | DONE-VERIFIED / QUALIFIED | Same document, section 16; CI `42661726444`, `42661726660` |
| 2R1 | Desktop qualification r1 | `e9b6ee02` | `165dc16f` | DESKTOP_PARTIAL | `bench-results/phase-2-desktop-qualification-r1` |
| 2R2 | Desktop remediation r2 (tests, dock, startup cancel, evidence warning) | `165dc16f` | `73c4d0a7`, `638d4151` | DESKTOP_PARTIAL | `bench-results/phase-2-desktop-qualification-r2` |
| 3.1 | Orchestrator human-approval integration | `70281b22` | `efda16c9`, `b5277512` | PASS (bounded) | `bench-results/phase-3-approval-integration` |
| 3.2 | Planner/contract closure (Phase 11.6 baseline) | `b5277512` | `7879e066`, `604605b2` | PASS (bounded) | `bench-results/phase-3.2-planner-contract-closure` |
| 3.3-1 | Canonical LangGraph owner + engineering delegation + B-DESK-001 | `604605b2` | `5197937a` | PASS (bounded) | `bench-results/phase-3.3-canonical-runtime/EVIDENCE.md` |
| 3.3-2 | One context/model/tool/approval/mutation boundary | `604605b2` | `5197937a` | PASS (bounded) | `.../INCREMENT2_EVIDENCE.md` |
| 3.3-3 | Canonical receipt, persistence, FinOps, B-DESK-006, route retirement | `604605b2` | `5197937a` | PASS (runtime gates); Electron E2E later passed (3.3-D) | `.../INCREMENT3_EVIDENCE.md` |
| 3.3-D | Desktop integration repair: chat routing singleton, panel hash, Electron UI E2E | `604605b2` | `f3528098` | PASS (provider-free Electron UI) | `.../DESKTOP_REPAIR_EVIDENCE.md` |
| 3.3-Q | Product qualification: scope fidelity + first live Velona Electron task | `604605b2` | uncommitted evidence | PASS (n=1 live smoke); not production-ready | `.../QUALIFICATION_REPORT.md` |
| 3.3-P1 | Live engineering progress: orchestrator `on_progress` → activity/plan cards → bridge → journal | `fb5bd528` | uncommitted working tree | PASS (provider-free Electron 16/16) | `CRUSOR_PROGRESS_INTEGRATION_REPORT.md`; `.../logs/electron-progress/` |
| 3.3-P2 | Engineering DAG completion: real node settlement, blocked back-fill, journal outcomes | `fb5bd528` | uncommitted working tree | PASS (deterministic + Electron) | `CRUSOR_PLAN_COMPLETION_REPORT.md` |
| 3.3-P3 | Plan outcome semantics: `blocked`/`cancelled` states on the existing plan card | `fb5bd528` | uncommitted working tree | PASS (provider-free Electron 21/21) | `CRUSOR_PLAN_OUTCOME_SEMANTICS_REPORT.md` |
| 3.3-MT | Multi-turn engineering isolation (per-turn state/context/journal storage) | `fb5bd528` | uncommitted working tree | FIXED | `docs/CURRENT_STATE.md` 2026-11-11 section |
| 3.3-T1 | Per-turn Agentic card ownership: persistence, hydration and reload/restart restoration | `fb5bd528` | uncommitted working tree | PASS (provider-free Electron 32/32) | `CRUSOR_TURN_CARD_RESTORATION_REPORT.md`; `.../logs/electron-progress/07-restarted.png` |
| 3.3-T2 | Clean chronological Agentic timeline; internal-only verification/delivery/cost cards hidden | `fb5bd528` | uncommitted working tree | PASS (provider-free Electron 40/40) | `CRUSOR_AGENTIC_TIMELINE_REPORT.md`; `.../logs/electron-progress/` |

### Phase 1.3.1 acceptance record

| Criterion | Result | Evidence |
|---|---|---|
| Reject `AnnAssign`, `AugAssign`, `Delete`, `setattr`, subscript, nested trustee, `p_new_dacl` mutation | Met | 17 negative tests pass |
| Validate exact targets, not names | Met | `_security_call_lines` exact-path table |
| Validate exact receivers | Met | `_advapi32.*`, `_kernel32.*`, `ctypes.*` tests |
| Validate exact arguments, counts, order, allocation/free flow | Met | Ordering/allocation tests; exact call-set rule |
| Require `LocalFree(p_new_dacl)` after `SetSecurityInfo` inside `if ret2 == 0:` | Met | AST rule + tests |
| Keep the documented implementation accepted | Met | `test_documented_grant_remains_accepted` |
| Cross-platform CI on Ubuntu, Windows, macOS | Met | Run `42560871135`, 3/3 jobs success |
| Verification order 1-11 with exit codes | Met | `PHASE_1_3_1_AST_ALLOWLIST_HARDENING.md` section 5 |
| No product behaviour change | Met | Only test, workflow, and docs changed |
| Documentation | Met | New phase document |

Test totals at close: 93 tests collected; 90 passed / 3 skipped locally; CI 89/4
(Ubuntu), 87/6 (Windows), 89/4 (macOS).

### Phase 1.3.1 CI history

| Run | Commit | Result | Notes |
|---|---|---|---|
| `42558699115` | `4a9e2ade` | FAILED | POSIX `ctypes.WinDLL` patch error; Windows 3.11 `platform.system()` spawn. |
| `42559738964` | `3450c790` | SUCCESS | Portability fixes; 91-test suite. |
| `42560871135` | `de4f8c0d` | SUCCESS | Exact-call hardening; 93-test suite. Final evidence. |

### Phase 1.3.2 acceptance record

| Criterion | Result | Evidence |
|---|---|---|
| Reject trustee/`ea`/receiver/`ctypes`/`p_new_dacl` aliases | Met | 6 parametrized alias tests |
| Reject receiver and constructor rebinding | Met | 11 rebinding/shadowing tests |
| Reject constant rebinding | Met | 8 protected-name tests + module tests |
| Reject tuple/list destructuring | Met | 4 tests |
| Reject named expressions / walrus | Met | 4 tests |
| Reject loop and context-manager targets | Met | 2 tests |
| Reject import and nested function/class shadowing | Met | 6 tests |
| Reject module and attribute monkeypatching | Met | 11 tests |
| Validate all eight `GetSecurityInfo` arguments | Met | 8 parametrized tests |
| Validate both `LocalFree` calls and arguments | Met | 2 tests + exact body |
| Validate allocation, order, branches and return | Met | 8 tests + exact body |
| Keep the documented implementation accepted | Met | positive control + real sandbox |
| Cross-platform CI | Met | Run `42563557065`, 3/3 jobs success |
| No product behaviour change | Met | Only test and docs changed |

Test totals at close: 161 collected; 158 passed / 3 skipped locally; CI 157/4
(Ubuntu), 155/6 (Windows), 157/4 (macOS).

### Phase 1.3.2 CI history

| Run | Commit | Result | Notes |
|---|---|---|---|
| `42563557065` | `6c55f350` | SUCCESS | 161-test suite; 3/3 jobs green on Python 3.14.10. |

### Phase 1.3.3 acceptance record

| Criterion | Result | Evidence |
|---|---|---|
| Exact `EXPLICIT_ACCESS_W` body and `_fields_` | Met | 8 structure tests |
| Exact `TRUSTEE_W` body and `_fields_` | Met | reordered-trustee test |
| Reject executable structure class bodies | Met | 6 class-body tests |
| Reject extra module-level classes | Met | 3 tests |
| Validate every DLL initialization expression | Met | 10 tests |
| Reject module/sibling aliases | Met | 4 tests |
| Reject executable module assignments | Met | 3 tests |
| Genuine implementation remains accepted | Met | positive control + real sandbox |
| Cross-platform CI | Met | Run `42571837431`, 3/3 jobs success |
| No product behaviour change | Met | Only test and docs changed |

Test totals at close: 192 collected; 189 passed / 3 skipped locally; CI 188/4
(Ubuntu), 186/6 (Windows), 188/4 (macOS).

### Phase 1.3.3 CI history

| Run | Commit | Result | Notes |
|---|---|---|---|
| `42571837431` | `1264d990` | SUCCESS | 192-test suite; 3/3 jobs green on Python 3.14.10. |

### Phase 1.3.4 acceptance record

| Criterion | Result | Evidence |
|---|---|---|
| Exact import manifest | Met | 7 import tests |
| Exact module declaration count/order/identity | Met | 62-entry manifest; 7 module tests |
| Exact helper declaration | Met | 6 function tests |
| Exact manager method manifest | Met | 8 manager tests |
| Full eleven-structure completeness | Met | 8 structure tests |
| Genuine implementation remains accepted | Met | full-module positive control + real sandbox |
| Cross-platform CI | Met | Run `42574847574`, 3/3 jobs success |
| No product behaviour change | Met | Only test and docs changed |

Test totals at close: 223 collected; 220 passed / 3 skipped locally; CI 219/4
(Ubuntu), 217/6 (Windows), 219/4 (macOS).

### Phase 1.3.4 CI history

| Run | Commit | Result | Notes |
|---|---|---|---|
| `42574847574` | `ac52ad26` | SUCCESS | 223-test suite; 3/3 jobs green on Python 3.14.10. |

### Phase 1.3.4R acceptance record

| Criterion | Result | Evidence |
|---|---|---|
| Exact 11-statement helper body | Met | 11 helper ownership tests |
| Exact early returns and dependency guard | Met | helper body checks |
| Exact handle acquisition and grant calls | Met | helper body checks |
| Exactly one grant, direct child of helper | Met | ownership check |
| Relocation into manager/other function rejected | Met | 2 tests |
| Duplicate/missing grant rejected | Met | 2 tests |
| Genuine implementation remains accepted | Met | full-module positive control |
| No product behaviour change | Met | Only test and docs changed |

Test totals at close: 234 collected; 231 passed / 3 skipped locally; CI 230/4
(Ubuntu), 228/6 (Windows), 230/4 (macOS).

### Phase 1.3.4R CI history

| Run | Commit | Result | Notes |
|---|---|---|---|
| `42583627343` | `3cc3c374` | SUCCESS | 234-test suite; 3/3 jobs green on Python 3.14.10. |

### Phase 1.3.4R2 acceptance record

| Criterion | Result | Evidence |
|---|---|---|
| Count sync and async grant declarations | Met | async regression test |
| Require exactly one grant | Met | uniqueness search |
| Require the sole grant to be synchronous | Met | `isinstance` check |
| Require helper ownership | Met | direct-child check |
| Reject async grant in manager method | Met | AST-only regression |
| Positive control still passes | Met | full-module positive test |

Test totals at close: 235 collected; 232 passed / 3 skipped locally; CI 231/4
(Ubuntu), 229/6 (Windows), 231/4 (macOS).

### Phase 1.3.4R2 CI history

| Run | Commit | Result | Notes |
|---|---|---|---|
| `42611296402` | `90a2d2d1` | SUCCESS | 235-test suite; 3/3 jobs green on Python 3.14.10. |

### Phase 1.4 acceptance record

| Criterion | Result | Evidence |
|---|---|---|
| W1 ACL state inspected | PASS | WinSta0/Default SDDL recorded |
| W2 No unapproved machine ACL change | PASS | read-only probe; helper skipped |
| W3 AppContainer runtime | PASS (bounded) | token, integrity, job, DACL deny; ACL-grant branch NOT RUN |
| W4 Job Object limits/cleanup | PASS | active-process denial, memory denial, termination |
| W5 Filesystem/environment | PASS (caveat) | DACL deny, secret stripping; TMP mismatch recorded |
| W6 Python 3.11/3.14 | PARTIAL | 3.14 clean; 3.11 full import fails |
| W7 Existing security suite | PASS on 3.14 | 232 passed, 3 skipped |
| W8 Limitations disclosed | PASS | Phase 1.4 document |

Runtime tests: 8/8 with AppContainer opt-in; 6 passed / 2 skipped without it.
Test totals: security suite 235 collected; 232 passed / 3 skipped locally; CI
231/4 (Ubuntu), 229/6 (Windows), 231/4 (macOS).

### Phase 1.4 CI history

| Run | Commit | Result | Notes |
|---|---|---|---|
| `42618095589` | `838857ee` | SUCCESS | 235-test security suite; 3/3 jobs green on Python 3.14.10. |

### Phase 1.4 final acceptance record

| Criterion | Result | Evidence |
|---|---|---|
| ACL architecture safely qualified | PASS | automatic ACL write removed; helper forbidden in runtime tests |
| AppContainer network isolation | PASS | native control succeeds; AppContainer timeout; no listener accept |
| Python 3.11 and 3.14 guarded import | PASS | both pass full security suite and guarded import |
| TMP contract | PASS | package-local `AC\Temp` asserted |
| Memory enforcement bounded | PASS (bounded) | 64 MB limit denies 128 MB; peak accounting limitation retained |
| Existing security tests | PASS | 232 passed, 3 skipped on 3.11 and 3.14 |
| CI exact commit | PASS | security `42654054565`; Windows runtime `42654054623` |
| Limitations disclosed | PASS | Phase 1.4 section 15 |

Final CI: security Ubuntu 231/4, Windows 229/6, macOS 231/4; Windows runtime
21/21 in 27.93 s on Python 3.14.10.

### Phase 1.4 corrective acceptance record

| Criterion | Result | Evidence |
|---|---|---|
| C1 AppContainer retention bounded | PASS | 1 MiB per pipe, 64 KiB chunks |
| C2 AppContainer temp storage bounded | PASS | no temp files; pipes only |
| C3 Fallback enormous lines bounded | PASS | binary fixed-chunk reader |
| C4 Independent stream limits | PASS | separate stdout/stderr budgets |
| C5 DACL denial proof | PASS | baseline start + exit 1 + Access denied |
| C6 Process-limit denial | PASS | WinError 1816 asserted |
| C7 Memory evidence classified | PASS | 512 MB control vs 64 MB MemoryError |
| C8 Timeout/cancellation/cleanup | PASS | output timeout, fallback + AC cancellation |
| C9 Security suite | PASS | 232 passed, 3 skipped |
| C10 Limitations disclosed | PASS | Phase 1.4 limitations retained |

Runtime harness: 21/21 with AppContainer opt-in. Phase 1.4 is now qualified for
the declared Windows 11 + Python 3.11/3.14 contract.

### Phase 1.4 corrective CI history

| Run | Commit | Result | Notes |
|---|---|---|---|
| `42646010564` | `3cc8c780` | SUCCESS | Security suite 235 collected; 3/3 jobs green on Python 3.14.10. |

### Phase 1.4 fail-closed acceptance record

| Criterion | Result | Evidence |
|---|---|---|
| Job assignment failure prevents resume | PASS | failure-injection test |
| Resume failure terminates/cleans up | PASS | failure-injection test |
| Security-capability failure prevents create | PASS | failure-injection test |
| Provisioning failure fails closed by default | PASS | provisioning test |
| Degraded fallback explicit and accurately reported | PASS | opt-in capability test |
| AppContainer/Job capabilities differ correctly | PASS | capability test |
| Python 3.11/3.14 runtime CI | PASS | 27/27 each |
| Existing security suite | PASS | 232 passed, 3 skipped |

CI: security `42661726444` (Ubuntu 231/4, Windows 229/6, macOS 231/4);
Windows runtime `42661726660` (3.11 job `129314746236` 27/27; 3.14 job
`129314745800` 27/27).

## 3. Historical phases (recorded, not re-verified)

These are summarized from root `PHASE_*.md` documents. Status is what the phase
record claims; this audit did not re-run them.

| Phase | Theme | Recorded result | Status here |
|---|---|---|---|
| 9.3.4.1 | Runtime acceptance, security verification | Completed with evidence | DONE-DOCUMENTED |
| 9.3.4.2 | Implementation changelog, performance, workflow | Completed with evidence | DONE-DOCUMENTED |
| 9.3.4.3 | Final closure, marketplace, invariant 7 | Completed | DONE-DOCUMENTED |
| 9.3.5 | Benchmark reconciliation, integrity | Completed | DONE-DOCUMENTED |
| 9.4 | Execution broker and OS sandbox | Implemented; adversarial evidence | DONE-DOCUMENTED |
| 9.4.1-9.4.3 | Filesystem/network/identity isolation | Security verdict recorded | DONE-DOCUMENTED |
| 9.5 | MCP and browser security | Security verdict recorded | DONE-DOCUMENTED |
| 9.6 | Performance and IPC reliability | Completed | DONE-DOCUMENTED |
| 9.7 | FinOps, budgets, routing | Completed | DONE-DOCUMENTED |
| 10.0 | Identity, RBAC, audit logging | Implemented; enforcement gap remains (B-002) | PARTIAL |
| 11.0-11.8 | Engineering intelligence, change impact, verification, production readiness | Implemented; integration gaps recorded | PARTIAL |
| 12.0.1 | Remaining limitations audit | Catalogued | DONE-DOCUMENTED |
| 12.1 | Desktop execution architecture and integration | Recorded | DONE-DOCUMENTED |
| 12.1.1 | End-to-end qualification | Recorded | DONE-DOCUMENTED |
| 12.1.2 | AppContainer, Electron runtime, live model | Recorded | DONE-DOCUMENTED |
| 12.1.3 | Final product qualification | `PRODUCT_QUALIFIED_WITH_LIMITATIONS`; GUI NOT VERIFIED; provider DETERMINISTIC_PROVIDER_ONLY; 395/395 subset | PARTIAL |

### 3.3-P acceptance record (2026-11-11)

| Criterion | Result | Evidence |
|---|---|---|
| Orchestrator progress reaches the existing Agentic cards | Met | `test_engineering_progress_events.py` 19; Electron live stage transitions |
| Completion recorded only after real executor success | Met | `test_plan_completion.py` 11; `test_plan_outcome_semantics.py` 16 |
| Failed / blocked / cancelled are distinct states | Met | Real scheduler + orchestrator tests; Electron plan card |
| Cancellation before, during and at an approval wait | Met | Scheduler predicate + `ApprovalDenied` path tests |
| No duplicate completion on retry | Met | Two-run idempotency tests |
| Journal replay keeps every status | Met | Bridge/journal projection test; Electron reload (6 steps, 4 states) |
| Backward compatibility with four-status cards | Met | Legacy card + legacy view + TS contract tests |
| Provider-free Electron acceptance | Met | `accept-crusorai-progress.mjs` PASS 21/21, `rows=0` |
| Multi-turn engineering session | Fixed | Per-turn storage; invalid `COMPLETED → UNDERSTANDING` eliminated |
| Frontend compile + card contract | Met | `typecheck-client` exit 0; emitter 43 files; `test_crusorai_cards.mjs` ok |

Known failures left untouched: `test_agent_cards.py::test_all_required_card_types_are_declared`
(working-tree extra Python card types) and two `test_bridge.py` assertions
(echo frame window, autotitler signature).

### 3.3-T1 acceptance record (2026-11-11)

| Criterion | Result | Evidence |
|---|---|---|
| Cards keyed by `(session, turn, card id)` | Met | `CrusorCardStore`; Node contract tests |
| Turns never overwrite each other / identical ids safe | Met | Python association 13; Node store; Electron |
| Session switch clears card state | Met | `resetSessionState`; source contract test |
| Duplicate replay cannot duplicate cards | Met | Identity-keyed dedupe + idempotent restore |
| Historical messages carry turn identity | Met | Journal `turn.started` request-hash stamping |
| Reload restores each turn's cards | Met | Electron 3 turns, `data-turn-id` sections |
| Repeated hydration is idempotent | Met | Electron second reload identical |
| Full application restart restores all turns | Met | Electron `07-restarted.png`, 32/32 checks |
| Legacy cards remain readable | Met | Hash → ordinal → single-turn fallback; ambiguous warned |
| No paid provider call | Met | `rows=0` |

### 3.3-T2 acceptance record (2026-11-11)

| Criterion | Result | Evidence |
|---|---|---|
| Verification/delivery/cost cards are not user-facing | Met | DOM counts 0 live and after reload; journal still holds all three |
| Verification execution and outcomes preserved | Met | `test_phase_12_1_end_to_end_acceptance` 5 passed; journal `verified` card |
| FinOps preserved internally | Met | cost cards journaled; `test_invocation_reconciliation` 13 passed |
| Activity/plan/tool/file/approval/test UI still renders | Met | Electron cards + existing tool rows; Node policy tests |
| Chronological timeline | Met | live order `activity → plan → file → approval → text`; final answer last |
| Per-turn ownership / reload / restart | Met | 3 turns, distinct ids, repeated hydration, full restart |
| No duplicate typed tool activity | Met | typed tool card suppressed when its tool row exists |
| No paid provider call | Met | `rows=0` |

## 4. Open gates

| Gate | Blocks | Owner action |
|---|---|---|
| Security defaults | Any product safety claim | Default `ask`; broker/sandbox + scrubbed env for all process creation (F-03/F-04). |
| Engineering capability | Any "agentic engineering" claim | Bind tools during generation; targeted edits; reject requirement-id targets (F-01). |
| Full TurnReceipt rendering / headed qualification | Full desktop close | Provider-free Agent pane flow passes; render every receipt field and run broader headed acceptance. |
| Working-tree disposition | Any clean baseline claim | **272 entries** (262 at audit; 84 modified, 188 untracked, 0 staged) include runtime + desktop + qualification + apps + generated modules + memory layer + P1-A/R2/R3 changes; decide commit vs retain. |
| Full-suite baseline | Release confidence | Collection fails (3 errors); fix imports/pins, run the full suite, classify every failure (F-02). |
| Live acceptance | Product acceptance | Authorized headed run after P-0/P-0b; do not reuse historical reservation. |

## 5. Phase hygiene checklist

Use this for every new phase:

- [ ] Starting HEAD recorded and matched to origin.
- [ ] Scope and explicit non-actions written before edits.
- [ ] Pre-existing dirty entries counted and preserved.
- [ ] Tests selected before implementation; negative tests required for guards.
- [ ] Local commands and exit codes captured.
- [ ] CI jobs, platforms, run IDs, and conclusions captured.
- [ ] Product behaviour change stated (or explicitly none).
- [ ] Limitations updated, not hidden.
- [ ] Final report lists start/implementation/final SHAs.
- [ ] `CURRENT_STATE.md` and `LATEST_HANDOFF.md` updated.

## 6. Backend qualification — 2026-11-12 (terminal, real provider)

| Aspect | Status | Evidence |
|---|---|---|
| Real provider path (auth, dispatch, usage, FinOps settle, latency, turn ids) | DONE-VERIFIED | 5 settled calls, ₹0.1815, `CRUSOR_AGENT_CORE_TERMINAL_QUALIFICATION.md` |
| Ledger `latency_ms` instrumentation | DONE-VERIFIED (fixed) | rows: 3242 / 1737 / 16381 / 26905 / 9709 ms |
| Test A — basic implementation (`divide()`) | FAILED | malformed code fence rejected; no recovery; 0 files |
| Test B — multi-file engineering (`clamp()`) | FAILED | created `src/req_001_module.py`, `src/req_003_module.py`, `tests/test_req_001_module.py`; 0 real files changed |
| Test C — diagnosis and repair | BLOCKED | failing tests never executed; regression intact (4 failing) |
| Tool execution on the engineering path | NOT STARTED | no `bind_tools` / tool loop in `orchestrator.py` or `model_adapter.py` |
| Phase 2A — workspace discovery before planning | **DONE-VERIFIED (deterministic)** | 9 tests A–H; `CRUSOR_PHASE_2A_WORKSPACE_DISCOVERY.md` |
| Phase 2B — targeted edits | NOT STARTED | whole-file regeneration still in place |
| Phase 2D — outside-workspace access with permission | **DONE-VERIFIED (reads + writes)** | `test_outside_workspace_access.py` 17 passed; `CRUSOR_PHASE_2D_OUTSIDE_WORKSPACE_ACCESS.md` §8 |
| Phase 2D-2 — outside-workspace writes | **DONE-VERIFIED (create/modify)** | broker grant + diff token; delete/rename/copy still workspace-only (B-CORE-007) |
| Phase 2C — test-diagnose-repair | NOT STARTED | existing repair loop unchanged; B-CORE-006 |

## 7. Memory reconciliation — 2026-11-12 (documentation-only)

| Item | Status | Evidence |
|---|---|---|
| Initial engineering audit | COMPLETE | `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` (F-01…F-15) |
| Canonical memory corrected to HEAD `fb5bd528` | COMPLETE | AGENTS + 7 docs updated; no phase executed |
| Dirty-tree count | **272 after P1-A-R3** (271 after R2; 269 after P1-A; 262 at audit; 84 modified, 188 untracked, 0 staged, 0 deletions) | `git status --porcelain` before/after |
| Broker status | FIXED at HEAD, not uncommitted | `src/tools/file_tools.py:508-538`; `git diff HEAD` empty |
| Agent Runtime increments | COMMITTED at `5197937a` | `git log -- src/runtime/turn_receipt.py` |
| Test baseline | 4,953 collected / 3 errors; 3 known failures | section 6; F-02 |
| Production readiness | **NOT CLAIMED** | audit findings F-01…F-11 open |

No source, dependency, git or provider change. Findings remain as recorded in
the audit register; do not mark an open finding closed without a command,
result and exit code.

## 8. P1-A — test isolation repair (2026-11-12, verified)

| Item | Status | Evidence |
|---|---|---|
| Checkpoint path resolves `CRUSORAI_CHECKPOINT_DB` / `_HOME` / `CRUSORAI_SESSIONS_DB` / `CRUSORAI_HOME` | DONE-VERIFIED | `src/runtime/app_paths.py`; 15 tests |
| Import opens no checkpoint DB | DONE-VERIFIED | subprocess import test; `memory.is_setup is False` |
| Lazy first-use connection | DONE-VERIFIED | `_LazySqliteConnection`; saver table/read-back test |
| Tests isolate home/sessions/checkpoint | DONE-VERIFIED | `src/tests/conftest.py`; fixture test |
| Actual checkpoint persistence retained | DONE-VERIFIED | `SqliteSaver.setup()` tables; cross-process restart test |
| Real user DB unchanged | DONE-VERIFIED | `sessions.db` sha256 `5fc06788…`, size 937,684,992; runtime/verification unchanged |
| Retention/vacuum/workspace placement | **OPEN (F-05 remains PARTIAL)** | no prune policy; 937 MB DB, 426 index DBs |
| P1-B collection/test baseline | NOT STARTED (review gate) | P1 report; F-02 |

Verification: 15 isolation tests pass (39.81 s); core gate 366 passed / 2
skipped / 1 xfailed (193.28 s); graph/restart 139 passed; session/acceptance 35
passed; security 232/3; checkup 57/5/0. Bridge 37 passed / 2 known failures;
`test_runtime_evidence_capture` retains 3 pre-existing failures. HEAD
unchanged; no commit.

## 8a. P1-A-R2 — independent-review remediation (2026-11-12, verified)

| Item | Status | Evidence |
|---|---|---|
| B-1: bridge `prior_checkpoints` uses the graph checkpoint path | DONE-VERIFIED | `src/bridge/__main__.py`; 4 bridge subprocess tests |
| B-2: OTel cleanup targets the isolated DB, never home | DONE-VERIFIED | `src/tests/test_otel_tracing.py`; B-2 regression seeds/deletes in isolated DB |
| All nine real DB/sidecar files + journals immutable | DONE-VERIFIED | full SHA-256 + existence/size/mtime before/after |
| Invalid checkpoint paths fail closed, no home fallback | DONE-VERIFIED | directory target, parent-is-file, nested parent, writable custom path |
| Existing lazy checkpointer retained | DONE-VERIFIED | no revert; import still opens nothing |
| Retention/vacuum/workspace placement | **OPEN (F-05 remains PARTIAL)** | no prune policy; 937 MB DB, 426 index DBs |
| P1-B collection/test baseline | NOT STARTED (re-review gate) | P1 report; F-02 |

Verification: `test_checkpoint_isolation.py` 22 passed (56.50 s);
`test_prior_checkpoint_isolation.py` 4 passed (26.10 s); targeted P1-A receipt
43 passed (102.62 s); final R2 receipt 47 passed (181.89 s); persistence/restart
subset 72 passed (27.81 s); final B-1/B-2/real-data re-run 6 passed (40.26 s).
Real DB/sidecars and all 61 workspace directories unchanged. HEAD `fb5bd528`
unchanged; no commit.

## 8b. P1-A-R3 — SQLite URI path correction (2026-11-12, verified)

| Item | Status | Evidence |
|---|---|---|
| B-4: checkpoint count uses an encoded absolute file URI | DONE-VERIFIED | `sqlite_readonly_uri()`; `_prior_checkpoint_count` |
| `#` path cannot be truncated to a decoy DB | DONE-VERIFIED | intended 2 vs pre-`#` decoy 1 → `prior_checkpoints=2` |
| Spaces, `%`, Unicode paths read the intended DB | DONE-VERIFIED | real bridge subprocess regressions |
| `?` is percent-encoded, never a query delimiter | DONE-VERIFIED | URI assertion always; actual filename case POSIX-only (Windows forbids `?`) |
| Read-only mode cannot modify the selected DB | DONE-VERIFIED | `DELETE` raises `OperationalError`; hash unchanged |
| Existing lazy checkpointer retained | DONE-VERIFIED | no change to `_LazySqliteConnection` |
| Retention/vacuum/workspace placement | **OPEN (F-05 remains PARTIAL)** | no prune policy; 937 MB DB, 426 index DBs |

Verification: `test_checkpoint_uri_isolation.py` 6 passed / 1 skipped (25.55 s);
URI + prior-checkpoint + isolation suite 32 passed / 1 skipped (109.47 s);
session pipeline 7 passed (51.52 s); OTel 7 passed (8.96 s). Real DB/sidecars
and all 61 workspace directories unchanged. HEAD `fb5bd528` unchanged; no
commit.
