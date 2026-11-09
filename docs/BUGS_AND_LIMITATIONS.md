# CrusorAI - Bugs, Limitations, and Discrepancies

**Snapshot:** `b72d04c57fd7b807df78234923e2a8b51cdce042` (2026-11-08)
**Rule:** every entry names the evidence and whether it was verified in this
audit. "Verified" means inspected in source or observed in a recorded run; it
does not mean the bug is fixed.

---

## 1. Severity and status legend

| Field | Values |
|---|---|
| Severity | CRITICAL, HIGH, MEDIUM, LOW |
| Status | OPEN, PARTIAL, HISTORICAL, INHERENT |
| Evidence | VERIFIED-HEAD, VERIFIED-WORKTREE, DOCUMENTED, UNVERIFIED |

"VERIFIED-HEAD" means the behaviour exists in commit `b72d04c5`.
"VERIFIED-WORKTREE" means the working copy differs and the statement applies to
the on-disk file only.

## 2. Current limitations

### B-DESK-001 - Agent Core graph cannot start: missing compaction helpers

- **Severity:** CRITICAL
- **Status:** OPEN at HEAD (`638d4151`)
- **Evidence:** VERIFIED-HEAD (import error in a live bridge turn)

`src/context/history_shaper.py:159-165` imports
`compact_assistant_tool_call_arguments` and
`transform_completed_tool_receipts` from `src.context.compaction`. Neither name
exists anywhere in `src`, and `git log -S "def compact_assistant_tool_call_arguments"`
returns nothing. `src/tests/test_eager_history_compaction.py` fails at
collection for the same reason.

Consequences: `CRUSORAI_ORCHESTRATOR_ENGINE=legacy` (the real Agent Core graph)
fails on the first ai-node call with
`ImportError: cannot import name 'compact_assistant_tool_call_arguments'`.
Real tool approval, real mutation, and durable transcript replay are blocked.
The default orchestrator path avoids the import but does not receive
`approval_channel`/`approval_policy`, so it emits no `safety_request`.
Evidence: `bench-results/phase-2-desktop-qualification-r2/approval-execution.txt`.

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

### B-001 - Interactive file tools bypass the mutation broker at HEAD

- **Severity:** CRITICAL
- **Status:** OPEN at HEAD; PARTIAL in the uncommitted working tree
- **Evidence:** VERIFIED-HEAD and VERIFIED-WORKTREE

`src/tools/file_tools.py` at HEAD contains no `WorkspaceMutationBroker` import
or call (verified with `git show HEAD:src/tools/file_tools.py`). The working copy
contains six broker references and calls `create_file`, `copy_file`, and
`modify_file` through the broker.

Consequences at HEAD: no ownership check, no snapshot/rollback, no hash receipt
for interactive writes. The working-tree fix is **not committed** and must not be
described as shipped. Decide whether to commit it as a separate reviewed change.

### B-002 - Identity and RBAC are not enforced in the live tool path

- **Severity:** HIGH
- **Status:** OPEN
- **Evidence:** VERIFIED-HEAD

`IdentityAwareToolAuthorizer` exists in `src/identity/tool_authorizer.py` and is
exercised by Phase 10/12 tests, but a repository-wide search finds no reference
in `src/bridge/__main__.py` or `src/graphs/chat_graph.py`. Tool calls therefore
run with ambient process permissions rather than role-derived authorization.

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
- **Status:** OPEN
- **Evidence:** DOCUMENTED (`PHASE_12_1_3_FINAL_VERDICT.md`)

The Phase 12.1.3 verdict marks interactive visual workbench display as
**NOT VERIFIED** because the automation host is headless. Electron runtime and
main-process linkage were qualified; a human-visible GUI run was not.

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

### B-006 - Full test suite has a historical 25-failure baseline

- **Severity:** HIGH
- **Status:** OPEN / UNVERIFIED ON CURRENT HEAD
- **Evidence:** DOCUMENTED (`README.md`, 2026-10-27)

The last recorded full-suite result is 2,802 passed, 25 failed, 26 skipped, and
1 xfailed, with the same 25 failing identities as the pre-merge baseline. That is
not a clean suite. Phase 12.1.3 separately recorded 395/395 on its narrower
regression set. Neither number replaces a fresh full run on `b72d04c5`.

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
- **Status:** INHERENT / MONITORED
- **Evidence:** VERIFIED-HEAD

The bridge defaults to `EngineeringExecutionOrchestrator` for agent/plan modes,
with a `legacy` graph path selectable by `CRUSORAI_ORCHESTRATOR_ENGINE`. Two
paths mean gates, budgets, and tool policy can drift unless both are tested.

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

## 3. Documentation-versus-implementation discrepancies

These are contradictions found during this audit. The source code is treated as
current truth.

| Document claim | Actual state | Resolution |
|---|---|---|
| `REMAINING_LIMITATIONS.md` #1: the Phase 11 stack is "completely uncallable from the desktop" because the bridge directly calls `stream_agent`. | At HEAD the bridge routes agent/plan turns to `EngineeringExecutionOrchestrator` (default) and calls `orch.run_task` (`src/bridge/__main__.py`). | The document is outdated. The remaining true gap is UI/protocol rendering (B-003), not zero wiring. |
| `REMAINING_LIMITATIONS.md` #5: the orchestrator's `default_executor` writes hardcoded stub functions. | At HEAD `default_executor` calls `self.model_adapter.execute_node(...)` (`src/orchestration/orchestrator.py`). | The document is outdated. Verify the adapter path per provider before claiming full autonomy. |
| `README.md`: full suite "2,802 passed, 25 failed" and "FAIL / not revalidated". | This is a 2026-10-27 snapshot. No newer full-suite run is recorded in this audit. | Keep as historical evidence; do not present as current green. |
| `PHASE_12_1_3_FINAL_VERDICT.md`: "PRODUCT_QUALIFIED_WITH_LIMITATIONS". | The same document marks GUI as NOT VERIFIED, provider as DETERMINISTIC_PROVIDER_ONLY, and the task as DETERMINISTIC_QUALIFIED. | Quote the qualifiers with the verdict; do not shorten it to "qualified". |
| Root `REMAINING_LIMITATIONS.md` #2: file tools bypass the broker. | True at HEAD; the working tree contains an uncommitted fix. | Accurate for HEAD. Do not describe the fix as shipped (B-001). |
| `README.md` says the desktop and runtime are production-hardened. | Security phases 0-1.3.1 hardened import/AppContainer guards; live acceptance and GUI remain unverified. | Scope "hardened" to the specific evidence. |

## 4. Unknown or unverified

1. Whether the uncommitted mutation-broker wiring is intended to ship.
2. Whether the current HEAD launches a visible desktop GUI on a headed host.
3. Whether the 25 historical test failures still reproduce on HEAD.
4. Whether the orchestrator path produces real code for every provider (adapter
   coverage is provider-specific).
5. Current provider credit/availability and the state of the historical
   reservation.
6. Whether the Phase 11 intelligence stack is exercised end-to-end from the
   desktop, beyond being constructed and called by the bridge.

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
```

Record the command, platform, commit, and exit code when closing an entry.
