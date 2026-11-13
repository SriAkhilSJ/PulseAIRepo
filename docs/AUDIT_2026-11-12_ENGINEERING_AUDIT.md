# 2026-11-12 Engineering Audit — Findings Register

**Repository:** `SriAkhilSJ/PulseAIRepo`
**Branch:** `feat/prompt-cache-stabilization`
**HEAD at audit:** `fb5bd528b40933346c4004a1490154683dc0d40e`
**Audit date:** 2026-11-12
**Reconciled into canonical memory:** 2026-11-12 (documentation-only)
**Working tree at audit:** 262 entries (80 modified, 182 untracked, 0 staged)
**Working tree after reconciliation:** 264 (two documentation files added)
**Working tree after P1-A:** 269 (test isolation repair: 3 source/fixture files
modified, 1 test module added, memory updated)
**Method:** source inspection, git inspection, bounded test execution. No provider
calls, no Electron launch, no repair scripts, no git mutation.

> This file is the detailed, identifiable record of the 15 findings produced by
> the initial repository audit. `docs/BUGS_AND_LIMITATIONS.md` carries the
> canonical bug status and links back here. Do not delete a finding when it is
> fixed: change its **Status** and add the closing evidence (append-only truth).

---

## 1. How this register was produced

Read: `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`,
`docs/BUGS_AND_LIMITATIONS.md`, `docs/DECISIONS.md`, `docs/ROADMAP.md`,
`docs/phases/PHASE_TRACKER.md`, `docs/handoffs/LATEST_HANDOFF.md`, then the
actual implementation under `src/`, `desktop/vscode/src/vs/workbench/contrib/crusorai/`
and the test suite.

Commands run (all read-only; no source/config change):

| Command | Result | Exit |
|---|---|---|
| `git status --porcelain=v1` | 262 entries: 80 modified, 182 untracked, 0 staged, 0 deletions | 0 |
| `git diff --stat` | 80 files, +8,732 / −735 | 0 |
| `pytest --collect-only -q` | **4,953 collected, 3 collection errors** (14.8 s) | 1 |
| `pytest src/tests/test_security_containment.py -q` | **232 passed, 3 skipped** (32.57 s) | 0 |
| `pytest src/tests/test_bridge.py -q` | **2 failed, 37 passed** (140.33 s) | 1 |
| `pytest src/tests/test_agent_cards.py -q` | **1 failed, 10 passed** | 1 |
| `pytest test_plan_outcome_semantics + test_turn_card_association` | **29 passed** | 0 |
| `pytest test_workspace_discovery_phase2a + test_outside_workspace_access` | **26 passed** | 0 |
| `pytest src/tests/test_scope_fidelity.py -q` | **7 passed** (22.14 s) | 0 |
| `python scripts/agent_core_checkup.py` | **57 pass / 5 warn / 0 fail** | 0 |
| `python -c "import src.observability ..."` | resolves to the package; `record_turn_receipt` absent | n/a |

---

## 2. Status and severity legend

| Field | Values |
|---|---|
| Severity | CRITICAL, HIGH, MEDIUM, LOW, INFO |
| Status | OPEN, PARTIAL, FIXED, HISTORICAL, INHERENT |
| Evidence | VERIFIED-HEAD, VERIFIED-WORKTREE, VERIFIED-RUNTIME, DOCUMENTED, UNVERIFIED |

`VERIFIED-HEAD` means the statement was checked against `fb5bd528` plus the
working tree; where HEAD and the working tree differ the entry says which.

---

## 3. Findings

### F-01 — Engineering is generation+verification, not a tool-using agent

- **Severity:** CRITICAL
- **Status:** OPEN (narrowed by Phase 2A discovery)
- **Source files:**
  - `src/orchestration/model_adapter.py:806-916` (`execute_node` generate → validate → mutate)
  - `src/orchestration/model_adapter.py:1164-1288` (`_call_model_for_implementation`)
  - `src/orchestration/model_adapter.py:1330-1660` (`_dispatch_code_prompt`, the only paid path)
  - `src/orchestration/orchestrator.py:583-640` (`run_task_request` delegation)
  - `src/orchestration/contract.py:948-993` (target resolution + synthesis fallback)
  - `src/workspace/discovery.py` (read-only discovery, before planning only)
- **Evidence:** `grep 'bind_tools' src/orchestration/*.py` returns no matches. The
  2026-11-12 real-provider terminal run failed all three tasks: A lost its source
  node and its reply was rejected as a malformed code fence; B created
  `src/req_001_module.py`, `src/req_003_module.py`,
  `tests/test_req_001_module.py` instead of editing `mini_math`; C returned
  `BLOCKED` without running the failing tests. `contract.py:981-993` still falls
  back to `src/{requirement_id}_module.py` when no discovery evidence or
  synthesis key exists, and
  `src/tests/test_contract_assignment_reliability.py:66-70` asserts that
  fallback and passes.
- **Impact:** The flagship engineering workflow cannot inspect, edit surgically,
  run a diagnosis loop, or repair. Targets are guessed in an empty workspace.
  "COMPLETED/VERIFIED" is honest but weak.
- **Recommended next action:** Phase 2B: bind bounded read/list/search during
  generation, add targeted hunk editing, reject requirement-id targets
  unconditionally, and prove it with a graph-level test on a disposable project
  plus one authorized bounded run.
- **Cross-reference:** B-CORE-001, B-CORE-002, B-CORE-003, D-2026-11-12-01,
  D-2026-11-12-02.

---

### F-02 — The test baseline is uncollectable/red and not gated in CI

- **Severity:** HIGH
- **Status:** OPEN
- **Source files:**
  - `src/tests/test_financial_accounting_closure.py:25`
  - `src/tests/test_provider_usage_normalization.py:27`
  - `src/tests/test_observability.py:5`
  - `src/tests/test_bridge.py:98, 802`
  - `src/tests/test_agent_cards.py:47`
  - `.github/workflows/security-guard.yml:4-14`
  - `.github/workflows/e2e-core.yml:14-20`
- **Evidence:**
  - `pytest --collect-only -q` → 4,953 collected, **3 collection errors**:
    `ImportError: cannot import name 'deduplicate_streaming_usage' from
    'src.llm.factory'` (two modules) and `ImportError: cannot import name
    'record_turn_receipt' from 'src.observability'`.
  - `test_bridge.py`: `test_sidecar_hello_then_real_runtime_shape` and
    `test_autotitler_fires_once_after_a_full_exchange` fail (2/39).
  - `test_agent_cards.py::test_all_required_card_types_are_declared` fails
    because the working tree adds `thinking`, `read`, `search` to `CARD_TYPES`.
  - `security-guard.yml` only triggers on its own four files; a normal `src/**`
    change does not run the 235-test security suite.
  - `e2e-core.yml` and `verify-provider-key.yml` only run on `main`/`arena/**`
    pushes, so this branch has no real-provider CI evidence.
  - P1-A added 15 isolation tests: **4,968** collected, still **3 collection
    errors**; the P1-B fixes are unchanged.
- **Impact:** No trustworthy regression gate. Three modules cannot be collected;
  three known failures are hidden inside a "suite" that is not run in full.
- **Recommended next action:** Fix or delete the stale imports, update the two
  bridge pins and the card-type pin, add a full-suite `push` gate plus the
  security suite on `src/**`, and record the first full run with commit, count
  and exit code.
- **Cross-reference:** B-006, F-06.

---

### F-03 — Process execution is unsandboxed by default and inherits the full environment

- **Severity:** HIGH (defense-in-depth; the canonical graph currently blocks shell tools)
- **Status:** OPEN (mitigated by `_GRAPH_MUTATION_BLOCKED`)
- **Source files:**
  - `src/tools/terminal_tools.py:1089-1170` (`env = dict(os.environ)`, sandbox opt-in)
  - `src/orchestration/test_execution.py:242-261, 619-687` (raw `Popen`, real tests)
  - `src/graphs/chat_graph.py:1470-1478` (`_GRAPH_MUTATION_BLOCKED` includes shell tools)
  - `src/security/execution_broker.py` (only reached when `CRUSOR_SANDBOX_TERMINAL=1`)
- **Evidence:** `CRUSOR_SANDBOX_TERMINAL` defaults to `0`; the default path calls
  `subprocess.Popen(..., env=env)` with `dict(os.environ)` (which contains
  `CUSTOM_API_KEY` / `CRUSORAI_CHEAP_API_KEY`). Test execution also bypasses the
  broker (it does scrub `*_API_KEY`/`*_SECRET`/`*_TOKEN`/`*_PASSWORD` from the
  child env). `docs/ARCHITECTURE.md:206` claims the broker is the single
  chokepoint; the code does not.
- **Impact:** A future tool-policy change, a non-canonical entry point, or a
  command-running verification tool becomes local code execution plus secret
  exfiltration. The architecture claim is false today.
- **Recommended next action:** Route all process creation through
  `ExecutionBroker` by default, pass a scrubbed env allowlist, require approval
  for executing model-generated tests, and add negative tests proving the key is
  absent from the child env.
- **Cross-reference:** B-008, B-016, B-017.

---

### F-04 — Product default auto-approves low-risk mutations; approval evidence came from an `ask` harness

- **Severity:** HIGH
- **Status:** OPEN
- **Source files:**
  - `src/bridge/__main__.py:1671-1675` (default `workspace_session`)
  - `src/orchestration/approval_gateway.py:96-112` (`needs_approval`)
  - `src/orchestration/models.py:321` (`risk_level` default `"LOW"`)
  - `desktop/vscode/scripts/accept-crusorai-*.mjs` (all set `ask`)
- **Evidence:** the bridge comment says "Interactive IDE sessions default to
  ask" but the code defaults `CRUSORAI_BRIDGE_APPROVAL_POLICY` to
  `workspace_session`; under that policy a LOW-risk write is granted without a
  human (`approval_gateway.py:215-218`). Every Electron acceptance script
  explicitly sets `CRUSORAI_BRIDGE_APPROVAL_POLICY: 'ask'`, so the approval-dock
  evidence does not represent the shipped default.
- **Impact:** Workspace writes can land with no visible approval in the normal
  desktop launch; the UI evidence overstates safety.
- **Recommended next action:** default to `ask`; make the policy an explicit,
  persisted user setting; test that the default path emits
  `tool.approval.request` for a LOW-risk write.
- **Cross-reference:** B-DESK-005, B-015.

---

### F-05 — Checkpoint persistence was hardcoded, import-time and unbounded

- **Severity:** MEDIUM-HIGH
- **Status:** **PARTIAL — P1-A fixed path/import isolation; R2 closed the
  bridge/OTel leaks; R3 fixed SQLite URI path encoding (2026-11-12)**;
  retention/vacuum and workspace-specific placement remain open
- **Source files:**
  - `src/runtime/app_paths.py:42-92` (`session_db_path`, `checkpoint_db_path`,
    `sqlite_readonly_uri`)
  - `src/runtime/session_store.py:46-52` (shared path resolution)
  - `src/graphs/chat_graph.py:8268-8333` (`_LazySqliteConnection`, lazy saver)
  - `src/tests/conftest.py:20-30` (test home / sessions DB / checkpoint home)
  - `src/tests/test_checkpoint_isolation.py` (22 regression tests)
  - `src/tests/test_prior_checkpoint_isolation.py` (4 bridge B-1 tests)
  - `src/tests/test_checkpoint_uri_isolation.py` (7 B-4 URI tests)
  - `src/bridge/__main__.py:176-203` (`_prior_checkpoint_count` path contract)
  - `src/tests/test_otel_tracing.py:204-241` (cleanup targets the graph DB)
- **Evidence:**
  - **Before:** `_CHECKPOINT_DB` opened `~/.crusorai/sessions.db` at import,
    ignored `CRUSORAI_HOME`/`CRUSORAI_SESSIONS_DB`/`CRUSORAI_CHECKPOINT_HOME`,
    and test runs changed the real DB (P1 observed ~0.99 MB growth; P1-A runs
    changed it again before the fixture repair).
  - **After:** `checkpoint_db_path()` resolves
    `CRUSORAI_CHECKPOINT_DB` > `CRUSORAI_CHECKPOINT_HOME` >
    `CRUSORAI_SESSIONS_DB`/`_PATH` > `CRUSORAI_HOME` >
    `~/.crusorai/sessions.db`; the connection opens on the first checkpoint
    operation, not at import. `conftest.py` pins
    `CRUSORAI_HOME`, `CRUSORAI_SESSIONS_DB` and `CRUSORAI_CHECKPOINT_HOME` to a
    throwaway runtime root.
  - `pytest src/tests/test_checkpoint_isolation.py` → **22 passed** (56.50 s,
    exit 0), including: import creates no DB; path precedence; real
    `SqliteSaver` checkpoint tables; checkpoint survives a second process; all
    nine real `~/.crusorai/{sessions,runtime_events,verification}.db` main and
    `-wal`/`-shm` files (plus journals) unchanged by full SHA-256 + size/mtime;
    invalid paths fail closed.
  - `pytest src/tests/test_prior_checkpoint_isolation.py` → **4 passed**
    (26.10 s, exit 0): `session_create`/`session_resume` read the custom
    checkpoint/session DB, a missing override reports zero instead of falling
    back to home, and the real DB/sidecars stay unchanged.
  - Core gate with the new file: **366 passed, 2 skipped, 1 xfailed** (193.28 s,
    exit 0). *Correction (R2, 2026-11-12): an earlier transcription said
    280.70 s; the measured P1-A run was 193.28 s.*
  - P1-A-R2 targeted receipt: **47 passed**, 181.89 s, exit 0 (22 isolation +
    4 B-1 bridge + 11 plan completion + 1 workspace isolation + 2 bridge
    transport + 7 session pipeline). Persistence/restart subset: **72 passed**,
    27.81 s.
  - P1-A-R3 URI regressions: **6 passed, 1 skipped**, 25.55 s, exit 0. The
    skipped case is a literal `?` in a filename, which Windows cannot create;
    the URI-encoding assertion still runs and the end-to-end case runs on POSIX.
    Combined R3 verification: URI + prior-checkpoint + isolation **32 passed, 1
    skipped**, 109.47 s; session pipeline **7 passed**, 51.52 s; OTel **7
    passed**, 8.96 s.
  - R3 repro: intended DB with 2 rows and a decoy at the pre-`#` truncated path
    with 1 row now reports `prior_checkpoints = 2`. The old raw
    `f"file:{db}?mode=ro"` returned 1. Read-only mode rejects writes and leaves
    the selected database hash unchanged.
  - Final real-data before/after: no changes to the nine main/sidecar files,
    three journal paths or 61 workspace directories (full SHA-256 + size +
    mtime).
- **Impact:** Tests can no longer create/open/write the developer's real
  session, journal or verification DB through the graph/session/runtime paths.
  R2 fixed the bridge's `prior_checkpoints` read and the OTel test cleanup,
  which previously opened/deleted against the real `sessions.db`. R3 encodes the
  checkpoint path as an absolute SQLite file URI, so `#`, `?`, `%`, spaces and
  Unicode cannot truncate the path or select another database. Invalid
  checkpoint paths fail closed (`sqlite3.OperationalError` for a directory
  target, `OSError`/`FileExistsError` for a file parent) with no home fallback.
  The 937 MB file and its 426 index DBs are still unmanaged: no retention,
  vacuum or workspace-level placement.
- **Recommended next action:** add a bounded retention/vacuum policy and decide
  whether checkpoints should be per-workspace; keep the env-override contract
  and the lazy-open test.
- **Cross-reference:** B-010, B-019, B-1/B-2 (P1-A independent review),
  `docs/CURRENT_STATE.md` P1-A/P1-A-R2 section.


---

### F-06 — `src/observability` package shadows `src/observability.py`; turn receipts are dead

- **Severity:** MEDIUM
- **Status:** OPEN
- **Source files:**
  - `src/observability.py:47` (`record_turn_receipt`)
  - `src/observability/__init__.py` (package without that export)
  - `src/graphs/chat_graph.py:3735-3753` (import inside `try/except: pass`)
  - `src/enterprise/monitor.py:37-39`
- **Evidence:** `import src.observability` resolves to
  `src/observability/__init__.py`, and `hasattr(..., 'record_turn_receipt')` is
  `False`. `test_observability.py` cannot be collected. The call site swallows
  the `ImportError`, so no runtime error is visible.
- **Impact:** Per-turn observability receipts are never recorded; the
  observability test module is red at collection; dashboards built on the stream
  are empty.
- **Recommended next action:** move `record_turn_receipt` into the package and
  re-export it (or rename the module), remove the blanket swallow, add an
  import/behaviour test.
- **Cross-reference:** F-02.

---

### F-07 — Identity/RBAC is wired only as a hard-coded superadmin

- **Severity:** MEDIUM
- **Status:** PARTIAL
- **Source files:** `src/orchestration/model_adapter.py:837-851`;
  `src/identity/tool_authorizer.py`
- **Evidence:** each engineering node builds
  `User(..., is_superadmin=True)` and calls `authorize_tool_call("write_file", ...)`.
  There is no session principal and no authorizer reference in
  `src/bridge/__main__.py` or `src/graphs/chat_graph.py`.
- **Impact:** RBAC cannot deny any live tool call. B-002's "not enforced" is
  right; "not wired" is now inaccurate.
- **Recommended next action:** derive the principal from session identity and
  tenancy, remove the superadmin default, and add tests proving a non-owner role
  is denied.
- **Cross-reference:** B-002, ADR-026/027.

---

### F-08 — FinOps under-counts cancellation and asserts pricing provenance

- **Severity:** MEDIUM
- **Status:** OPEN
- **Source files:**
  - `src/orchestration/model_adapter.py:685-691, 1575-1590`
  - `src/orchestration/finops_governor.py:360-372`
  - `src/finops/pricing_registry.py:169-174`
  - `src/finops/invocation_context.py:107-110`
- **Evidence:** `TurnCancelledError` is treated as pre-dispatch/unbilled, so a
  Stop during streaming releases the reservation and records zero usage. Model
  pricing for `z-ai/glm-5.3-flash` is hardcoded with
  `VerificationStatus.VERIFIED` and source `velona_catalog`; no verification
  artifact or date is in the repo. Cost state spans per-task SQLite,
  `*_finops.json` and a workspace JSONL ledger with no single transaction.
- **Impact:** Cost-per-task and budget enforcement can under-report real spend;
  "verified" pricing is an assertion.
- **Recommended next action:** classify post-dispatch cancellation as
  `uncertain` with measured/estimated usage, record pricing provenance
  (source + verified_at + evidence path), and define one authoritative ledger
  with reconciliation.
- **Cross-reference:** B-010, B-012, B-025.

---

### F-09 — Verification strength depends on a prompt-derived `testing_required`

- **Severity:** MEDIUM
- **Status:** OPEN
- **Source files:** `src/verification/requirement_verifier.py:195-240`;
  `src/orchestration/orchestrator.py:1412, 1724-1739`
- **Evidence:** `require_test_evidence=testing_required`. When a task is not
  classified as test-required, a requirement can reach `VERIFIED` from file
  presence + satisfied criteria with no executed test (`:225-233`), despite the
  module docstring saying otherwise (`:6-7`).
- **Impact:** Code tasks that do not explicitly mention tests can be reported as
  `VERIFIED` on structural evidence alone.
- **Recommended next action:** derive `testing_required` from contract file
  roles (any SOURCE ⇒ tests required, or `NOT_VERIFIED`), and surface the rule
  in the delivery contract.
- **Cross-reference:** ADR-009, F-01.

---

### F-10 — Non-desktop entry points bypass the canonical runtime contract

- **Severity:** MEDIUM
- **Status:** OPEN
- **Source files:** `src/dashboard_server.py:162-171`; `src/main.py:241-246`;
  `src/graphs/chat_graph.py:5232, 6774, 8423-8425`
- **Evidence:** dashboard and CLI call `stream_agent` without
  `canonical_runtime=True`. `_is_engineering_turn` then returns `False` (no
  engineering delegation) and `_authorize_mutations` returns early (no
  digest-bound authorizations).
- **Impact:** Two products with different capability and mutation semantics; the
  dashboard/CLI can behave differently from the IDE.
- **Recommended next action:** make `canonical_runtime` the only interactive
  contract (or gate it explicitly at every entry) and add an entry-point parity
  test.
- **Cross-reference:** ADR-026.

---

### F-11 — Generated engineering artifacts contaminate the product source tree

- **Severity:** MEDIUM
- **Status:** OPEN
- **Source files:** `src/req_001_module.py`, `src/req_002_module.py` (tracked),
  `src/req_003_module.py`, `src/req_004_module.py`, `src/req_005_module.py`
  (untracked); 471 files at repo root
- **Evidence:** `req_001/002` were added in `0b0e799d` and now carry +2,549
  uncommitted lines. The five modules are ~285 KB. `test_scope_fidelity.py` and
  `test_contract_assignment_reliability.py` reference the requirement-id
  filenames. 81 untracked root reports and 62 untracked diagnostics directories
  exist.
- **Impact:** `src/` is polluted with non-product code; tests encode the
  contamination; the audit surface is huge and error-prone.
- **Recommended next action:** quarantine/delete the generated modules with owner
  approval, decouple tests from the filenames, add a hygiene check rejecting
  `src/req_*_module.py`.
- **Cross-reference:** F-01.

---

### F-12 — Repository memory contradicted code (corrected by this reconciliation)

- **Severity:** MEDIUM (decision risk)
- **Status:** FIXED for the 2026-11-12 audit snapshot (this documentation phase)
- **Source files:** `AGENTS.md` §4.3/§11; `docs/CURRENT_STATE.md`;
  `docs/ARCHITECTURE.md`; `docs/BUGS_AND_LIMITATIONS.md`;
  `docs/phases/PHASE_TRACKER.md`; `docs/ROADMAP.md`;
  `docs/handoffs/LATEST_HANDOFF.md`; `docs/DECISIONS.md`
- **Evidence:** pre-reconciliation claims included 175/195/211/247 dirty
  entries; "HEAD bypasses the broker"; B-DESK-001 as an active blocker; the
  bridge routing agent/plan to the orchestrator; "334 test modules"; the broker
  as the single process chokepoint; `workspace_session` described as `ask`; and
  requirement-id synthesis described as impossible. Each was checked against
  `fb5bd528` + working tree and corrected in this reconciliation.
- **Impact (before):** a future session would fix already-fixed issues and miss
  the real ones.
- **Recommended next action:** keep the audit baseline linked from AGENTS.md;
  update findings in place rather than rewriting history.
- **Cross-reference:** §4 of this file, `docs/BUGS_AND_LIMITATIONS.md` §3.

---

### F-13 — Engineering streaming is internal-only; real-provider streaming is unmeasured

- **Severity:** LOW-MEDIUM
- **Status:** PARTIAL
- **Source files:** `src/graphs/chat_graph.py:5363-5387`;
  `src/orchestration/generation_progress.py`;
  `CRUSOR_P1A_ENGINEERING_STREAMING_REPORT.md`
- **Evidence:** engineering model text is never painted; only elapsed time,
  characters received and target file are sent on the activity card. Chat tokens
  are streamed. Real-provider chunk sizes and first-token latency are not
  measured; the user previously judged real-provider UI streaming unacceptable.
- **Impact:** Product-perception and latency-SLO risk.
- **Recommended next action:** define the intended engineering streaming
  contract, then measure it with one authorized bounded run.
- **Cross-reference:** B-LIVE-003.

---

### F-14 — Guard/style drift: `sys.platform` in path safety

- **Severity:** LOW
- **Status:** OPEN
- **Source files:** `src/workspace/path_safety.py:140-154`
- **Evidence:** uses `sys.platform == "win32"`; `AGENTS.md` requires
  `os.name == "nt"` in new code to avoid import-time `platform.system()` spawns.
- **Impact:** Cross-platform packaging/import purity risk; low.
- **Recommended next action:** normalise when the file is next touched; add to
  the style checklist.
- **Cross-reference:** B-007.

---

### F-15 — 55 stashes and 41 branches carry unowned work

- **Severity:** INFO
- **Status:** OPEN / OWNER DECISION
- **Source files:** git refs only
- **Evidence:** `git stash list` → 55 entries (mostly old `arena/*` pre-pull
  diagnostics); one `On main: untrack out/ slice`. `git branch -a` → 41.
- **Impact:** Cleanup/disposition risk; no stash is part of this audit.
- **Recommended next action:** owner inventory; do not drop/apply without
  explicit instruction.
- **Cross-reference:** `docs/ROADMAP.md` N-2.

---

## 4. Summary matrix

| ID | Severity | Status | One-line |
|---|---|---|---|
| F-01 | CRITICAL | OPEN | Engineering binds no tools; whole-file regeneration |
| F-02 | HIGH | OPEN | 3 collection errors, 3 known failures, no full CI gate |
| F-03 | HIGH | OPEN | Unsandboxed exec + full env by default |
| F-04 | HIGH | OPEN | Product default auto-approves low-risk writes |
| F-05 | MEDIUM-HIGH | **PARTIAL (P1-A + R2 + R3)** | Checkpoint path/import/bridge/OTel/URI leaks fixed; retention/vacuum open |
| F-06 | MEDIUM | OPEN | `src/observability` package shadows the module; receipts dead |
| F-07 | MEDIUM | PARTIAL | RBAC wired with a synthetic superadmin |
| F-08 | MEDIUM | OPEN | Cancellation under-counts; pricing provenance asserted |
| F-09 | MEDIUM | OPEN | `VERIFIED` without tests when `testing_required` is false |
| F-10 | MEDIUM | OPEN | Dashboard/CLI bypass canonical runtime |
| F-11 | MEDIUM | OPEN | Generated `src/req_*_module.py` contamination |
| F-12 | MEDIUM | FIXED (docs) | Memory contradicted code; reconciled here |
| F-13 | LOW-MEDIUM | PARTIAL | Engineering streaming internal; real latency unmeasured |
| F-14 | LOW | OPEN | `sys.platform` guard drift |
| F-15 | INFO | OPEN | 55 stashes / 41 branches need owner disposition |

---

## 5. Update protocol

1. A finding is closed only with a command, result and exit code (plus CI run/job
   IDs where applicable), recorded in the entry.
2. Change **Status**, never delete the finding.
3. Keep the F-ID stable; new findings get F-16, F-17, …
4. `docs/BUGS_AND_LIMITATIONS.md` is the canonical bug status; this register is
   the detailed evidence trail. If they disagree, the code wins and the
   disagreement is itself a finding.
5. Do not edit `docs/production/**` historical evidence.

---

## 6. Related canonical memory

- `AGENTS.md` — session protocol and current constraints
- `docs/CURRENT_STATE.md` — status, tests, working tree
- `docs/ARCHITECTURE.md` — actual runtime ownership
- `docs/BUGS_AND_LIMITATIONS.md` — bug status and documentation discrepancies
- `docs/DECISIONS.md` — D-2026-11-12-01/02 and the reconciliation entry
- `docs/ROADMAP.md` — corrected priorities
- `docs/phases/PHASE_TRACKER.md` — phase status and open gates
- `docs/handoffs/LATEST_HANDOFF.md` — next-session entry point
