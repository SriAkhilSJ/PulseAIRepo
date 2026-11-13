# CrusorAI - Bugs, Limitations, and Discrepancies

**Snapshot:** `fb5bd528b40933346c4004a1490154683dc0d40e` (2026-11-12 engineering audit; working tree uncommitted)
**Rule:** every entry names the evidence and whether it was verified in this
audit. "Verified" means inspected in source or observed in a recorded run; it
does not mean the bug is fixed. Detailed findings: `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md`.

---

## 1. Severity and status legend

| Field | Values |
|---|---|
| Severity | CRITICAL, HIGH, MEDIUM, LOW, INFO |
| Status | OPEN, PARTIAL, FIXED, HISTORICAL, INHERENT |
| Evidence | VERIFIED-HEAD, VERIFIED-WORKTREE, DOCUMENTED, UNVERIFIED |

"VERIFIED-HEAD" means the behaviour was checked against `fb5bd528` plus the
working tree; where the two differ the entry says which. "VERIFIED-WORKTREE"
means the on-disk file is the evidence.

## 2. Current limitations

### B-DESK-001 - Agent Core graph cannot start: missing compaction helpers

- **Severity:** CRITICAL (historical)
- **Status:** **FIXED at HEAD** (`5197937a`), verified 2026-11-12
- **Evidence:** `src/context/compaction.py` exports the helpers;
  `test_eager_history_compaction.py` 22/22; `bench-results/phase-3.3-canonical-runtime/EVIDENCE.md`

All five helpers (`transform_completed_tool_receipts`,
`compact_assistant_tool_call_arguments`, `is_low_information_command`,
`extract_test_metrics`, `generate_historical_anchor_digest`) are implemented in
`src/context/compaction.py` with real semantics. `stream_agent` imports and
runs; the historical collection failure is gone. The fix is committed at
`5197937a` (not uncommitted, as the prior entry said).

### B-DESK-005 - Orchestrator approvals are requested before code generation

- **Severity:** LOW
- **Status:** **FIXED at HEAD** (`5197937a`), verified 2026-11-12
- **Evidence:** `bench-results/phase-3.3-canonical-runtime/INCREMENT2_EVIDENCE.md`

Approval now happens at mutation time after the engine generates the content:
the dock receives a unified diff, a content digest and the workspace
precondition. Approve/deny/cancel bridge probes show one ask per mutation and
no file change on deny/cancel.

### B-DESK-007 - Historical repair-lifecycle contract test fails at HEAD

- **Severity:** LOW
- **Status:** OPEN (pre-existing)
- **Evidence:** VERIFIED-HEAD (`7879e066`) — fails identically with HEAD
  `contract.py`/`requirement_extractor.py` restored

`test_p0_6_8_contract_first.py::TestExactHistoricalLifecycle::test_historical_failure_is_diagnosed_and_repaired`
ends with 2 cross-file violations and 2 failing tests with 0 repair attempts.
It is outside the Phase 3.2 extraction fix and is explicitly deselected in
the verification batch (documented, not hidden).

### B-DESK-006 - Denied approval counted as "1 landed" in the cancel receipt

- **Severity:** LOW
- **Status:** **FIXED at HEAD** (`f3528098`), verified 2026-11-12
- **Evidence:** `bench-results/phase-3.3-canonical-runtime/INCREMENT3_EVIDENCE.md`;
  deny probe receipt `DENIED` with 0 mutation receipts

`stampInterrupt()` now counts only `passed` tool calls as landed. When the
terminal frame carries the canonical receipt, the renderer uses
`receipt.mutation_receipts`/`changed_files` and `terminal_status`, so a denial
shows zero landed mutations and a non-completed outcome.

### B-DESK-002 - Crusor pane ignores the built-in light theme

- **Severity:** MEDIUM
- **Status:** OPEN
- **Evidence:** VERIFIED-WORKTREE + live Electron screenshot

With `workbench.colorTheme = "Default Light Modern"` the workbench is light
(`vs ... light_modern`) but the whole Crusor pane paints `rgb(0,0,0)`. The
approval dock remains readable, so this is visual/theme fidelity, not a
functional blocker. Evidence:
`bench-results/phase-2-desktop-qualification-r2/visual-findings.md`.

### B-DESK-003 - Yellow evidence warning on every cancelled turn

- **Severity:** LOW
- **Status:** FIXED (r2 follow-up, `src/runtime/evidence_capture.py`)
- **Evidence:** VERIFIED-WORKTREE + regression test

A turn cancelled before any model/tool work has no trace/report by construction;
the receipt marked it `degraded` and the renderer painted
"Agent Core evidence capture is degraded. Missing: trace, report." That warning
is now scoped to executed turns: a cancelled-before-execution turn records
`coverage.not_applicable = [trace, report]`, `missing = []`, receipt
`persisted`. Executed turns keep the strict check.

### B-DESK-004 - Ctrl/Cmd+L not proven through a genuine input path

- **Severity:** LOW
- **Status:** OPEN (unproven, not confirmed broken)
- **Evidence:** VERIFIED-WORKTREE + live Electron session

`AppActivate` returned false and OS `SendKeys` did not reach the app (a control
chord was ignored too), so the keybinding could not be exercised at the OS
input layer. CDP key delivery also did not open the pane; the command palette
`Crusor: Open Agent` works.

### B-001 - Interactive file tools bypassed the mutation broker (fixed at HEAD)

- **Severity:** CRITICAL (historical)
- **Status:** **FIXED at HEAD**, verified 2026-11-12
- **Evidence:** `src/tools/file_tools.py:508-538, 1503-1529`; `git diff HEAD -- src/tools/file_tools.py` is empty; `test_canonical_runtime_increment2.py`

Both `write_file` and `edit_file` route through `WorkspaceMutationBroker` with a
digest/precondition-bound token; `copy_file` also uses the broker. Other graph
mutations and shell execution remain fail-closed at the graph boundary. The
previous "HEAD bypasses the broker / working tree only" text was stale and is
superseded by this entry and audit F-12.

### B-002 - Identity and RBAC are not enforced in the live tool path

- **Severity:** HIGH
- **Status:** **PARTIAL (vacuous wiring)**, verified 2026-11-12
- **Evidence:** VERIFIED-HEAD; `src/orchestration/model_adapter.py:837-851`; audit F-07

`IdentityAwareToolAuthorizer` exists in `src/identity/tool_authorizer.py` and is
called by the engineering adapter, but with a hard-coded
`User(..., is_superadmin=True)` principal. There is no reference in
`src/bridge/__main__.py` or `src/graphs/chat_graph.py`. The check therefore
cannot deny any live tool call: tool calls still run with ambient process
permissions rather than role-derived authorization.

### B-003 - Protocol v2 has no frames for several intelligence artifacts

- **Severity:** MEDIUM
- **Status:** OPEN
- **Evidence:** VERIFIED-HEAD

`src/bridge/protocol.py` defines no server events for architecture blueprints,
ADRs, change-impact reports, regression reports, verification reports, or
delivery contracts. The orchestrator can produce these objects, but the desktop
has no typed frame to render them.

### B-004 - Desktop GUI acceptance is not verified

- **Severity:** HIGH for a "product qualified" claim
- **Status:** PARTIAL — provider-free Electron E2E passed; full product qualification open
- **Evidence:** `DESKTOP_REPAIR_EVIDENCE.md`, screenshots

The real Electron app launched, the Agent pane opened, chat and engineering
prompts were submitted through the UI, the diff approval dock was used, the
broker wrote files, and denial/cancellation left the workspace unchanged.
Remaining: full TurnReceipt rendering, live providers, packaging and broader
desktop qualification.

### B-005 - Live acceptance is failed or unvalidated

- **Severity:** HIGH
- **Status:** OPEN / HISTORICAL FAILURE
- **Evidence:** DOCUMENTED (`diagnostics/p0_6_9/`, `diagnostics/live12_*`,
  `README.md`, prior session notes)

- The P0.6.9 live run did not produce an accepted result (a generation and/or
  persistence failure is recorded in its evidence); it is not a PASS.
- The LIVE12 acceptance run remains unrun/uncertain.
- The README records a full-stack run that produced files but failed SQLite
  persistence (`no such table: tasks`); the follow-up repair has provider-free
  evidence only.
- A historical provider reservation is reported as still `in_flight` in prior
  session notes. Do not mutate billing/provider state to "clean it up" without
  owner approval.

Do not claim end-to-end product acceptance until a new authorized run is
recorded with artifacts and a verdict.

### B-006 - The full suite is uncollectable/red; the last clean baseline is historical

- **Severity:** HIGH
- **Status:** **OPEN — collection fails**, verified 2026-11-12
- **Evidence:** `pytest --collect-only -q` (**4,968** collected after P1-A,
  3 errors; 4,953 at the audit);
  `test_bridge.py` (2 failed / 37 passed); `test_agent_cards.py` (1 failed / 10
  passed); audit F-02

The last recorded *full* result is 2,802 passed, 25 failed, 26 skipped, 1
xfailed (README, 2026-10-27). On 2026-11-12, three modules fail at import
(`deduplicate_streaming_usage` missing from `src/llm/factory.py`;
`record_turn_receipt` shadowed by the `src/observability` package), and three
known tests are red. Phase 12.1.3's 395/395 is a narrower regression set. Do
not claim a clean full suite.

### B-007 - Windows + CPython <= 3.12 spawns `cmd /c ver` at import

- **Severity:** MEDIUM
- **Status:** FIXED (Phase 1.4 final)
- **Evidence:** VERIFIED on Python 3.11.9 and 3.14.4

`src/runtime/windows_shell.py` and `src/tools/terminal_tools.py` called
`platform.system()` at import time. On Windows with CPython <= 3.12,
`platform.win32_ver()` calls `subprocess.check_output(['cmd', '/c', 'ver'])`.
Both now use `os.name == "nt"`. The full guarded import passes on Python 3.11.9
and 3.14.4, and both versions pass the full security suite (232 passed,
3 skipped).

Mitigation: `.github/workflows/security-guard.yml` runs Python 3.14, where the
version is read from `winreg`. The suite is therefore not executed on 3.11 in
CI. A one-line change to `os.name == "nt"` would remove the spawn and allow
3.11 coverage.

### B-008 - The AppContainer AST guard is static, not a sandbox

- **Severity:** MEDIUM
- **Status:** INHERENT
- **Evidence:** VERIFIED-HEAD

`src/tests/test_security_containment.py` now requires the exact 18-statement
grant body, protected-name bindings, module shape, exact `ctypes.Structure`
layouts, module-class bodies, exact WinDLL initialization, the exact import,
module declaration, helper and manager method manifests, the exact helper body,
sync/async grant uniqueness, and grant ownership as the helper's direct nested
child (Phases 1.3.2-1.3.4R2). It still cannot prevent generated code, native
extensions, direct OS calls, a different file, or a compromised interpreter from
performing a mutation. The OS sandbox and execution broker are the runtime
boundary.

The exact manifests also mean any legitimate import, constant, structure,
helper or manager-method change fails closed; the manifests and positive control
must be updated together in an audited change.

### B-009 - Machine-level WindowStation/Desktop ACL recovery is unresolved

- **Severity:** HIGH
- **Status:** OPEN
- **Evidence:** DOCUMENTED (`docs/production/phase-1/`, security phase docs)

The hardening work removed dangerous import-time ACL payloads and repair
scripts; it did not implement a safe, host-level recovery of
WindowStation/Desktop ACLs. No live desktop security is claimed.

### B-010 - Financial state spans multiple stores

- **Severity:** MEDIUM
- **Status:** OPEN
- **Evidence:** VERIFIED-HEAD + DOCUMENTED (Phase 0 architecture map)

Canonical reservations live in `sessions.db`; additional surfaces include
`provider_invocations.jsonl`, per-task `*_finops.json`, and workspace
aggregates. Reconciliation is time/heuristic based, not lease/fencing-token
based. A crash between writes can leave inconsistent records.

### B-011 - Compaction can invalidate the prompt cache

- **Severity:** MEDIUM
- **Status:** OPEN (measured, not mitigated)
- **Evidence:** VERIFIED in checkup warning (2026-11-08)

The agent-core checkup warns that compaction does not consult the cache plan.
Summarising history rewrites the prefix, so the next call re-prefills the whole
prompt at full price. `src/context/prompt_cache_*` exists, but the checkup says
the compaction path does not use it.

### B-012 - The cost budget leg is off by default

- **Severity:** MEDIUM
- **Status:** OPEN
- **Evidence:** VERIFIED in checkup warning (2026-11-08)

Token/iteration ceilings exist, but a session can run until the provider
refuses unless a cost budget is configured. This is a spend-risk default, not a
correctness bug.

### B-013 - Tool-result volume can still dominate a turn

- **Severity:** MEDIUM
- **Status:** INHERENT / MONITORED
- **Evidence:** VERIFIED in checkup warning (2026-11-08)

Tool results are capped at 12,000 characters per result, but 30 calls can still
inject roughly 90,000 tokens before reasoning. Long turns remain the dominant
cost and latency risk.

### B-014 - Desktop fork drift and native-module fragility

- **Severity:** MEDIUM
- **Status:** PARTIAL
- **Evidence:** DOCUMENTED (`docs/production/phase-0/`,
  `PHASE_12_1_3_REPRODUCIBLE_BUILD.md`, `desktop/README.md`)

The fork vendors 18k files and depends on native modules. Phase 12.1.3
(dated 2026-11-06) recorded a reproducible-build fix. Phase 0 (2026-11-08)
nevertheless recorded a launch failure from `@vscode/policy-watcher` bindings
after `npm ci --ignore-scripts`; the modules were restored offline but a
successful launch was not proven at that point. `vsda` remained unresolved.
Launch status therefore requires a fresh check.

### B-015 - Two agent execution paths can diverge

- **Severity:** MEDIUM
- **Status:** **RESOLVED at HEAD for the desktop**; **PARTIAL for other entry points**
- **Evidence:** `src/bridge/__main__.py:1640-1688`; `git show HEAD:src/bridge/__main__.py` has no orchestrator branch; audit F-10

The bridge no longer selects a top-level owner by mode/env. `stream_agent`
(LangGraph) is the only interactive lifecycle; the orchestrator is delegated
inside `engineering_task_node`. The direct branch and
`CRUSORAI_ORCHESTRATOR_ENGINE` selection are absent at HEAD. Dashboard/CLI
callers still invoke `stream_agent` without `canonical_runtime=True`, so they
skip engineering delegation and mutation-token minting (F-10).

### B-016 - Production WindowStation/Desktop ACL-grant branch

- **Severity:** HIGH for the AppContainer boundary
- **Status:** RESOLVED (Phase 1.4 final)
- **Evidence:** VERIFIED runtime + CI

The automatic `_ensure_windowstation_desktop_access()` call was removed from
`initialize()`. The production path never rewrites machine WindowStation/Desktop
DACLs; an environment that cannot launch AppContainer fails closed. Runtime
tests replace the helper with a function that raises if called, proving the
production path does not invoke it. The helper remains for explicit operator
provisioning only.

### B-017 - AppContainer network isolation

- **Severity:** HIGH for the kernel network boundary
- **Status:** VERIFIED (Phase 1.4 final)
- **Evidence:** native probe, local + Windows CI

A native Winsock control connected to a disposable local TCP listener; the same
probe inside AppContainer timed out and the listener saw no connection. Denial
is a silent kernel drop, not a Winsock error. A supplemental UDP `sendto`
returned success but no datagram arrived. This is genuine network isolation
evidence, with the silent-drop behavior documented.

### B-018 - AppContainer TMP is not the staging directory

- **Severity:** LOW / CONTRACT
- **Status:** ACCEPTED CONTRACT (Phase 1.4 final)
- **Evidence:** VERIFIED runtime + test

AppContainer uses package-local `AC\Temp`, which is isolated per profile and
removed with it; staging remains the file-delivery root. The runtime test
asserts the package-local contract. The old assumption that TMP must equal
staging was wrong.

### B-019 - Job memory peak accounting exceeds the configured limit

- **Severity:** MEDIUM / ACCOUNTING
- **Status:** OPEN / BOUNDED
- **Evidence:** VERIFIED runtime (Phase 1.4)

With `max_memory_mb=64` (job limit 67,108,864 bytes), a 128 MB allocation raised
`MemoryError`; `PeakJobMemoryUsed` reported ~140 MB. A 128 MB allocation
succeeds under a 512 MB control. Behavioral denial is observed, but hard
peak-memory enforcement is not claimed; the accounting discrepancy remains.

### B-020 - Output capture bypassed the retention cap

- **Severity:** MEDIUM / RESOURCE CONTROL
- **Status:** FIXED (Phase 1.4 corrective)
- **Evidence:** VERIFIED runtime before/after

Before the correction, the fallback used `readline()` (an unbounded line was
materialized before truncation), and the AppContainer path wrote temp files then
called `read_bytes()` (unbounded temp storage and parent allocation). Both
backends now retain at most 1 MiB per stream using fixed 64 KiB chunks, drain
excess, and use independent stdout/stderr budgets. AppContainer uses anonymous
pipes, not temp files. Runtime tests: 19/19 with AppContainer opt-in.

### B-021 - Electron Agent pane did not open

- **Severity:** HIGH for desktop E2E claims
- **Status:** FIXED in the working tree (2026-11-10, not committed)
- **Evidence:** `DESKTOP_REPAIR_EVIDENCE.md`; screenshots in `logs/desktop-e2e/`

Root cause: `IChatSessionRoutingProviderService` was registered only by the
separate `sessions.common.main.ts` app entry; the regular workbench loaded
`chat.contextContributions` without the singleton. The workbench chat
contribution now imports the real service module. The Agent pane opens and was
driven through the actual UI: chat prompt/response, engineering diff approval,
broker write, report, denial and cancellation.

Remaining: the pane shows the delivery report/status; every canonical
`TurnReceipt` field is not yet rendered as its own card.

### B-022 - Desktop shipped-panel manifest mismatch

- **Severity:** MEDIUM
- **Status:** FIXED in the working tree (2026-11-10, not committed)
- **Evidence:** `DESKTOP_REPAIR_EVIDENCE.md`

`npm run compile-client` updates `out/`, but the shipped hashes are written by
`scripts/emit-crusorai-bundle.mjs`. Running the emitter after compile regenerated
`SOURCES_HASH`/`SOURCES_MANIFEST.json`; the bridge now logs
`compiled workbench matches the pulled crusorai sources - panel is current`.

### B-023 - Explicit Markdown requests synthesized source/test files

- **Severity:** HIGH for task fidelity
- **Status:** **FIXED at HEAD**, verified 2026-11-12 (7/7 scope tests pass)
- **Evidence:** `test_scope_fidelity.py` 7/7; `QUALIFICATION_REPORT.md`

Two leaks: an explicit `.md` requirement was classified SOURCE and synthesized
`src/req_001_module.py`; a “Do not create … tests” clause was extracted as a
TEST requirement and synthesized `tests/test_req_002.py`. Explicit file roles now
win over the verb fallback, prohibitory clauses are skipped, and negated test
words no longer trigger test verification.

### B-024 - Live output contains emoji mojibake

- **Severity:** LOW / quality
- **Status:** OPEN
- **Evidence:** live `hello.md` (`logs/live-e2e4/`)

The live Velona response wrote `dY'<` / `�?"` around an emoji. Scope,
verification and mutation were unaffected; provider/encoding investigation is
required before quality claims.

### B-025 - Gateway and FinOps invocation IDs could differ

- **Severity:** MEDIUM for accounting reconciliation
- **Status:** **FIXED at HEAD** (`5197937a`); live re-verification still absent
- **Evidence:** live4 gateway `inv-f417…` vs ledger `inv-6cd6…`

The engineering adapter now adopts `gateway_result.context.invocation_id` before
recording the ledger entry. The five-call budget was exhausted before a live
re-verification.

## 3. Documentation-versus-implementation discrepancies

These are contradictions found during this audit. The source code is treated as
current truth.

| Document claim | Actual state (2026-11-12) | Resolution |
|---|---|---|
| `REMAINING_LIMITATIONS.md` #1: the Phase 11 stack is "completely uncallable from the desktop" because the bridge directly calls `stream_agent`. | The bridge always calls `stream_agent`, and engineering is delegated inside the graph; this is the intended single-owner design. | The document is outdated. The remaining gap is capability (F-01) and entry-point parity (F-10), not wiring. |
| `REMAINING_LIMITATIONS.md` #5: the orchestrator's `default_executor` writes hardcoded stub functions. | `default_executor` calls `self.model_adapter.execute_node(...)`. | Still outdated; verify per provider. |
| `README.md`: full suite "2,802 passed, 25 failed". | 2026-10-27 snapshot. The 2026-11-12 suite cannot collect (3 errors) and has 3 known failures. | Historical only; see B-006/F-02. |
| `PHASE_12_1_3_FINAL_VERDICT.md`: "PRODUCT_QUALIFIED_WITH_LIMITATIONS". | The same document marks GUI NOT VERIFIED and provider DETERMINISTIC_PROVIDER_ONLY. | Quote the qualifiers; do not shorten to "qualified". |
| Root `REMAINING_LIMITATIONS.md` #2: file tools bypass the broker. | **False at HEAD**: `write_file`/`edit_file` use `WorkspaceMutationBroker` (`file_tools.py:508-538`). | Superseded by B-001 and F-12. |
| `README.md`: desktop/runtime are production-hardened. | Security phases 0–1.4 are qualified for a narrow Windows contract; audit F-03/F-04/F-05 show default gaps. | Scope "hardened" to the security evidence; do not imply whole-product readiness. |
| `AGENTS.md` §11: B-DESK-001 is an active blocker. | `compaction.py` exports both helpers; the graph runs. | Fixed 2026-11-12; see F-12. |
| `docs/ARCHITECTURE.md` §4: bridge routes agent/plan to the orchestrator (two owners). | Single owner: `stream_agent`; orchestrator delegated. | Corrected in §4 and §14.2; F-12. |
| `docs/ARCHITECTURE.md` §8: execution broker is the single process chokepoint. | Terminals use the broker only when `CRUSOR_SANDBOX_TERMINAL=1`; test execution uses raw subprocess. | False as written; F-03. |
| `docs/CURRENT_STATE.md`/`PHASE_TRACKER.md`/`ROADMAP.md`/`LATEST_HANDOFF.md`: working tree 195/211/239/247 entries. | 262 at the audit; **269 after P1-A** (83 modified, 186 untracked, 0 staged). | Corrected in this reconciliation and P1-A. |
| `docs/ARCHITECTURE.md` §11 / `CURRENT_STATE.md`: 334 test modules. | **363 modules; 4,968 collected; 3 collection errors** (362/4,953 at audit). | Corrected; F-02. |
| `docs/DECISIONS.md` D-2026-11-12-02: synthesis is "never from a requirement id". | `contract.py:981-993` still falls back to `src/{rid}_module.py` without discovery evidence; a test asserts it. | Condition the decision on discovery evidence; F-01. |
| `src/bridge/__main__.py:1666-1673` comment: interactive sessions default to `ask`. | Code default is `workspace_session`. | Correct the default or the comment; F-04. |
| `docs/BUGS_AND_LIMITATIONS.md` B-002: RBAC "not wired". | Wired in the engineering adapter with a hard-coded superadmin; cannot deny. | PARTIAL; F-07. |

## 4. Unknown or unverified

1. Which uncommitted runtime/desktop work is intended to ship (the broker is
   already at HEAD; the working tree carries the rest). See ROADMAP N-2.
2. ~~Whether a headed host can open the Electron Agent pane and drive
   approvals.~~ Proven provider-free (2026-11-10); live providers and full
   TurnReceipt rendering remain unproven.
3. Whether the 25 historical failures still reproduce. The suite currently
   cannot collect in full (F-02), so this cannot be answered from one run.
4. Whether the orchestrator path produces real code for every provider (adapter
   coverage is provider-specific; the 2026-11-12 live run failed all three
   engineering tasks).
5. Current provider credit/availability and the state of the historical
   reservation.
6. Whether the Phase 11 intelligence stack is exercised end-to-end from the
   desktop, beyond being constructed and called by the bridge.
7. Whether live provider cost/latency should be measured under an explicit
   paid-call authorization.

## 5. How to confirm an entry

```powershell
# B-001
git show HEAD:src/tools/file_tools.py | Select-String "WorkspaceMutationBroker"

# B-002
Get-ChildItem src -Recurse -Filter *.py | Select-String "IdentityAwareToolAuthorizer"

# B-003
Get-Content src/bridge/protocol.py -TotalCount 45

# B-006 (fresh full run; long)
python -m pytest -q

# B-007
python -c "import platform, inspect; print(inspect.getsource(platform.win32_ver))"

# F-02 (collection; no provider calls)
.\.venv\Scripts\python.exe -m pytest --collect-only -q

# F-05 (checkpoint path; read-only)
Select-String -Path src\graphs\chat_graph.py -Pattern "_CHECKPOINT_DB ="

# F-06 (package shadowing; read-only)
.\.venv\Scripts\python.exe -c "import src.observability as o; print(o.__file__, hasattr(o,'record_turn_receipt'))"

# F-03 (execution defaults)
Select-String -Path src\tools\terminal_tools.py -Pattern "CRUSOR_SANDBOX_TERMINAL"
```

Record the command, platform, commit, and exit code when closing an entry.

## 2026-11-10 — Streaming UI qualification limits

- **OPEN (fixture scope):** `CRUSORAI_BRIDGE_RUNNER=scripted` proves the
  streaming/cards UI but bypasses the LangGraph checkpointer. A renderer reload
  therefore restores no transcript with this fixture. Do not cite it as replay
  proof; use the Increment checkpoint tests for production replay.
- **OPEN (evidence capture):** scripted turns report evidence capture DEGRADED
  because they write no trace/report artifacts. This is fixture behavior, not a
  new production regression.
- **UNVERIFIED (live):** invocation-id reconciliation is proven provider-free
  only; no paid call was authorized to re-verify against Velona.
- The earlier live `hello.md` mojibake could not be reproduced at the byte
  level; broker/protocol bytes are exact UTF-8. Treat console code-page
  decoding as the likely display cause until a live render proves otherwise.

## 2026-11-11 — Agentic progress and plan outcome limits

**Closed**

- Engineering progress was computed and discarded:
  `engineering_task_node` called `run_task_request` without `on_progress`.
  Fixed with `EngineeringProgressReporter` (activity + plan cards through the
  existing bus/bridge/renderer). Evidence:
  `CRUSOR_PROGRESS_INTEGRATION_REPORT.md`.
- `AdaptiveContextManager.record_task_completion` had no caller, so
  `completed_steps` stayed empty forever. Fixed through
  `record_task_outcome` at the scheduler settlement boundary. Evidence:
  `CRUSOR_PLAN_COMPLETION_REPORT.md`.
- Blocked work and cancelled work were rendered as `failed` or left `pending`.
  Fixed with additive `blocked`/`cancelled` plan states. Evidence:
  `CRUSOR_PLAN_OUTCOME_SEMANTICS_REPORT.md`.
- A second engineering turn in the same workspace failed with
  `Invalid state transition … COMPLETED → UNDERSTANDING` because every turn
  shared one orchestration storage directory. Fixed with per-turn storage
  (`src/graphs/chat_graph.py`).

**Open / limits**

1. **Blocked vs intentional skip.** The scheduler has no independent
   intentional-skip outcome; `SKIPPED` maps to `blocked`. Do not claim a
   distinct skip state exists.
2. **Node completion is not the task verdict.** A node can be `completed` while
   the delivery is `FAILED`/`NOT_VERIFIED` because later global gates failed.
   The plan and the delivery/verification cards report both facts separately.
3. **Multi-turn plan cards share the post-reload stack.** `session_messages`
   returns the latest card per `card_id`, so several turns' plan cards can render
   together after reload (existing renderer behaviour). Scoping cards to their
   own history turn remains open.
4. **No real-provider validation of these paths.** The acceptance uses the mock
   adapter (`rows=0` provider invocations). An intermediate scripted-seam run
   produced one local FinOps attribution row (₹0.000555) from scripted usage
   metadata; the seam is network-free and was not used for the final evidence.
5. **Pre-existing failures remain.** `test_agent_cards.py::test_all_required_card_types_are_declared`
   (working-tree extra Python card types) and two `test_bridge.py` assertions
   (echo frame window, autotitler signature) were not changed or hidden.
6. **Plan strip summary counts completed/total only**; blocked/cancelled counts
   appear in the activity detail and step states, not the strip header.

## 2026-11-11 — Turn card ownership limits

**Closed**

- Cards from multiple turns shared one bottom stack after reload: the renderer
  had a global card-id map, hydration never passed cards per turn, and the
  bridge returned messages without turn identity. Fixed with `CrusorCardStore`,
  journal request-hash message stamping, full-identity card dedupe, and per-turn
  hydration/rendering. Evidence: `CRUSOR_TURN_CARD_RESTORATION_REPORT.md`.
- Session reset did not clear the card map; `resetSessionState` now clears the
  store and `currentTurnId`.
- Duplicate card replay could duplicate entries; identity-keyed updates and
  idempotent snapshot restore prevent it.

**Open / limits**

1. **Legacy ambiguity.** Sessions whose journal lacks `turn.started` request
   hashes and whose message/turn counts do not align leave cards unassociated.
   They stay in the store and are named by a bounded `console.warn`; they are
   never attached to the newest turn.
2. **Single-turn legacy fallback only.** Messages with no turn ids can adopt
   cards only when the hydrated window has exactly one turn and the store has
   exactly one bucket.
3. **Placement unchanged.** Cards still render at the end of their turn; this
   task did not implement chronological interleaving.
4. **Journal paging cost.** `session_messages` pages the whole session journal;
   correct for long histories but proportional to journal size.
5. **No paid-provider validation** of this path; the Electron acceptance is
   provider-free (`rows=0`). Pre-existing `test_agent_cards`/`test_bridge`
   failures remain untouched.

## 2026-11-11 — Timeline visibility limits

**Closed**

- Verification, delivery and cost cards were painted as user-facing cards. They
  are now internal-only via `isUserFacingCard`; the model, journal, receipts and
  FinOps records are untouched. Journal proof: 3 delivery, 1 verification and 3
  cost cards existed for the three acceptance turns while the DOM rendered 0.
- All typed cards were appended after the timeline, putting the final answer
  above the work. Visible cards now pin into `CrusorAITurnPart`; the final
  assistant answer is last live and after reload.
- A typed tool card duplicated the existing tool row; it is suppressed when the
  matching tool row is present.

**Open / limits**

1. **Historical interleaving is anchored, not event-exact.** Checkpoint messages
   have no per-event sequence; restored turns place the plan early and other
   cards before the final answer in stored order.
2. **Typed tool cards without a matching tool row** fall back to the end of the
   turn.
3. **Plan strip + plan card** and **approval dock + approval card** remain as
   separate existing surfaces (persistent summary/interaction vs turn record).
4. **Hidden cards remain in renderer state** by design (audit/debug); they are
   only filtered at paint time.
5. **Renderer reload can close the workbench window** in this build; the
   acceptance relaunches with the same profile for repeated hydration, and the
   explicit full-restart phase is separate.
6. **No paid-provider validation**; mock-mode evidence only.

## 2026-11-11 — Real-provider qualification blocked by the contract gate

**Open (blocking)**

- ~~**B-LIVE-001.** `parse_prompt_contract` only extracts a symbol when it follows
  the literal token `def` or `function` …~~ **FIXED 2026-11-11** (P0 milestone).
  Natural-language forms are extracted by narrow, clause-scoped patterns;
  preservation/negation clauses are excluded; ambiguity detection is unchanged.
  Evidence: `src/tests/test_contract_natural_language.py` (20 passed),
  `test_p0_6_8_contract_first.py` (44 passed), Electron `crusor-p0` acceptance
  (plan strip produced for "Implement a divide(a, b) function …"). Report:
  `CRUSOR_P0_CONTRACT_AND_FAILURE_REPORT.md`.
- **B-LIVE-002.** Ledger `turn_id` does not match the rendered UI turn id and
  `task_id` duplicates the prefix (`turn_turn-…`); per-turn cost attribution
  needs a mapping. `latency_ms` is written as `null`, so latency is only
  derivable from `started_at`/`completed_at`. **Still open** — not part of the
  P0 milestone. (Distinct from the *mission's* "B-LIVE-002 — honest turn
  outcomes", fixed as B-LIVE-004 below.)
- **B-LIVE-003.** Real-provider UI streaming was judged unacceptable by the user
  during Test A/B: one activity stage plus a terminal error string, no plan card,
  no tool rows, no file-change card, no test-result card. **Partially fixed
  2026-11-11 (P1A).** Engineering model calls now stream through the gateway and
  report live generation facts (elapsed, characters received, target file) while
  the request is running, and the plan marks the generating node `in_progress`.
  Model *text* is deliberately not painted as chat for engineering (it is a file
  body / structured plan); the chat path keeps its token streaming. Evidence:
  `CRUSOR_P1A_ENGINEERING_STREAMING_REPORT.md`; Electron `crusor-p1a` acceptance
  with a loopback SSE provider (no paid calls).

**Fixed 2026-11-11 (P0)**

- **B-LIVE-004 — a failed turn could paint as a success.** `turn_done` carries
  `completed: false`, but the renderer derived its outcome from `cancelled` plus
  an optional receipt, so an engineering failure with no receipt rendered as a
  normal answer whose text was the error. Fixed by
  `common/crusorAITurnOutcome.ts` (cancellation → receipt → evidence → completed
  flag → unknown) wired into `turn_done`/`turn_failed`; the error is shown in the
  existing error row and a `Run failed` receipt, and a byte-identical failure
  chunk is removed from the transcript. Restored turns take their outcome from
  the journal's durable terminal row (`turn.completed|failed|cancelled|
  interrupted|watchdog`) exposed as `session_messages.turn_outcomes`; missing
  evidence is `unknown`, never `completed`, and hydrated tools are `recorded`
  (no invented `passed`). Evidence: `scripts/test_crusorai_turn_outcome.mjs`,
  `src/tests/test_turn_outcome_semantics.py` (8 passed), Electron `crusor-p0`
  acceptance 16/16 (successful turn clean, failed turn `is-failed` + error row
  live and after reload).

**Evidence.** `CRUSOR_REAL_PROVIDER_E2E_QUALIFICATION.md` (verdict FAIL; ₹0.143 of
a ₹50 cap spent, 2 settled calls). Tests B/C were stopped, not disproven.

## 2026-11-12 — Real-provider backend qualification findings

**Open (blocking engineering capability)**

- **B-CORE-001 — engineering binds no tools.** `orchestrator.py` /
  `model_adapter.py` contain no `bind_tools`, no tool registry use and no tool
  loop; only the mutation authorization at `model_adapter.py:843`. Live run:
  the planner created `src/req_001_module.py`, `src/req_003_module.py`,
  `tests/test_req_001_module.py` instead of editing the existing `mini_math`
  package. No file listing, reading, searching or test execution occurs.
- **B-CORE-002 — no bounded format recovery.** Test A's single source reply was
  rejected by `extract_generated_source` ("Malformed Markdown code fence") and
  the run ended without a retry/re-prompt. Fail-closed is correct; recovery is
  missing.
- **B-CORE-003 — repair loop unreachable.** Test C planned one `task_main` node
  and returned `BLOCKED`; it never executed the failing tests, so diagnosis and
  repair could not occur. The injected `multiply()` regression remains.
- **B-CORE-004 — aux rate limiting is unhandled in-flight.** `qwen/qwen3.7-flash`
  returned `rate_limit_exceeded` during a post-run review; the retry path
  recovered, but the turn has no bounded aux fallback policy.
- **B-CORE-006 — `mock_mode` does not gate repair dispatches.** The repair loop
  in `orchestrator._execute_repairs` calls the paid adapter regardless of
  `ModelExecutionAdapter.mock_mode`. A deterministic engine harness with
  `max_correction_attempts` left at its default spent ₹0.0601 on
  `repair_task_ops` (2026-11-12). Set `max_correction_attempts=0` for offline
  runs until the gate is fixed.
- **B-PRE-001 — pre-existing failures caused by uncommitted prompt/bridge work
  (not Phase 2A).** `test_p0_3_orchestrator_integration::test_desktop_bridge_reaches_model_backed_executor`
  expects a `turn_lifecycle` frame; the working-tree bridge emits
  `turn_started`/`turn_done` (HEAD still maps `turn.started` →
  `turn_lifecycle`). `test_autonomous_runtime_contract` has 3 failures asserting
  chat system-block counts (`fused_system_blocks` 5 vs 6). Neither suite imports
  the Phase 2A files.
- **B-CORE-007 — outside-workspace deletes/renames and new-file creation are
  not supported.** Phase 2D grants read and write access for an exact external
  boundary; create and modify are grant-aware, but `delete_file` /
  `rename_file` / `copy_file` remain workspace-only, and a path that does not
  exist yet is not offered for approval. Read grants never authorise writes.
- **B-CORE-008 — generic approval wording for `workspace.access`.** The request
  rides the existing `tool.approval.request` event and dock, but the renderer
  was not changed (frontend out of scope), so the card shows the generic
  path/arguments rather than a bespoke "allow this folder?" sentence. Backend
  payload is complete (`name`, `arguments.path`, `operation`, `reason`).

**Fixed 2026-11-12**

- **B-CORE-005 — ledger `latency_ms` was null.** `_ledger_record` now records
  the measured dispatch→response/failure latency. Confirmed in the live rows
  (3242 ms, 1737 ms, 16381 ms, 26905 ms, 9709 ms). **Uncommitted working tree;
  HEAD still has the null-latency behaviour.**

**Narrowed 2026-11-12 (Phase 2A, uncommitted)**

- **B-CORE-001** is narrowed, not closed. The engineering path now has bounded
  read-only discovery (`workspace.list_files` / `read_file` / `search`) before
  planning, and the contract resolves real paths instead of requirement-id
  filenames. It still binds no tools *during* generation, and still cannot edit
  an existing file surgically — that is Phase 2B.
- **B-CORE-003** remains open: no test-diagnose-repair loop driven by discovery
  evidence. The existing repair loop is unchanged.

**Positive evidence**

- Provider auth/dispatch/usage/FinOps: 5 settled calls, real tokens, honest
  receipts (`FAILED/FAILED/BLOCKED`), `turn_id` correct, spend ₹0.4207 of ₹50.

## 2026-11-12 — Initial engineering audit (F-01…F-15)

Detailed register: `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md`. Severity,
status, sources, evidence, impact and next action are preserved here in compact
form.

### F-01 — Engineering binds no tools during generation

- **Severity:** CRITICAL · **Status:** OPEN (narrowed by Phase 2A)
- **Sources:** `src/orchestration/model_adapter.py:806-916, 1164-1288,
  1330-1660`; `src/orchestration/orchestrator.py:583-640`;
  `src/orchestration/contract.py:981-993`
- **Evidence:** no `bind_tools` in `src/orchestration/`; real run A/B/C failed;
  requirement-id fallback still reachable and asserted by
  `test_contract_assignment_reliability.py:66-70`.
- **Impact:** no inspection, targeted edit, test loop or repair; guessed paths.
- **Next:** Phase 2B — bind read/list/search during generation, targeted edits,
  unconditional requirement-id rejection.

### F-02 — Test suite uncollectable/red and not gated

- **Severity:** HIGH · **Status:** OPEN
- **Sources:** `test_financial_accounting_closure.py:25`,
  `test_provider_usage_normalization.py:27`, `test_observability.py:5`,
  `test_bridge.py:98,802`, `test_agent_cards.py:47`,
  `.github/workflows/security-guard.yml:4-14`, `e2e-core.yml:14-20`
- **Evidence:** **4,968** collected (4,953 at audit + 15 P1-A isolation tests),
  3 errors; bridge 2 failed / 37 passed; cards 1 failed / 10 passed; security
  suite 232/3; security CI is path-filtered; real-provider CI not on this
  branch.
- **Impact:** no trustworthy regression gate.
- **Next:** fix imports/pins, add full-suite and security CI gates, record a
  full run with commit + exit code.

### F-03 — Unsandboxed execution + inherited env by default

- **Severity:** HIGH · **Status:** OPEN (mitigated by the graph shell block)
- **Sources:** `src/tools/terminal_tools.py:1089-1170`;
  `src/orchestration/test_execution.py:242-261, 619-687`;
  `src/graphs/chat_graph.py:1470-1478`
- **Evidence:** `CRUSOR_SANDBOX_TERMINAL` defaults to `0`; `env=dict(os.environ)`;
  test execution uses a raw subprocess (it does scrub `*_API_KEY` et al.).
- **Impact:** future tool-policy change becomes local RCE/secret exfiltration;
  the architecture's "single chokepoint" claim is false.
- **Next:** broker + env allowlist + sandbox by default; approval for generated
  tests; negative tests.

### F-04 — Product approval default is `workspace_session`, not `ask`

- **Severity:** HIGH · **Status:** OPEN
- **Sources:** `src/bridge/__main__.py:1671-1675`;
  `src/orchestration/approval_gateway.py:96-112`;
  `src/orchestration/models.py:321`
- **Evidence:** LOW-risk writes are auto-granted; acceptance scripts force
  `ask`, so the dock evidence is harness-only.
- **Impact:** writes can land with no visible approval.
- **Next:** default `ask`; persisted policy setting; default-path approval test.

### F-05 — Hardcoded, import-time, unbounded checkpoint DB

- **Severity:** MEDIUM-HIGH · **Status:** **PARTIAL (P1-A + R2 + R3 fixed
  path/import/bridge/OTel/URI isolation; retention open)**
- **Sources:** `src/runtime/app_paths.py`; `src/runtime/session_store.py`;
  `src/graphs/chat_graph.py`; `src/bridge/__main__.py`;
  `src/tests/conftest.py`; `src/tests/test_checkpoint_isolation.py`;
  `src/tests/test_prior_checkpoint_isolation.py`;
  `src/tests/test_checkpoint_uri_isolation.py`;
  `src/tests/test_otel_tracing.py`
- **Evidence:** Path resolves `CRUSORAI_CHECKPOINT_DB` >
  `CRUSORAI_CHECKPOINT_HOME` > `CRUSORAI_SESSIONS_DB` > `CRUSORAI_HOME` >
  default; the connection is lazy; conftest isolates home/sessions/checkpoint.
  R2 routes the bridge `prior_checkpoints` count and the OTel cleanup through
  the same resolved checkpoint DB. R3 encodes that DB as an absolute
  `Path.as_uri()` read-only URI, so `#`, `?`, `%`, spaces and Unicode cannot
  select another database. 22 isolation + 4 bridge + 7 URI tests pass (one
  Windows-only `?` end-to-end skip); all nine real main/sidecar files and three
  journal paths were unchanged across the final run (full SHA-256 + size +
  mtime). 937 MB and 426 index DBs still have no retention.
- **Impact:** Test isolation is fixed; disk lifecycle remains open.
- **Next:** retention/vacuum and a workspace-placement decision.

### B-1 — Bridge `_prior_checkpoint_count` read the real home DB

- **Severity:** HIGH (P1-A review) · **Status:** **FIXED (P1-A-R2,
  2026-11-12)**
- **Source:** `src/bridge/__main__.py:176-203` (call at `session_create`).
- **Evidence:** the default was `~/.crusorai/sessions.db`; running only
  `test_session_pipeline.py` changed the real `sessions.db-shm` mtime
  (content hash unchanged). After R2 the default is the graph's captured
  `_CHECKPOINT_DB` when that module is already imported, otherwise
  `checkpoint_db_path()`, so `CRUSORAI_CHECKPOINT_DB` / `_HOME` /
  `CRUSORAI_SESSIONS_DB` / `CRUSORAI_HOME` are respected; an explicit
  `db_path` remains a caller override. `test_prior_checkpoint_isolation.py`
  proves a 2-row custom checkpoint DB wins over a 7-row custom session DB,
  `session_resume` stays isolated, and a missing override reports 0 instead of
  reading a decoy home DB.
- **Impact:** no silent cross-database counts and no real-home read in tests.
- **Next:** none for this finding; re-review.

### B-2 — OTel test cleanup deleted rows from the real DB

- **Severity:** HIGH (P1-A review) · **Status:** **FIXED (P1-A-R2,
  2026-11-12)**
- **Source:** `src/tests/test_otel_tracing.py:204-241`.
- **Evidence:** `_drop_checkpoints` opened `~/.crusorai/sessions.db` read-write
  and committed `DELETE FROM checkpoints`. After R2 it resolves
  `chat_graph._CHECKPOINT_DB`, refuses the real home path, and calls
  `SqliteSaver.delete_thread()` on the graph's own saver (fallback SQL only
  against the isolated file). A regression seeds a row in the isolated DB,
  calls the helper, proves the row is gone, and proves the real DB + sidecars
  are unchanged.
- **Impact:** test hygiene can no longer write/delete real checkpoint rows.
- **Next:** none for this finding; the full OTel module is left for independent
  review.

### B-3 — Invalid checkpoint paths had no documented contract

- **Severity:** LOW (P1-A review follow-up) · **Status:** **DOCUMENTED + TESTED
  (P1-A-R2, 2026-11-12)**
- **Contract:** an existing directory target raises
  `sqlite3.OperationalError`; a regular file used as a parent raises
  `FileExistsError`/`NotADirectoryError` (`OSError`); a missing nested parent
  is created lazily on first use; an unusable override fails the operation and
  never falls back to the home database. Covered by
  `test_checkpoint_isolation.py`.
- **Impact:** failures are visible and fail closed.
- **Next:** none; keep the no-fallback rule.

### B-4 — SQLite URI was built from an unescaped filesystem path

- **Severity:** HIGH (final independent review) · **Status:** **FIXED
  (P1-A-R3, 2026-11-12)**
- **Source:** `src/bridge/__main__.py` (`_prior_checkpoint_count`);
  `src/runtime/app_paths.py` (`sqlite_readonly_uri`).
- **Evidence:** the old `f"file:{db}?mode=ro"` treated `#` as a URI fragment.
  With an intended DB `cp#frag/sessions.db` containing 2 checkpoints and a decoy
  file `cp` containing 1, the bridge returned `prior_checkpoints = 1` instead
  of 2. The independent review reproduced this and rejected P1-A. R3 uses
  `Path(db).resolve().as_uri()` plus `?mode=ro`, which percent-encodes `#`,
  `?`, `%`, spaces and Unicode. The same repro now returns 2, and read-only mode
  rejects `DELETE` without changing the DB hash.
- **Impact:** no silent cross-database count; absolute path and timeout are
  preserved; no home fallback.
- **Next:** none; keep the encoded-URI helper and the URI regression suite.

### F-06 — `src/observability` package shadows the module; receipts dead

- **Severity:** MEDIUM · **Status:** OPEN
- **Sources:** `src/observability.py:47`; `src/observability/__init__.py`;
  `src/graphs/chat_graph.py:3735-3753`
- **Evidence:** import resolves to the package; `record_turn_receipt` absent;
  the call site swallows the error; `test_observability.py` cannot collect.
- **Impact:** no turn receipts/metrics.
- **Next:** move/re-export, remove the swallow, add a test.

### F-07 — RBAC is vacuous

- **Severity:** MEDIUM · **Status:** PARTIAL
- **Sources:** `src/orchestration/model_adapter.py:837-851`;
  `src/identity/tool_authorizer.py`
- **Evidence:** hard-coded `is_superadmin=True`; no authorizer in the bridge or
  graph.
- **Impact:** no live denial path.
- **Next:** real principal, remove superadmin, adversarial tests.

### F-08 — FinOps under-counts cancellation; pricing provenance asserted

- **Severity:** MEDIUM · **Status:** OPEN
- **Sources:** `model_adapter.py:685-691, 1575-1590`;
  `finops_governor.py:360-372`; `pricing_registry.py:169-174`;
  `invocation_context.py:107-110`
- **Evidence:** `TurnCancelledError` → hold released, zero usage recorded;
  pricing marked `VERIFIED` with no artifact; three storage surfaces.
- **Impact:** under-reported spend; unverifiable cost.
- **Next:** mark post-dispatch cancel `uncertain`; record pricing provenance;
  one ledger.

### F-09 — `VERIFIED` can be presence-based

- **Severity:** MEDIUM · **Status:** OPEN
- **Sources:** `verification/requirement_verifier.py:195-240`;
  `orchestrator.py:1412, 1724-1739`
- **Evidence:** `require_test_evidence=testing_required`; no-test tasks can be
  `VERIFIED` from files/symbols (`:225-233`).
- **Impact:** over-claim on code tasks that omit tests.
- **Next:** derive requirement from contract roles; require tests for SOURCE.

### F-10 — Dashboard/CLI bypass `canonical_runtime=True`

- **Severity:** MEDIUM · **Status:** OPEN
- **Sources:** `src/dashboard_server.py:162-171`; `src/main.py:241-246`;
  `chat_graph.py:5232, 6774, 8423-8425`
- **Evidence:** no engineering delegation and no mutation-token minting outside
  the bridge.
- **Impact:** divergent product behaviour/security.
- **Next:** one entry contract; parity test.

### F-11 — Generated `src/req_*_module.py` contamination

- **Severity:** MEDIUM · **Status:** OPEN
- **Sources:** `src/req_001_module.py`, `req_002_module.py` (tracked),
  `req_003..005_module.py` (untracked); 471 root files
- **Evidence:** +2,549 uncommitted lines; ~285 KB; tests reference the names.
- **Impact:** polluted source tree and tests tied to contamination.
- **Next:** quarantine/delete with owner approval; add a hygiene guard.

### F-12 — Memory contradicted code

- **Severity:** MEDIUM · **Status:** FIXED by the 2026-11-12 reconciliation
- **Sources:** AGENTS.md; CURRENT_STATE; ARCHITECTURE; BUGS; PHASE_TRACKER;
  ROADMAP; LATEST_HANDOFF; DECISIONS
- **Evidence:** 175/195/211/247 entry counts, broker-at-HEAD, B-DESK-001,
  routing, 334 modules, broker chokepoint, `ask` default, requirement-id
  guarantee.
- **Impact (before):** future sessions would fix the wrong things.
- **Next:** keep this register linked; update findings in place.

### F-13 — Engineering streaming internal; real latency unmeasured

- **Severity:** LOW-MEDIUM · **Status:** PARTIAL
- **Sources:** `chat_graph.py:5363-5387`;
  `src/orchestration/generation_progress.py`
- **Evidence:** only elapsed/chars/target file are painted; chat streams text;
  real chunk/latency data absent.
- **Impact:** perception and latency-SLO risk.
- **Next:** define the contract; measure with one authorized run.

### F-14 — `sys.platform` guard drift

- **Severity:** LOW · **Status:** OPEN
- **Sources:** `src/workspace/path_safety.py:140-154`
- **Evidence:** uses `sys.platform == "win32"` despite the `os.name == "nt"` rule.
- **Impact:** cross-platform import/behaviour risk.
- **Next:** normalise on next touch.

### F-15 — 55 stashes / 41 branches

- **Severity:** INFO · **Status:** OPEN / OWNER DECISION
- **Evidence:** `git stash list`; `git branch -a`.
- **Impact:** disposition/cleanup risk.
- **Next:** owner inventory; do not drop/apply without instruction.

## 2026-11-12 — P1-A test isolation repair (checkpoint/session storage)

**Status:** DONE-VERIFIED (P1-A scope). F-05 is PARTIAL: retention/vacuum and
workspace placement remain open.

**What changed.**

- `src/runtime/app_paths.py` now centralises `session_db_path()` and
  `checkpoint_db_path()`. Checkpoint precedence:
  `CRUSORAI_CHECKPOINT_DB` > `CRUSORAI_CHECKPOINT_HOME` >
  `CRUSORAI_SESSIONS_DB`/`_PATH` > `CRUSORAI_HOME` > default. The default is
  unchanged (`~/.crusorai/sessions.db`).
- `src/graphs/chat_graph.py` uses a lazily opened connection
  (`_LazySqliteConnection`) around `SqliteSaver`; importing the graph no longer
  creates or opens a database, and `memory.setup()` is no longer called at
  import. WAL/busy_timeout/synchronous PRAGMAs are applied on first connect.
- `src/runtime/session_store.py` uses the shared `session_db_path()`
  (same precedence as before).
- `src/runtime/app_paths.py` `workspace_app_data_root()` honours
  `CRUSORAI_HOME`, so per-workspace app data also stays under the test home.
- `src/tests/conftest.py` sets `CRUSORAI_HOME`,
  `CRUSORAI_SESSIONS_DB` and `CRUSORAI_CHECKPOINT_HOME` to a throwaway runtime
  root and clears `CRUSORAI_CHECKPOINT_DB`. Session rows, checkpoints,
  `runtime_events.db` and `verification.db` are all isolated.
- `src/tests/test_checkpoint_isolation.py` (new, 15 tests) covers precedence,
  import-time laziness, actual `SqliteSaver` tables, cross-process restart,
  fixture isolation, and real-user-data immutability.

**Evidence.**

| Check | Result |
|---|---|
| `pytest src/tests/test_checkpoint_isolation.py` | **15 passed**, 39.81 s, exit 0 |
| Core reliability gate (20 prior modules + new module) | **366 passed, 2 skipped, 1 xfailed**, 193.28 s, exit 0 |
| Graph persistence/restart group (increment 2/3, plan completion, invocation reconciliation, session store/search) | **139 passed**, 59.40 s, exit 0 |
| Session/acceptance group (`session_store`, `session_search`, phase 12.1) | **35 passed**, 9.20 s, exit 0 |
| Security containment | **232 passed, 3 skipped**, 21.34 s, exit 0 |
| Agent-core checkup | **57 pass / 5 warn / 0 fail**, exit 0 |
| Bridge sidecar | **37 passed, 2 known failures**, 157.60 s, exit 1 |
| `test_runtime_evidence_capture` (sampled) | 3 known failures (2 Windows mode-bit assertions, 1 pre-existing echo/runtime_degraded expectation), 97 passed |
| Real `~/.crusorai/sessions.db` before/after verification | **unchanged**: size 937,684,992; mtime_ns 1794499990403343400; sha256 `5fc06788a9ad9928dc5a127d4bb9fc0ec3b50706733722540e26df321bf4b4ec` |
| Real `runtime_events.db` | unchanged: 44,466,176 bytes; sha256 `d6e879…` |
| Real `verification.db` | unchanged: 835,584 bytes; sha256 `719066…` |

**Remaining limitations.** No VACUUM/prune/retention; 937 MB `sessions.db` and
426 `code_index_*.db` (~1.88 GB) remain; workspace-specific checkpoint placement
is not introduced. `test_runtime_evidence_capture` still has the 3 pre-existing
failures noted above. Bridge known failures (frame-window/signature pins) are
outside P1-A.

## 2026-11-12 — P1-A-R2 independent-review remediation

**Status:** DONE-VERIFIED (R2 scope); awaiting independent re-review. F-05
remains PARTIAL (retention/vacuum and workspace placement open).

**Trigger.** The independent P1-A review returned REJECT for acceptance. It
confirmed the lazy checkpointer design and identified two blocking real-DB
leaks (B-1, B-2) plus missing sidecar/invalid-path coverage (B-3).

**What changed.**

- `src/bridge/__main__.py` — `_prior_checkpoint_count` defaults to
  `checkpoint_db_path()`; explicit `db_path` remains an override.
- `src/tests/test_otel_tracing.py` — cleanup uses
  `chat_graph._CHECKPOINT_DB` + `SqliteSaver.delete_thread()`; refuses the real
  home DB; stale import-time comments removed.
- `src/tests/test_checkpoint_isolation.py` — 22 tests (was 15); full SHA-256 +
  existence/size/mtime for nine main/sidecar files plus journals; directory
  target, parent-is-file, nested-parent, writable-custom-location and
  fail-closed-no-fallback tests; B-2 cleanup regression.
- `src/tests/test_prior_checkpoint_isolation.py` (new, 4 tests) — bridge
  subprocess regressions for `session_create`/`session_resume`, custom
  checkpoint DB, custom session DB, no-home-fallback, real DB immutability.

**Evidence.**

| Check | Result |
|---|---|
| `pytest src/tests/test_checkpoint_isolation.py` | **22 passed**, 56.50 s, exit 0 |
| `pytest src/tests/test_prior_checkpoint_isolation.py` | **4 passed**, 26.10 s, exit 0 |
| P1-A targeted receipt (now 43 tests) | **43 passed**, 102.62 s, exit 0 |
| Final R2 receipt (43 + 4 B-1 bridge tests) | **47 passed**, 181.89 s, exit 0 |
| Persistence/restart subset | **72 passed**, 27.81 s, exit 0 |
| B-1 + B-2 + real-data re-run | **6 passed**, 40.26 s, exit 0; no real DB/sidecar/workspace changes |

**Sidecar evidence.** Full SHA-256 + size + mtime for `sessions.db`,
`runtime_events.db`, `verification.db` and every `-wal`/`-shm` plus the three
`-journal` paths were identical before/after the final 47-test run. The current
values are in `docs/CURRENT_STATE.md`. `verification.db-wal`/`-shm` and all
journals remain absent. All 61 workspace directories were unchanged.

**Documentation discrepancy (recorded, not rewritten).** The audit F-05 entry
previously said the core gate took 280.70 s; the measured P1-A run was 193.28 s.
R2 corrected the number and annotated the correction. The handoff §0 previously
said 365 passed; it now says 366, matching CURRENT_STATE, BUGS and the audit.

**Limitation.** During an early B-1 draft the bridge test omitted
`CRUSORAI_HOME`, so `session_resume` opened the real journal and changed only
`runtime_events.db-shm` mtime (content hash stayed `67dea1a5…`). The test was
corrected to pin `CRUSORAI_HOME`; the final run shows zero changes. The full
`test_otel_tracing.py` module was not executed in R2; the corrected cleanup is
covered by the new B-2 regression and should be exercised in re-review.

**Non-blocking review notes still open.**

- `src/tests/conftest.py` unconditionally overwrites `CRUSORAI_HOME`,
  `CRUSORAI_CHECKPOINT_HOME` and `CRUSORAI_SESSIONS_DB`; an external harness
  cannot choose its own runtime root. This is intentional for isolation but is
  not configurable.
- Setting both `CRUSORAI_CHECKPOINT_HOME` and `CRUSORAI_SESSIONS_DB`
  intentionally splits checkpoints from session rows; documented in D-05.
- `workspace_app_data_root()` now follows `CRUSORAI_HOME` (P1-A). Core tests
  pass, but it is a production path change beyond the checkpoint fix.

## 2026-11-12 — P1-A-R3 SQLite URI path correction

**Status:** DONE-VERIFIED (R3 scope); awaiting independent acceptance. F-05
remains PARTIAL (retention/vacuum and workspace placement open).

**Trigger.** The final independent review rejected P1-A on B-4: the bridge built
`f"file:{db}?mode=ro"` from an unescaped path, so a legal `#` in the checkpoint
path started a URI fragment. With intended DB 2 rows and a decoy at the
truncated path 1 row, `session_create` returned `prior_checkpoints = 1`.

**What changed.**

- `src/runtime/app_paths.py` — new `sqlite_readonly_uri(db_path)` returns
  `Path(db_path).resolve().as_uri() + "?mode=ro"`, preserving absolute path
  resolution and read-only mode while percent-encoding `#`, `?`, `%`, spaces
  and Unicode.
- `src/bridge/__main__.py` — `_prior_checkpoint_count` uses
  `sqlite_readonly_uri(db)`; timeout `2.0`, path precedence and the graph
  captured-path preference are unchanged.
- `src/tests/test_checkpoint_uri_isolation.py` (new, 7 tests) — actual bridge
  subprocess regressions for `#` (with a decoy at the truncated path), spaces,
  `%` and Unicode; URI assertions for `?` (actual `?` filename test runs on
  POSIX and is skipped on Windows, which forbids `?` in filenames); read-only
  write-rejection + hash-unchanged test.
- The lazy `_LazySqliteConnection` and all checkpoint storage architecture are
  unchanged.

**Evidence.**

| Check | Result |
|---|---|
| `pytest src/tests/test_checkpoint_uri_isolation.py` | **6 passed, 1 skipped**, 25.55 s, exit 0 |
| URI + prior-checkpoint + isolation suite | **32 passed, 1 skipped**, 109.47 s, exit 0 |
| `pytest src/tests/test_session_pipeline.py` | **7 passed**, 51.52 s, exit 0 |
| `pytest src/tests/test_otel_tracing.py` | **7 passed**, 8.96 s, exit 0 |
| B-4 repro (intended 2, pre-`#` decoy 1) | now reports **2**; old code reported 1 |
| Read-only probe | `DELETE` raises `OperationalError`; DB hash unchanged |
| Real DB/sidecars/workspaces | no changes across the verification run |

**Historical rejection preserved.** The final independent review's REJECT and
its B-4 evidence remain the record of why R3 exists; this section supersedes the
fix status only.

**Remaining limitations.** F-05 retention/vacuum and workspace placement remain
open. The literal `?` end-to-end bridge case cannot run on Windows because the
filesystem forbids `?`; the URI encoding assertion always runs and the
end-to-end case runs on POSIX. The R2 non-blocking notes (conftest overrides,
split checkpoint/session precedence, `workspace_app_data_root` behavior) remain.
