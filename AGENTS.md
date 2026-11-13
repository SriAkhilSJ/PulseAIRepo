# AGENTS.md - Permanent Instructions for AI Coding Sessions

This file is the entry point for every AI session working in this repository.
It is not optional context. Read it before planning or editing.

**Repository:** `SriAkhilSJ/PulseAIRepo`
**Primary branch in active use:** `feat/prompt-cache-stabilization`
**Memory snapshot:** 2026-11-12, HEAD `fb5bd528b40933346c4004a1490154683dc0d40e` (working tree uncommitted)
**Audit baseline:** 2026-11-12 — the verified condition of record is
`docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` (findings F-01…F-15). Cite it
instead of reconstructing state from narrative reports.

---

## 1. Precedence

When sources disagree, use this order:

1. Actual source code at the current commit.
2. A fresh command/test result from this session.
3. Evidence documents with a commit SHA and command (`docs/production/`,
   `docs/phases/`, `diagnostics/`).
4. `docs/CURRENT_STATE.md`, `docs/BUGS_AND_LIMITATIONS.md`,
   `docs/handoffs/LATEST_HANDOFF.md`.
5. Narrative documents (`README.md`, root `PHASE_*.md`, audits).
6. Assumptions (never present these as facts).

If code and documentation disagree, record the discrepancy in
`docs/BUGS_AND_LIMITATIONS.md`; do not silently "fix" history.

## 2. Mandatory read-first protocol

Before implementation, read in this order:

1. `AGENTS.md` (this file)
2. `docs/CURRENT_STATE.md`
3. `docs/ARCHITECTURE.md`
4. `docs/handoffs/LATEST_HANDOFF.md`
5. `docs/BUGS_AND_LIMITATIONS.md`
6. `docs/phases/PHASE_TRACKER.md`
7. `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` (verified condition and F-01…F-15)

Then inspect the specific source files for the task. Do not propose changes to
code you have not read.

Also check:

```bash
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git status --short
git log --oneline -10
```

Compare the dirty-entry count with the handoff. If it changed unexpectedly, stop
and ask before proceeding.

## 3. Repository map

| Path | What it is |
|---|---|
| `desktop/vscode/` | Vendored Code OSS fork, Electron app, Crusor workbench contribution. |
| `desktop/vscode/src/vs/workbench/contrib/crusorai/` | All first-party Crusor UI/host code. |
| `src/bridge/` | Python engine entry point and protocol v2. |
| `src/graphs/` | LangGraph turn graph, gates, budgets, state. |
| `src/orchestration/` | Engineering orchestrator, scheduler, FinOps governor. |
| `src/context/` | Context engine, layers, compaction, memory, token budgets. |
| `src/llm/` | Provider factory, guards, retries, streaming. |
| `src/tools/` | Agent tools and toolsets. |
| `src/security/` | Execution broker, sandbox backends, MCP/browser security. |
| `src/identity/` | Auth, roles, tenancy, audit, tool authorizer. |
| `src/verification/` | Completion/quality/security/requirement verifiers. |
| `src/runtime/` | Persistence, sessions, identity, evidence, recovery, tracing. |
| `src/targets/` | Multi-platform detection/build/verification. |
| `src/intelligence/`, `src/production/` | Requirements/architecture intelligence and production readiness. |
| `src/tests/` | 363 pytest modules; the main regression surface. |
| `scripts/` | Checkup, evidence, build, protocol generation, diagnostics. |
| `docs/production/` | Phase evidence with commits, commands, and conclusions. |
| `docs/` (new memory layer) | Current truth, architecture, decisions, bugs, roadmap, phases, handoffs. |
| `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` | Verified 2026-11-12 condition and findings F-01…F-15 (append-only evidence). |
| `diagnostics/`, `bench-results/`, `benchmarks/` | Historical run evidence. |
| `skills/` | Bundled agent skills. |
| `apps/` | Example/generated apps (not the product core). |

## 4. Hard safety invariants

These rules are not negotiable:

1. Never run `git reset`, `git clean`, `git stash`, `git rebase`, or
   `git push --force` in this repository unless the owner explicitly requests it
   for a named purpose.
2. Never run `git add .` or `git add -A`. Stage only named files.
3. The working tree contains pre-existing user work. At the 2026-11-08 snapshot
   it was 175 entries (34 modified tracked + 141 untracked). At the verified
   2026-11-12 audit it was **262 entries** (80 modified tracked + 182 untracked,
   zero staged, zero deletions); the documentation reconciliation, P1-A
   isolation repair, P1-A-R2 remediation and P1-A-R3 URI correction bring the
   current count to **272** (84 modified, 188 untracked). Do not overwrite,
   revert, or commit those files. Re-count before and after every task and
   report the delta.
4. Do not modify application source, dependencies, schemas, or configuration
   during a documentation-only task.
5. Do not execute repair scripts, `runner.exe`, Windows ACL changes, Electron
   launches, provider calls, or database writes unless the task explicitly
   authorizes them and the owner confirms.
6. Do not install dependencies for a documentation task. For code tasks, ask
   before changing the environment.
7. Do not commit or push without permission.
8. Never claim "done" without a command, exit code, and (where applicable) CI
   run evidence.
9. Never mark an unfinished item complete. Preserve failures as failures.
10. Do not delete existing documentation. Supersede it and link forward.

## 5. Truth rules

- **HEAD is canonical.** Find it with `git rev-parse HEAD`. A file on disk that
  differs from HEAD is uncommitted work, not shipped behaviour.
- **Verify, do not inherit.** A README claim is a lead, not proof. Open the file,
  run the test, or cite the evidence document.
- **Distinguish** "verified now", "recorded earlier", and "assumed".
- **Record receipts.** For every completed task, capture: commit SHA, command,
  platform, result, exit code, CI run/job IDs, and limitations.
- **No invented details.** If a provider, endpoint, schema, or deployment is not
  in the repo, say it is unknown.

## 6. Before implementation

Complete this checklist and put it in your working notes:

- [ ] Task scope and explicit non-actions written.
- [ ] Starting HEAD recorded and matched to origin.
- [ ] Dirty tree counted; named files that must not be touched.
- [ ] Relevant source files read (not just docs).
- [ ] Existing tests for the area identified.
- [ ] Verification commands chosen.
- [ ] Rollback/containment understood.
- [ ] For security work: negative/adversarial tests planned.
- [ ] For docs work: sources and evidence locations identified.

## 7. During implementation

- Keep the change minimal and consistent with surrounding code.
- Do not mix unrelated fixes into one phase.
- Do not reformat entire files.
- Preserve public contracts unless the task explicitly changes them.
- Add tests for behaviour changes; for guards, add tests that prove rejection.
- Prefer failing closed when a security decision is ambiguous.
- Do not weaken an existing security test to make CI pass. Fix the environment
  or the implementation, and document the reason.

### Windows / cross-platform notes

- The local `.venv` is Python 3.14.4.
- The security CI runs Python 3.14 because CPython <= 3.12 on Windows spawns
  `cmd /c ver` through `platform.system()`.
- Use `os.name == "nt"` instead of `platform.system()` in new code.
- Windows temp paths and drive letters (checkout on `D:`, temp on `C:`) cause
  cross-drive test skips; do not treat a skip as a failure.

## 8. Verification commands

Run what the task requires. Common baseline:

```powershell
# Parse changed Python files
.\.venv\Scripts\python.exe -c "import ast,pathlib,sys; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in sys.argv[1:]]; print('AST OK')" <files>

# Security containment suite
.\.venv\Scripts\python.exe -m pytest src/tests/test_security_containment.py -q

# Guarded import surface
.\.venv\Scripts\python.exe -m pytest src/tests/test_security_containment.py::test_full_guarded_import_surface -q

# Agent-core checkup
.\.venv\Scripts\python.exe scripts/agent_core_checkup.py

# Checkup regression suite
.\.venv\Scripts\python.exe -m pytest src/tests/test_agent_core_checkup.py -q
```

CI evidence:

```bash
gh run list --repo SriAkhilSJ/PulseAIRepo --commit <sha>
gh run view <run-id> --repo SriAkhilSJ/PulseAIRepo --json jobs
gh run view --repo SriAkhilSJ/PulseAIRepo --job <job-id> --log
```

Record the actual numbers. "Tests pass" without a count and exit code is not
evidence.

## 9. After implementation (mandatory memory update)

Update these files after verified work:

| File | What to update |
|---|---|
| `docs/CURRENT_STATE.md` | Status, commit, what changed, what remains, test results. |
| `docs/phases/PHASE_TRACKER.md` | Phase status, acceptance criteria, run/job IDs. |
| `docs/DECISIONS.md` | Any new architectural decision, with rationale and consequences. |
| `docs/BUGS_AND_LIMITATIONS.md` | New/fixed limitations and documentation discrepancies. |
| `docs/ROADMAP.md` | Move completed items; add newly discovered work. |
| `docs/handoffs/LATEST_HANDOFF.md` | Current state, next task, constraints, landmines. |
| `docs/ARCHITECTURE.md` | Only if the actual architecture changed. |
| `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` | Close/annotate findings with a command, result and exit code; never delete a finding. |
| `docs/PROJECT_MASTER.md` | Only if scope or product definition changed. |

Then archive the prior handoff under `docs/handoffs/HISTORY/` per its README.

Do not edit `docs/production/phase-*` evidence retroactively. Add a new phase
document or a superseding note.

## 10. Phase discipline

Every phase must state:

1. Starting HEAD and branch.
2. Goal and explicit non-actions.
3. Files allowed to change.
4. Tests to run and expected results.
5. CI coverage and platforms.
6. Known risks and rollback.
7. Final report: start/implementation/final SHAs, changed files, test results,
   CI run/job IDs, limitations, and confirmation that pre-existing dirty entries
   were preserved.

Do not start the next phase until the current one is reviewed or explicitly
accepted.

## 11. Current constraints (2026-11-09)

- Phase 1.4 is **WINDOWS SECURITY QUALIFIED** for Windows 11 + Python 3.11/3.14.
- Phase 2 r1/r2 are complete at **DESKTOP_PARTIAL**; Phase 3.1 wired the default
  orchestrator to the shared ApprovalQueue (`efda16c9`, bounded PASS); Phase
  3.2 closed the eight Phase 11.6 contract failures (`7879e066`, bounded PASS;
  full file 44/44).
- **B-DESK-001 is FIXED (verified 2026-11-12).** `src/context/compaction.py`
  now exports `compact_assistant_tool_call_arguments` and
  `transform_completed_tool_receipts`, and `stream_agent` imports/runs. Do not
  repeat the old "graph cannot start" claim; audit F-12 covers the stale text.
- **B-DESK-002:** the Crusor pane ignores the built-in light theme (black pane).
- **B-DESK-004:** Ctrl/Cmd+L is unproven through a genuine OS input path; the
  command palette command works.
- AppContainer startup is fail-closed. Do not resume a process after Job
  assignment failure and do not silently downgrade to Job Object-only.
- Degraded fallback requires `CRUSOR_ALLOW_JOB_OBJECT_FALLBACK=1`; capability
  reporting must stay truthful.
- Network evidence is TCP loopback only; denial is silent. UDP/DNS/non-loopback
  are not claimed.
- Job memory peak accounting remains a documented limitation; do not claim a
  hard peak-memory bound from `MemoryError` alone.
- **The mutation broker is wired at HEAD.** `src/tools/file_tools.py` routes
  `write_file`/`edit_file` through `WorkspaceMutationBroker`
  (`:508-538`, `:1503-1529`) and `git diff HEAD -- src/tools/file_tools.py` is
  empty. B-001 is fixed at HEAD; do not reintroduce an "uncommitted broker"
  claim or a second write path.
- Identity/RBAC status: see the F-07 bullet below (vacuous wiring; no denial
  path in the live tool call).
- P0.6.9 live acceptance failed; LIVE12 is not revalidated.
- **The test suite is NOT clean (verified 2026-11-12).** `pytest --collect-only`
  reports 4,968 tests with **3 collection errors** (missing
  `deduplicate_streaming_usage`, shadowed `record_turn_receipt`). Known red:
  two `test_bridge.py` tests and
  `test_agent_cards.py::test_all_required_card_types_are_declared`. The
  historical 25-failure full-suite record remains historical. Do not claim a
  clean suite.
- **Engineering binds no tools during generation (F-01).** Phase 2A added
  bounded read-only discovery before planning; generation still regenerates
  whole files and binds no read/search/list/test tools. Requirement-id targets
  are still synthesised when no discovery evidence exists
  (`src/orchestration/contract.py:981-993`). Do not claim targeted editing or
  test-driven repair until Phase 2B/2C.
- **Execution is unsandboxed by default (F-03).** `terminal_tools` inherits
  `os.environ` and only uses `ExecutionBroker` when
  `CRUSOR_SANDBOX_TERMINAL=1`; test execution uses a raw subprocess. The
  canonical graph blocks shell tools today (`_GRAPH_MUTATION_BLOCKED`), so this
  is defense-in-depth, not a current exploit path. Never re-enable shell tools
  without routing them through the broker and a scrubbed env.
- **The product approval default is `workspace_session`, not `ask` (F-04).**
  `src/bridge/__main__.py:1671-1675` auto-grants LOW-risk mutations. The
  Electron acceptance scripts force `ask`, so their dock evidence does not
  describe the shipped default. Treat `ask` as the required behaviour in any
  new acceptance claim.
- **Checkpoint storage is env-resolved and lazily opened (P1-A + R2 + R3,
  F-05 PARTIAL).** `src/runtime/app_paths.py` resolves
  `CRUSORAI_CHECKPOINT_DB` > `CRUSORAI_CHECKPOINT_HOME` > `CRUSORAI_SESSIONS_DB`
  > `CRUSORAI_HOME` > `~/.crusorai/sessions.db`; `chat_graph` opens on first
  use, not import. `conftest.py` pins home/sessions/checkpoint to a temp root.
  R2 routes the bridge `_prior_checkpoint_count` and the OTel test cleanup
  through the same resolved checkpoint DB; both used to read/delete the
  developer's real DB. R3 adds `sqlite_readonly_uri()` (absolute
  `Path.as_uri()` + `mode=ro`) so `#`, `?`, `%`, spaces and Unicode paths are
  encoded and cannot resolve to another database. Invalid checkpoint paths fail
  closed with no home fallback. Do not reintroduce an import-time
  connect/mkdir/setup, a raw `f"file:{path}?mode=ro"` URI, or a hardcoded
  `~/.crusorai` checkpoint consumer. Retention/vacuum and the 937 MB file remain
  open.
- **Turn observability receipts are currently dead (F-06).**
  `src/observability/` (package) shadows `src/observability.py`, so
  `record_turn_receipt` is unavailable and the call site swallows the error.
  Do not cite observability receipts as evidence until this is repaired.
- **Identity/RBAC is wired only vacuously (F-07).** The engineering adapter
  mints a hard-coded superadmin principal (`model_adapter.py:837-851`); it
  cannot deny. Do not claim enforcement.
- **FinOps under-counts post-dispatch cancellation (F-08).** A Stop during
  streaming releases the reservation and records zero usage. Do not present
  "spend" as complete after a cancelled paid turn.
- **Only the bridge sets `canonical_runtime=True` (F-10).** Dashboard/CLI
  `stream_agent` callers do not; they skip engineering delegation and
  mutation-token minting. Do not describe them as the same product path.
- Interactive desktop rendering is verified on this Windows host for the
  provider-free path (r1/r2 screenshots); real tool approval and light-theme
  fidelity remain unproven.
- A historical provider reservation is reported as still `in_flight`; do not
  touch provider/billing state without owner confirmation.
- Phase 2A read-only discovery before planning is implemented and verified;
  see `CRUSOR_PHASE_2A_WORKSPACE_DISCOVERY.md`. The remaining generation
  limitations are covered by the F-01 bullet above.
- Discovery never mutates: it must not be extended with write/delete/exec
  capabilities without a separate security review and Phase 2B design.
- Outside-workspace access is **turn-scoped** (`workspace.access` approval):
  read and create/modify are allowed after a grant, but the mutation still needs
  the normal diff token. Never widen a grant to a parent folder, persist it, or
  let a session policy auto-approve it. Delete/rename/copy outside the workspace
  remain unsupported (B-CORE-007).
- `mock_mode` does not gate the repair dispatch path (B-CORE-006); set
  `max_correction_attempts=0` for offline engine runs.
- Backend qualification runs from the terminal with
  `stream_agent(..., canonical_runtime=True)`; the frontend is not required to
  exercise the backend, and was explicitly out of scope on 2026-11-12.

## 12. Reporting format

End every implementation session with:

```text
Starting HEAD:
Final HEAD:
Branch / origin:
Changed files:
Phase / scope:
Tests (command, result, exit):
CI (workflow, run, job, platform, conclusion):
Dirty entries before / after:
Known limitations added or closed:
Next recommended task:
```

If any field is unknown, write `UNKNOWN` and say why. Do not fill it with a
guess.

## 13. Relationship to other memory tools

- This repository memory is file-based and versioned with the project. It is the
  durable source future sessions must read and update.
- External agent memory services or MCP tools, if configured, are auxiliary.
  Never rely on them as the only record. Never store secrets in them.
- If an external tool conflicts with this repository, the repository wins.


## 14. Execution status (2026-11-12)

T-18 (CI truth gate) is **PARTIAL**: `.github/workflows/agent-core.yml` now enforces the full suite with no
concealment, and red-on-red is proven. Green-on-green is blocked by `test_copilot_parity_permission_diff`
(approval-dock inline-diff contract) and by `test_degraded_memory` hanging. T-07 (receipt emission) has not
started. Do not claim a green full suite or a GitHub-hosted run until both are resolved and a real Actions run
exists.

