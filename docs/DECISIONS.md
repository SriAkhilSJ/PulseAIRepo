# CrusorAI - Architectural Decisions

This is an ADR-style log. Each entry records a decision that constrains current
code. Status values:

- **Accepted** - implemented and observed in the repository.
- **Accepted (derived)** - reconstructed from source and phase evidence; no
  standalone ADR file was found.
- **Proposed** - not implemented; recorded for future work.

Do not rewrite history here. If a decision changes, add a new entry and mark the
old one superseded.

---

## ADR-001 - Build on a pinned Code OSS fork, not a from-scratch editor

**Status:** Accepted
**Date recorded:** 2026-11-08 (decision predates this log)
**Evidence:** `desktop/UPSTREAM_PIN`, `desktop/SELECTIVE_MANIFEST.json`,
`desktop/README.md`, `docs/DESIGN/FORK_REBRANDING.md`

**Context.** The product needs a mature editor, terminal, extension host, and
workbench on day one.

**Decision.** Vendor Code OSS at a pinned commit
(`6c27443ce6fdf6ac798c64025d45175e2e23c4b4`), brand it, and add Crusor as a
workbench contribution. Keep upstream source edits to a named, hash-receipted
set.

**Consequences.**
- Immediate access to editor/terminal/extension infrastructure.
- Large vendored tree (18k tracked files) and an ongoing upstream-sync burden.
- The manifest check (`src/tests/test_desktop_contrib_overlay.py`) must move
  whenever a pinned file changes.
- "Invariant 7" limits upstream source edits; new UI should be additive under
  `contrib/crusorai/`.

---

## ADR-002 - Run the agent as a separate Python process over stdio

**Status:** Accepted
**Evidence:** `src/bridge/__main__.py`, `src/bridge/protocol.py`,
`desktop/.../node/crusorAIWorkerProcessService.ts`

**Context.** The IDE is TypeScript/Electron; the agent stack is Python
(LangGraph, provider SDKs, data tooling). Embedding Python in Electron is
fragile and unsafe.

**Decision.** Spawn a Python worker (`python -m src.bridge`) from an Electron
utility process and speak newline-delimited JSON over stdio, protocol v2.

**Consequences.**
- Clean process isolation, crash containment, and independent testing.
- Protocol versioning and generated TypeScript types become mandatory.
- No runtime schema validator on both ends; drift is caught by tests.
- Desktop and engine can be packaged/updated separately.

---

## ADR-003 - Use LangGraph for the turn lifecycle

**Status:** Accepted
**Evidence:** `src/graphs/chat_graph.py`, `src/graphs/state.py`,
`pyproject.toml` (`langgraph`)

**Context.** Agent turns need explicit planning, tool loops, recovery, budget
limits, and terminal states that can be inspected and replayed.

**Decision.** Model the turn as a LangGraph state machine with named nodes:
task manager, planner, AI, tools, progress, recovery limit, tool-cycle limit,
pivot, plan preview/reviser/cancel, finish gate, finalize.

**Consequences.**
- Deterministic routing and a clear place for gates/checkpoints.
- The graph file is very large; changes require careful regression testing.
- A second orchestrator path exists for engineering tasks, so divergence is a
  standing risk.

---

## ADR-004 - One fixed right-side agent surface

**Status:** Accepted
**Evidence:** `desktop/.../browser/crusorAI.contribution.ts`,
`docs/DESIGN/CRUSORAI_DESIGN_PLAN.md`, `README.md`

**Context.** Multiple chat surfaces and movable panes fragment the experience.

**Decision.** Crusor lives in the Auxiliary Bar, fixed, non-movable, as a single
agent. Copilot remains available but hidden by default without deleting source.

**Consequences.**
- Predictable layout and a single session model.
- New capabilities must fit the panel/dialog/preview patterns rather than add
  panes.
- UI tests pin dock location and visibility.

---

## ADR-005 - Context assembly is a layered, budgeted engine

**Status:** Accepted
**Evidence:** `src/context/engine.py`, `src/context/context_engine.py`,
`src/context/token_budget.py`, `src/context/compaction.py`

**Context.** A coding agent needs repository, task, memory, history, and
verification context without exceeding model windows or cost caps.

**Decision.** Define `ContextEngine` as an ABC and a facade with named layers;
assemble under a shared token budget; compact based on actual provider usage;
preserve a stable prompt prefix where possible.

**Consequences.**
- Context selection is inspectable and testable per layer.
- Compaction can invalidate the prompt cache (known warning).
- Layer additions must respect ordering, dedup, and budget policy.

---

## ADR-006 - Route management calls to a cheap auxiliary model

**Status:** Accepted
**Evidence:** `src/config/settings.py` (`resolve_aux_llm`),
`src/llm/factory.py`

**Context.** Summaries, titling, classification, and memory maintenance should
not bill at flagship rates or share the main request chain.

**Decision.** Default auxiliary provider to `cheap`, with
`CRUSORAI_CHEAP_*` credentials/model and `AUX_LLM_*` overrides. Keep structural
separation from the main conversation.

**Consequences.**
- Lower cost for housekeeping.
- Another credential surface to configure and audit.
- `SUMMARIZER_LLM` remains off by default for budget safety.

---

## ADR-007 - SQLite is the canonical durable store

**Status:** Accepted
**Evidence:** `src/server.py`, `src/agents/financial_store.py`,
`src/bridge/__main__.py` (checkpoint read), `src/runtime/persistence.py`

**Context.** Sessions, checkpoints, and financial records must survive restarts
on a desktop machine without a database server.

**Decision.** Use `~/.crusorai/sessions.db` (SQLite) as the canonical store for
checkpoints and financial reservations; keep workspace-scoped JSON/JSONL
ledgers for audit and portability.

**Consequences.**
- Zero-install local persistence and easy backup.
- Multiple money surfaces require reconciliation; no single transaction spans
  them.
- Persistence redaction is mandatory before writes.

---

## ADR-008 - Fail closed at the security boundary

**Status:** Accepted
**Evidence:** `src/security/contracts.py`,
`src/security/execution_broker.py`, `src/security/sandbox/`,
`src/tests/test_security_containment.py`

**Context.** The agent executes model-chosen commands and file mutations. A
mistake is a real host risk, not a UI bug.

**Decision.** Route execution through a single broker with single-use approval
tokens, workspace jailing, environment allowlists, output caps, and OS sandbox
backends. Fail closed when the platform or policy is unknown. Keep the
AppContainer AST allowlist exact and adversarial-tested.

**Consequences.**
- Stronger containment and auditable receipts.
- Platform-specific code paths and CI matrix complexity.
- A static AST guard is not an OS sandbox; native/direct OS calls remain out of
  reach.

---

## ADR-009 - Completion is derived from verification, not model claims

**Status:** Accepted
**Evidence:** `src/verification/`, `src/graphs/gates.py`,
`src/runtime/status_contract.py`, `README.md` status-contract notes

**Context.** Models regularly claim success after partial work.

**Decision.** Separate runtime outcome, verification status, and specification
status. Require landed mutations and exact-check evidence before clearing
failed-check debt; weaker green commands cannot authorize completion.

**Consequences.**
- More honest completion and better failure diagnosis.
- More state to track and more tests to maintain.

**Audit note 2026-11-12 (F-09).** The rule is weaker than it reads: when
`testing_required` is false (derived from the prompt/plan),
`RequirementVerifier` can mark a requirement `VERIFIED` from file presence and
matched criteria with no executed test (`requirement_verifier.py:225-233`).
SOURCE components should force test evidence or `NOT_VERIFIED`.
- Users may see "failed/incomplete" when the model believes it succeeded,
  which is intentional.

---

## ADR-010 - Multi-platform delivery is evidence-gated

**Status:** Accepted
**Evidence:** `src/targets/`, `src/tools/target_tools.py`,
`docs/MULTI_PLATFORM_TARGETS.md`, `docs/pipelines/`

**Context.** "Build succeeded" is not "the app runs".

**Decision.** Resolve targets from real manifests, run per-target build plans,
and issue a receipt only when deterministic probes pass (window/CDP, device
foreground, screenshot quality, logs, UI assertions). Dry runs are `PLAN`, never
`passed`.

**Consequences.**
- Honest cross-platform claims.
- Host toolchains and devices are required; many environments yield
  `UNAVAILABLE`.
- CI uses general-purpose runners, so device proof is often local-only.

---

## ADR-011 - Phase-gated hardening with written evidence

**Status:** Accepted
**Evidence:** `docs/production/phase-0` through `phase-1`,
root `PHASE_*.md`, Git commit chain from `a6455e25` to `b72d04c5`

**Context.** Earlier work produced false greens and undocumented regressions.

**Decision.** Work in narrow phases with an explicit starting HEAD, scope,
non-actions, tests, CI runs, and a final report. Preserve historical failures.

**Consequences.**
- Traceable changes and reviewable scope.
- Documentation overhead per phase.
- Phase work must not silently absorb unrelated dirty entries.

---

## ADR-012 - Maintain project memory inside the repository

**Status:** Accepted (this task)
**Date:** 2026-11-08
**Evidence:** `AGENTS.md`, `docs/PROJECT_MASTER.md`, `docs/CURRENT_STATE.md`,
`docs/ARCHITECTURE.md`, `docs/DECISIONS.md`,
`docs/BUGS_AND_LIMITATIONS.md`, `docs/ROADMAP.md`,
`docs/phases/PHASE_TRACKER.md`, `docs/handoffs/`

**Context.** Project knowledge was spread across hundreds of root/phase/audit
documents, and future sessions repeatedly re-derived or contradicted it.

**Decision.** Keep a small, always-current memory layer in `docs/` and a root
`AGENTS.md` that requires every session to read it before implementation and
update it after verified work.

**Consequences.**
- Faster, safer onboarding for humans and AI sessions.
- The memory files must be maintained or they become misleading.
- Historical documents remain authoritative evidence; the new files are the
  index and current truth, not a replacement for evidence.

---

## ADR-013 - The AppContainer grant uses an exact structural whitelist

**Status:** Accepted (Phase 1.3.2)
**Date:** 2026-11-09
**Evidence:** `src/tests/test_security_containment.py`,
`docs/production/phase-1/PHASE_1_3_2_AST_BINDING_HARDENING.md`

**Context.** Per-node validation of assignments and calls still missed aliases,
rebinding, destructuring, walrus assignments, loop/with targets, import and
nested-scope shadowing, and attribute monkeypatching.

**Decision.** Require the exact documented signature and the exact eighteen
statements of `_grant_to_object`, validate the module shape and canonical
bindings, reject protected-name bindings in every function/class scope, reject
protected attribute mutation and `setattr`, and validate every API argument,
both `LocalFree` calls, order, branches and return.

**Consequences.**
- Any unexpected statement or binding form fails closed.
- A legitimate policy change requires updating the expected structure, the
  module constants, and the positive control together.
- The guard remains static AST analysis; the OS sandbox is still the runtime
  boundary.

---

## ADR-014 - Structure layouts and module initialization are exact

**Status:** Accepted (Phase 1.3.3)
**Date:** 2026-11-09
**Evidence:** `src/tests/test_security_containment.py`,
`docs/production/phase-1/PHASE_1_3_3_MODULE_STRUCTURE.md`

**Context.** Header-only class validation and loose DLL initialization checks
left class-body execution, layout tampering and arbitrary module expressions
outside the allowlist.

**Decision.** Record the exact ordered `_fields_` layout of every sandbox
`ctypes.Structure`, require structure classes to contain only that assignment,
allow only `WindowsSandboxManager` as a non-structure module class (docstring
and methods only), and require the exact
`ctypes.WinDLL(...) if sys.platform == "win32" else None` initialization with
`use_last_error=True` and no extra arguments.

**Consequences.**
- Class bodies and module initialization fail closed on any unexpected change.
- Legitimate layout changes require an audited update to the expected map and
  the positive control.
- The guard remains static AST analysis; the OS sandbox is the runtime boundary.

---

## ADR-015 - Module declaration surface is pinned

**Status:** Accepted (Phase 1.3.4)
**Date:** 2026-11-09
**Evidence:** `src/tests/test_security_containment.py`,
`docs/production/phase-1/PHASE_1_3_4_MODULE_DECLARATION_HARDENING.md`

**Context.** Validation of the grant function, structures and DLL loads still
left imports, module-level declarations, the helper signature and manager
methods unconstrained.

**Decision.** Pin an exact 16-entry import manifest, a 62-entry ordered module
declaration manifest (docstring, imports, WinDLL carriers, constants,
structures, state flag, helper, manager), the exact helper signature, the exact
thirteen-method manager manifest, and require all eleven structures to be
present exactly once.

**Consequences.**
- Additional imports, functions, classes, methods or declarations fail closed.
- The manifests duplicate the real module surface; legitimate changes require
  an audited update and a fresh positive control.
- Method bodies remain outside this declaration check; only their signatures and
  decorators are pinned.

---

## ADR-016 - The ACL grant is owned by the validated helper

**Status:** Accepted (Phase 1.3.4R)
**Date:** 2026-11-09
**Evidence:** `src/tests/test_security_containment.py`,
`docs/production/phase-1/PHASE_1_3_4_MODULE_DECLARATION_HARDENING.md` section 13

**Context.** Phase 1.3.4 pinned the helper signature but not its body, and the
grant function was discovered by a whole-tree search. Additional helper
statements or a relocated grant could still be accepted.

**Decision.** Pin the helper's exact eleven-statement body and require exactly
one `_grant_to_object`, as a direct child of
`_ensure_windowstation_desktop_access`. Relocation into manager methods, other
functions, nested scopes, or duplication fails closed.

**Consequences.**
- The helper's early returns, dependency guard, handle acquisition, grant calls,
  state update and return are all structural.
- Any legitimate helper change requires an audited update and a fresh positive
  control.
- Manager method bodies remain outside this narrow declaration check.

---

## ADR-017 - Grant declaration uniqueness counts async functions

**Status:** Accepted (Phase 1.3.4R2)
**Date:** 2026-11-09
**Evidence:** `src/tests/test_security_containment.py`,
`docs/production/phase-1/PHASE_1_3_4_MODULE_DECLARATION_HARDENING.md` section 14

**Context.** The grant uniqueness search counted only `ast.FunctionDef`, so an
additional asynchronous `_grant_to_object` in another scope was invisible.

**Decision.** Count both `ast.FunctionDef` and `ast.AsyncFunctionDef` in the
whole-tree search, require exactly one declaration named `_grant_to_object`, and
require that declaration to be synchronous, helper-owned, and valid under the
existing signature and body checks.

**Consequences.**
- Async duplicates or relocations fail closed.
- The sole grant remains the documented synchronous function.
- Manager method bodies remain outside this narrow declaration check.

---

## ADR-018 - Runtime qualification is separate from static validation

**Status:** Accepted (Phase 1.4)
**Date:** 2026-11-09
**Evidence:** `docs/production/phase-1/PHASE_1_4_WINDOWS_RUNTIME_QUALIFICATION.md`,
`src/tests/test_windows_sandbox_runtime.py`

**Context.** Static AST checks and mocks cannot prove that Windows enforces the
intended sandbox boundary.

**Decision.** Keep a Windows-only runtime harness that observes the real
AppContainer token, Job Object limits, DACL denial, environment sanitization,
termination and cleanup. AppContainer tests are opt-in and monkeypatch the
WindowStation/Desktop ACL helper to a no-op so no machine ACL is changed. Record
unexecuted coverage as NOT RUN rather than mocking a PASS.

**Consequences.**
- Runtime evidence is separated from static guarantees.
- The production ACL-grant branch and network denial remain explicitly
  unproven until a safe elevated/isolated environment exists.
- A confirmed output-cap defect was fixed with a runtime regression test.

---

## ADR-019 - Windows AppContainer never rewrites machine ACLs

**Status:** Accepted (Phase 1.4 final)
**Date:** 2026-11-09
**Evidence:** `docs/production/phase-1/PHASE_1_4_WINDOWS_RUNTIME_QUALIFICATION.md`

**Context.** The production initializer called
`_ensure_windowstation_desktop_access()`, which added ALL APPLICATION PACKAGES
to the current WindowStation/Desktop DACL. That is a machine-level security
change and was not safely qualifiable on this host.

**Decision.** Remove the automatic call. AppContainer launch uses the
environment's existing WindowStation/Desktop permissions; if they are
insufficient, process creation fails closed. The helper remains for explicit,
audited operator provisioning only.

**Consequences.**
- No silent machine ACL modification by the agent runtime.
- Hosts requiring the grant must provision it out of band; otherwise
  AppContainer execution is unavailable.
- Runtime tests replace the helper with a raise-if-called sentinel and pass.

---

## ADR-020 - AppContainer startup fails closed and never silently downgrades

**Status:** Accepted (Phase 1.4 fail-closed correction)
**Date:** 2026-11-09
**Evidence:** `docs/production/phase-1/PHASE_1_4_WINDOWS_RUNTIME_QUALIFICATION.md`
section 16

**Context.** Process creation ignored several security-critical return values,
and AppContainer provisioning failure silently fell back to Job Object-only
execution. Capability reporting also claimed network/low-integrity protections
that the fallback did not provide.

**Decision.** Check attribute-list setup, security-capability/handle-list
updates, Job assignment and resume; never resume after assignment failure; fail
initialization on AppContainer provisioning failure by default. Job Object-only
degradation requires `CRUSOR_ALLOW_JOB_OBJECT_FALLBACK=1`, and capabilities
report the actual backend.

**Consequences.**
- No process executes before AppContainer attributes and Job containment are
  established.
- No silent reduction in isolation.
- Degraded operators see accurate false capability flags.
- Failure-injection tests cover every path without destructive machine changes.

---

## ADR-021 - Renderer architecture pins assert behaviour, not refactor spelling

**Status:** Accepted (Phase 2 r2)

**Context.** Three `test_desktop_renderer_architecture.py` pins froze exact
source strings (`host.submitPrompt(value)`, `this.send({ type: 'prompt'`, the
subagent ternary). The implementation had been refactored to equivalent shapes
(context chips, a typed payload, an early `taskToolCard` return), so the pins
failed while the behaviour was correct.

**Decision.** Assert the contract: prompt submission may carry
`model.contextChips`; the prompt frame is a typed `CrusorClientMethod` with
`type:'prompt'` and `mode:this.mode` followed by `this.send(payload)`; the
subagent family returns through `taskToolCard()` before generic args chips are
built. The real defect (four raw font sizes) stays a hard assertion and now has
its own selector-level regression.

**Consequences.** The suite verifies behaviour without freezing harmless
refactors; a genuinely missing behaviour still fails.

---

## ADR-022 - Cancellation during turn startup is a bounded pending slot

**Status:** Accepted (Phase 2 r2)

**Context.** A Stop sent ~0.9 s after Send returned `accepted=False` because the
turn had been accepted but `turn_controls.begin()` had not run; the prompt still
completed (r1 runtime evidence).

**Decision.** `TurnControlRegistry` keeps one pending slot per session
(`mark_pending` before warm-up/dispatch). `cancel()` on an inactive session
accepts the Stop only while that slot is live (`PENDING_CANCEL_TTL_S = 120 s`);
`begin()` consumes it into `cancel_event`; `_run_turn` emits one cancelled
terminal before any model/echo work. `end()` clears both. A late or expired Stop
is rejected and cannot poison the next turn.

**Consequences.** Startup Stops are honoured without an unbounded queue and
without weakening session identity; the branch is deterministic under
`CRUSORAI_TURN_STARTUP_BARRIER_MS` (bounded test seam).

---

## ADR-023 - Cancelled-before-execution receipts are complete, not degraded

**Status:** Accepted (Phase 2 r2 follow-up)

**Context.** Every cancelled turn painted "Agent Core evidence capture is
degraded. Missing: trace, report." A turn cancelled before any model/tool work
has no trace or report by construction; the warning misdescribed a clean Stop.

**Decision.** When the turn is cancelled, no trace/report exists, no tool
receipts exist, and the reason is a cancellation/echo-seam reason, the coverage
records `not_applicable: [trace, report]` and the receipt is `persisted`.
Executed turns keep the strict missing-artifact check.

**Consequences.** The UI no longer cries wolf on a clean Stop; real monitoring
gaps on executed turns still degrade the receipt.

---

## ADR-024 - The default orchestrator asks the shared ApprovalQueue

**Status:** Accepted (Phase 3.1)

**Context.** Stage 9 of `EngineeringExecutionOrchestrator` called
`grant_approval(..., "APPROVE")` itself, so the default desktop path never
asked a human; the bridge's `safety_reply` resolved a queue the orchestrator
never used.

**Decision.** A new `OrchestratorApprovalGateway` publishes
`tool.approval.request` to the existing `ApprovalQueue`/`event_bus`, waits for
the bridge's `safety_reply` (waking on turn cancellation), validates session and
request, and issues an `APPV-` token bound to task/workspace/path/operation.
The token travels through `model_adapter` to the mutation broker, which verifies
and consumes it. `ask` gates every mutation; session policies auto-allow only
low-risk in-workspace operations; high risk always asks. Headless callers
without `approval_channel` keep the historical supervision path.

**Consequences.** Denial, timeout, cancellation, wrong-session, stale/duplicate
replies and resource mismatches cannot authorize a mutation. Approvals are
requested before code generation, so the dock carries resource/operation but no
file diff body (follow-up).

---

## ADR-025 - Role-correct synthesis for non-source requirements

**Status:** Accepted (Phase 3.2)

**Context.** Product requests beginning with “build” were classified as BUILD
file requirements, and CONFIG/DOC/BUILD requirements with no matching file were
attached to a source (or left unassigned), which rejected the plan. Separately,
the extractor did not treat fix/refactor/clean requests as explicit
requirements, so verification had no requirement evidence.

**Decision.** `requirement_intent` matches build-system nouns only. Necessary
CONFIG/DOC/BUILD requirements receive deterministic role-appropriate targets
(`config/<req>.yaml`, `docs/<req>.md`, `build/<req>.py`) and `detect_file_role`
recognises those directories. The extractor recognises repair/refactor/cleanup
verbs and keeps requests ≥6 characters. Contract validation, coalescing,
optional-suggestion exclusion and dispatch budgets are unchanged.

**Consequences.** Normal product/repair requests produce a valid requirement →
file → work-unit plan with the user's files authoritative; ambiguous
descriptions and conflicting symbols still block; SOURCE/TEST are never
synthesized when the user named a file.

---

## ADR-026 - LangGraph is the one interactive owner; engineering is delegated

**Status:** Accepted and implemented (Agent Runtime Increment 1)

**Context.** Two top-level owners existed: the bridge could run
`EngineeringExecutionOrchestrator` directly or `stream_agent`. That split the
transcript/checkpoint, approval and mutation surfaces.

**Decision.** `stream_agent` is the only interactive turn lifecycle. The graph
classifies chat vs engineering and delegates engineering work through
`engineering_task_node` using `EngineeringTaskRequest → DeliveryContract`.
The orchestrator keeps contract/plan/impact/implementation/verification/repair.
The bridge no longer selects a competing owner; the direct branch was removed
in Increment 3.

**Consequences.** One transcript, checkpoint, cancellation and completion
surface. Engineering work is a graph node, not a second lifecycle. Chat stays
conversational. No environment flag can reactivate the old top-level route.

**Update 2026-11-12 (audit F-10).** Verified at HEAD for the desktop bridge.
Dashboard (`src/dashboard_server.py:162-171`) and CLI (`src/main.py:241-246`)
still call `stream_agent` without `canonical_runtime=True`; they skip
engineering delegation and digest-bound mutation authorization. "One owner" is
true for the desktop, not yet for every entry point.

---

## ADR-027 - One receipt, one model gateway, digest+precondition approvals

**Status:** Accepted and implemented (Agent Runtime Increments 2–3)

**Context.** Context was assembled twice, graph/engineering provider calls were
separate, graph tools bypassed the broker, approvals were path-only and could
be applied to changed bytes/state, and completion/FinOps were reconstructed
from disconnected events.

**Decision.**
1. `ContextEngine.build_engineering_context()` assembles one bounded structured
   bundle; the engine never retrieves its own context.
2. `src/llm/gateway.py` wraps the existing `get_llm`/`RetryLLMProxy` and attaches
   session/turn/task/invocation ids; retry/timeout/cancellation ownership does
   not move.
3. Every supported workspace mutation goes through `WorkspaceMutationBroker`.
   Approval tokens bind task, session, turn, workspace, path, operation,
   proposed-content digest, workspace pre-image, expiry and single use. The
   broker recomputes digest + pre-image before applying.
4. `src/runtime/turn_receipt.py` builds one terminal receipt persisted in the
   LangGraph checkpoint and emitted on `turn_done`.
5. One FinOps invocation ledger per workspace (`.crusorai/finops/
   provider_invocations.jsonl`) records attempts, tokens, latency, known/unknown
   cost and correlation ids, with invocation/task/session/daily reports.
6. Unsupported/opaque tools fail closed; shell execution remains disabled until
   an equivalent sandbox/mutation-capture exists.

**Consequences.** Graph `write_file`/`edit_file` are broker-mediated; denied,
cancelled, stale or replayed approvals do not mutate. One terminal status
(`COMPLETED|FAILED|CANCELLED|DENIED|PARTIAL|NOT_VERIFIED`) is authoritative.
Live provider cost and Electron interactive E2E remain unproven.

---

## ADR-028 - Desktop workbench registers chat routing; panel hash is emitted

**Status:** Accepted and implemented (desktop integration repair, 2026-11-10)

**Context.** The workbench chat contribution injected
`IChatSessionRoutingProviderService`, but the real singleton was side-effect
imported only by the separate sessions app entry, so the Agent pane failed with
`depends on UNKNOWN service chatSessionRoutingProviderService`. Compiling the
workbench also did not update the shipped panel hash consumed by the bridge.

**Decision.** The always-loaded workbench chat contribution imports the real
`sessionRouter/chatSessionRoutingProviderService.js`. After any TypeScript
compile, `node scripts/emit-crusorai-bundle.mjs` regenerates the shipped
`SOURCES_HASH`/manifest and DI bundle before the app is relaunched. Electron
acceptance uses CDP on port **9222** and the real command palette / dock.

**Consequences.** The Agent pane opens and can submit chat/engineering prompts,
show the diff dock, apply broker-mediated writes and display denial/cancellation
receipts. Full `TurnReceipt` field rendering and live-provider qualification
remain open.

---

## Proposed decisions (not implemented)

| ID | Proposal | Why it matters |
|---|---|---|
| P-001 | Wire `IdentityAwareToolAuthorizer` into the live tool path | RBAC exists but is not enforced. |
| P-002 | Add bridge events for architecture/impact/regression/verification artifacts | Desktop cannot render them today. |
| P-003 | Replace `platform.system()` with `os.name == "nt"` in `src/runtime/windows_shell.py` | Removes an import-time process spawn on CPython <= 3.12 and allows 3.11 CI. |
| P-004 | Commit or discard the working-tree mutation-broker wiring | HEAD still bypasses the broker for interactive file tools. |
| P-005 | Unify financial persistence or document the reconciliation contract | Multiple stores can disagree after a crash. |
| P-006 | Re-run and record a full-suite baseline on current HEAD | Historical 25 failures are unresolved. |
| P-007 | Outside-workspace access with a turn-scoped human grant | **Implemented for reads 2026-11-12** (`D-2026-11-12-03`). Writes outside the workspace remain refused (2D-2). |

Note (2026-11-10): P-004 and P-005 are addressed in the uncommitted working tree
by ADR-027 (broker-mediated writes, one invocation ledger with reservation ids
preserved). They remain uncommitted. P-006 is still open.

## D-2026-11-10-01 — App data vs user workspace

Canonical desktop turns bind a per-workspace application-data root
(`~/.crusorai/workspaces/<hash>`); explicit `CRUSORAI_APP_DATA_ROOT` overrides it
for tests/packaging. Legacy direct callers keep `<workspace>/.crusorai` for
migration compatibility. Internal runtime metadata must never be treated as a
user deliverable.

## D-2026-11-10-02 — Typed agent cards over a parallel event system

Agent cards are a presentation projection of canonical bridge events, not a
second execution stream. The wire carries versioned, schema-validated data; the
renderer re-validates and paints text only. Unknown card types remain visible as
an unsupported indicator and can never crash the pane or execute markup.

## D-2026-11-11-01 — Engineering progress rides the existing card pipeline

**Status:** Accepted and implemented (uncommitted, provider-free Electron verified)

**Context.** `EngineeringExecutionOrchestrator.emit_progress` produced safe
`DesktopVisibilityReporter` snapshots, but `engineering_task_node` called
`run_task_request` without `on_progress`, so the UI saw only a final summary and
the terminal receipt.

**Decision.** A bounded `EngineeringProgressReporter` is the callback. Each
snapshot becomes an existing `agent.card` activity card (`<turn>:activity`) and
an existing `plan.created` plan card (`<turn>:plan`). Stages never impersonate
tool/file/test/verification/cost events; those stay with their authoritative
sources. The bridge journals producer-built `agent_card` frames so progress
survives reload. No second event system, card schema or renderer.

**Consequences.** Live stage and plan updates stream through the existing
bridge/renderer; plan cards replay. Progress is capped at 240 emissions per turn
and suppressed after Stop except for one final settled snapshot.

## D-2026-11-11-02 — Six-state plan outcomes; blocked and cancelled are not failed

**Status:** Accepted and implemented (uncommitted, provider-free Electron verified)

**Context.** The plan contract had `pending | in_progress | completed | failed`.
The scheduler can genuinely cancel, and a halted pipeline leaves work that never
ran; collapsing both into `failed` (or leaving them `pending`) misreports
execution.

**Decision.** Keep the four existing states and add exactly two:
`blocked` (dependency/upstream halt; never attempted) and `cancelled` (Stop
before, during, or while awaiting approval). `record_task_outcome` is the single
settlement point. The existing `CrusorAIPlanStepView` union, `PLAN_STATUSES`,
strip glyphs, card marks and CSS gain the two states; no new schema version.

**Consequences.** Old four-status cards remain valid; unknown statuses on older
clients still fall back to `pending`. The scheduler has no intentional-skip
outcome, so `SKIPPED` maps to `blocked` rather than `failed`. Node completion
remains a work-unit fact, separate from the final task verdict.

## D-2026-11-11-03 — Per-turn orchestration storage

**Status:** Accepted and implemented (uncommitted)

**Context.** The graph passed one shared
`app_data_root(workspace)/orchestration` directory to every engineering turn.
`TaskStateMachine`, `AdaptiveContextManager` and the journal key off the provided
directory, so the second engineering turn loaded the first turn's terminal
state and raised `cannot move from COMPLETED to UNDERSTANDING` (shown to the
owner as "Engineering execution failed: Invalid state transition…"). Completed
steps could also leak into the next plan.

**Decision.** Storage is scoped per turn:
`app_data_root(workspace)/orchestration/<task_id>`.

**Consequences.** State, authoritative context and journal are isolated per
turn; multi-turn engineering sessions work. Existing per-task defaults outside
the graph are unchanged.

## D-2026-11-11-04 — Cards belong to exactly one turn

**Status:** Accepted and implemented (uncommitted, provider-free Electron verified)

**Context.** The renderer kept one global card map keyed by card id; journal
hydration loaded every card for the session into it and history turns never
received cards. After multiple turns and a reload, all cards shared one bottom
stack. The bridge also deduplicated by card id alone and returned messages
without turn identity.

**Decision.** Card state is a `CrusorCardStore` keyed by `(turnId, cardId)` per
surface/session. The bridge stamps each historical message with the turn whose
prompt produced it using the journal's `turn.started.request.sha256`; cards are
deduplicated by `(session, turn, card id)`; hydration attaches only
`cardsFor(turn.turnId)` to each history turn, and the existing renderer paints
them at the end of that turn. Surface reset/snapshot include the store and
`currentTurnId`.

**Consequences.** Turns cannot overwrite one another, identical card ids across
turns are independent, session switching clears cards, replay cannot duplicate,
and reload/restart restores each turn's own cards. Legacy journals without
request hashes use ordinal association only when counts align; ambiguous cards
stay unassigned and are warned, never merged into the newest turn.

## D-2026-11-11-05 — User-facing cards are a filtered, chronological timeline

**Status:** Accepted and implemented (uncommitted, provider-free Electron verified)

**Context.** The conversation rendered every typed card in one stack after the
timeline, including internal verification, delivery and cost cards. That mixed
execution/accounting records into the developer conversation and put the final
assistant answer above the work it described.

**Decision.** One rendering policy:
`verification | delivery | cost` are internal-only and never paint a dedicated
card; they remain in the model, journal, receipts and FinOps records. Visible
cards are pinned into the turn timeline (`CrusorAITurnPart` card parts): live at
event arrival, late receipt cards before the final answer, historical cards by
stored order with the plan early and other cards before the final answer. Typed
tool cards are suppressed when the existing tool row already renders the call.

**Consequences.** The transcript reads plan → work/tools → file/approval → final
answer, with no internal accounting cards. Verification, delivery and cost are
still recorded and can be surfaced later for audit/debug; the existing plan
strip, approval dock, tool rows and test cards remain unchanged.

## D-2026-11-12-01 — Engineering is generation+verify until tools are bound

**Status:** Accepted (current behaviour, qualified against a real provider)

**Context.** The real-provider terminal qualification (5 settled calls,
₹0.1815) failed all three engineering tasks: the plans targeted
requirement-ID-named files (`src/req_001_module.py`, `src/req_003_module.py`,
`tests/test_req_001_module.py`) instead of the existing `mini_math` package, a
single malformed code fence aborted Test A with no recovery, and Test C never
executed the failing tests. `rg` over `orchestrator.py` and `model_adapter.py`
finds no `bind_tools`, no tool registry use and no tool loop; the chat path does
bind tools (`chat_graph.py:2322,2675,2786`).

**Decision.** Treat `EngineeringExecutionOrchestrator` as a metered
generation + independent-verification engine, not an agent, until Phase 2 lands.
No report may describe it as inspecting, searching, running or repairing code.
Phase 2 is scoped to: bind bounded read-only tools (list/read/search) before
planning; feed discovered files into `_requested_files`/planner so targets are
real paths; add one bounded format-recovery re-prompt on
`SourceExtractionError` (metered as its own invocation); close the
test-diagnose-repair loop on existing verification evidence. LangGraph stays the
canonical lifecycle owner and all mutations stay on the broker.

**Consequences.** Until Phase 2, engineering outcomes are honest but weak
(`FAILED`/`BLOCKED` with no file changes), and the deficiency is recorded rather
than hidden. Paid qualification runs from the terminal via
`stream_agent(..., canonical_runtime=True)` — same graph, orchestrator and
gateway as the desktop bridge — so the frontend is not required to exercise the
backend.

## D-2026-11-12-02 — Engineering plans only against discovered files

**Status:** Accepted and implemented (uncommitted, Phase 2A)

**Context.** The real-provider terminal run failed all three engineering tasks
because the planner guessed targets. `extract_contract` synthesised
`src/<requirement_id>_module.py` whenever a requirement did not name a file, so
the engine wrote `src/req_001_module.py` instead of editing `mini_math`.

**Decision.** The engineering lifecycle inspects the workspace before planning,
using exactly three read-only capabilities (`workspace.list_files`,
`workspace.read_file`, `workspace.search`). They are bounded
(depth/entries/bytes/lines/results/time), reuse the existing ignore set, and
delegate containment to `PathSafetyValidator`. Discovery produces a ranked,
bounded `WorkspaceEvidence`; the contract resolves
explicit → requested → discovered → synthesis, where synthesis is named from
the request and never from a requirement id. Ambiguity is reported and blocks
the plan pre-dispatch. `validate_contract_plan` rejects requirement-id targets
whenever evidence exists. Discovery runs inside the existing
`PROJECT_DISCOVERY` stage, before `CONTRACT_EXTRACTION`, and is journalled with
per-call identity. LangGraph and `EngineeringExecutionOrchestrator` remain the
only lifecycle owners; the model gateway, mutation broker, approval gateway,
journal, checkpoints, TurnReceipt and FinOps are unchanged.

**Consequences.** Plans reference real files (`src/mini_math/ops.py`,
`tests/test_ops.py`, `README.md`) and generation receives the existing file plus
bounded neighbour evidence. Discovery is lexical, not semantic: when it cannot
choose confidently it blocks rather than fabricates. It does not enable
targeted edits or repair — those remain Phase 2B/2C. Discovery failures are
fail-soft and journalled, falling back to request-only targeting.

**Correction 2026-11-12 (audit F-01).** The guarantee is conditional, not
global. `src/orchestration/contract.py:981-993` still falls back to
`src/{requirement_id}_module.py` when no discovery evidence and no synthesis key
exist, and `src/tests/test_contract_assignment_reliability.py:66-70` asserts
that fallback. Read this decision as "never use a requirement id when evidence
exists"; Phase 2B must make the rejection unconditional.

## D-2026-11-12-03 — Outside-workspace reads only with a turn-scoped human grant

**Status:** Accepted and implemented (uncommitted, Phase 2D read grants)

**Context.** Phase 2A correctly refuses every path outside the session
workspace, but a human who explicitly points at a neighbouring folder got a
hard error with no way to allow it. Other coding agents ask (OpenCode's
`external_directory` action with allow-once/allow-always/reject; Claude Code's
separate read/write outside-workspace controls).

**Decision.** A path outside the workspace may be **read** only after one
explicit approval for that exact canonical boundary, through the existing
session approval queue and `tool.approval.request` event. Grants are
turn-scoped (`once` or `turn`), never persisted, never recursive to a parent,
never implied by a session policy, and never cover sensitive names (`.ssh`,
`.env*`, key stores). `read` grants never authorise writes. Traversal, UNC,
drive-relative forms and symlink escapes remain hard rejections and never
become prompts. External files are **context only**: they are attached to the
plan node as read-only evidence, and any outside write target is rejected
before dispatch.

**Consequences.** A user can say "read ../shared/utils.py and use it here" and
approve exactly that path; the agent then reads it and edits only workspace
files. A request to **edit** an outside file asks for a ``write`` grant for that
exact boundary; after approval the mutation still needs the normal diff-bound
token, and the broker refuses an outside write without one. Delete/rename/copy
outside the workspace remain unsupported. The approval card reuses the existing
dock; the frontend was not changed, so its wording is generic.

## D-2026-11-12-04 — The 2026-11-12 audit is the condition baseline for memory

**Status:** Accepted (documentation; no runtime change)

**Context.** Repository memory had drifted from HEAD. It claimed a working-tree
count of 175/195/211/247, a broker that bypassed at HEAD, an active B-DESK-001
blocker, competing bridge owners, 334 test modules, a broker that was the only
process chokepoint, an `ask` approval default, and an impossible
requirement-id filename synthesis. Each was checked against `fb5bd528` plus the
working tree and found wrong or conditional.

**Decision.** `docs/AUDIT_2026-11-12_ENGINEERING_AUDIT.md` is the canonical,
append-only findings register (F-01…F-15) for this snapshot. Future sessions
cite it instead of reconstructing state from narrative reports. A finding is
closed by changing its status and adding a command/result/exit-code receipt; it
is never deleted. If code and memory disagree, code wins and the disagreement
is itself recorded.

**Consequences.** `AGENTS.md`, `CURRENT_STATE.md`, `ARCHITECTURE.md`,
`BUGS_AND_LIMITATIONS.md`, `ROADMAP.md`, `PHASE_TRACKER.md` and
`LATEST_HANDOFF.md` point at the register. Historical phase evidence under
`docs/production/` is untouched. Production readiness is still not claimed.

## D-2026-11-12-05 — Checkpoint storage is env-resolved and lazily opened

**Status:** Accepted and implemented (P1-A 2026-11-12; extended by P1-A-R2 and
P1-A-R3 2026-11-12)

**Context.** `src/graphs/chat_graph.py` hardcoded
`~/.crusorai/sessions.db`, created the directory and opened the connection at
import, and ignored `CRUSORAI_HOME`/`CRUSORAI_SESSIONS_DB`/
`CRUSORAI_CHECKPOINT_HOME`. Test runs therefore wrote the developer's real
session DB; the P1 investigation measured ~0.99 MB growth.

**Decision.** `src/runtime/app_paths.py` owns the path contract:
`session_db_path()` preserves the existing sessions precedence and
`checkpoint_db_path()` resolves `CRUSORAI_CHECKPOINT_DB` >
`CRUSORAI_CHECKPOINT_HOME` > `CRUSORAI_SESSIONS_DB`/`_PATH` >
`CRUSORAI_HOME` > `~/.crusorai/sessions.db`. The graph wraps `SqliteSaver` in a
lazy connection proxy; import performs no mkdir/open/setup. The first
checkpoint operation creates the configured DB and applies WAL/busy_timeout/
synchronous. `conftest.py` pins `CRUSORAI_HOME`, `CRUSORAI_SESSIONS_DB` and
`CRUSORAI_CHECKPOINT_HOME` to a per-run temp root. `workspace_app_data_root()`
also honours `CRUSORAI_HOME`, so per-workspace orchestration/test-report data
stays under the test home while keeping its workspace subtree.

**Consequences.** Defaults and production persistence are unchanged; tests
still exercise real checkpoints, `SqliteSaver` tables and cross-process replay,
but only in throwaway storage. A checkpoint-specific override intentionally
outranks the shared sessions DB, so an operator who sets both gets separate
files. Retention/vacuum and workspace-specific placement are not part of this
decision (F-05 remains PARTIAL).

**R2 extension (2026-11-12).** Every checkpoint *consumer* must use the same
resolved path, not just the graph:

- `src/bridge/__main__.py::_prior_checkpoint_count` defaults to the graph's
  captured `_CHECKPOINT_DB` when that module is already imported, otherwise
  `checkpoint_db_path()`; an explicit `db_path` is only a caller override.
  `session_create` therefore reports `prior_checkpoints` from the configured
  checkpoint DB and never silently reads `~/.crusorai/sessions.db`.
- `src/tests/test_otel_tracing.py::_drop_checkpoints` resolves
  `chat_graph._CHECKPOINT_DB`, refuses the real home path, and prefers
  `SqliteSaver.delete_thread()` on the graph's own saver. Direct SQL is a
  fallback against the isolated file only.
- Invalid checkpoint paths fail closed with no fallback: an existing directory
  target raises `sqlite3.OperationalError`; a regular file used as a parent
  raises `FileExistsError`/`NotADirectoryError`; a missing nested parent is
  created lazily. The error contract is covered by
  `src/tests/test_checkpoint_isolation.py`.
- The bridge path ownership is regression-tested by
  `src/tests/test_prior_checkpoint_isolation.py` (custom checkpoint DB wins
  over custom session DB; missing override reports zero; real DB + sidecars
  unchanged).

**Consequence of R2.** A deployment that configures a custom checkpoint DB now
also gets its `prior_checkpoints` count from that DB. A missing override is
honestly zero/unknown rather than a cross-database read. No new fallback path
was introduced.

**R3 extension (2026-11-12).** The bridge count must not interpolate a
filesystem path into a SQLite URI. `src/runtime/app_paths.py` now provides
`sqlite_readonly_uri(db_path)`:
`Path(db_path).resolve().as_uri() + "?mode=ro"`. This preserves absolute path
resolution, Windows/POSIX path handling, read-only mode and the caller's timeout,
while percent-encoding `#` (fragment), `?` (query), `%` (escape), spaces and
Unicode. `_prior_checkpoint_count` uses it. A path such as
`cp#frag/sessions.db` can no longer be truncated to `cp` and silently count a
decoy database.

**Consequence of R3.** Special-character checkpoint paths are safe; the count
remains read-only (writes raise `sqlite3.OperationalError`) and no home fallback
exists. `src/tests/test_checkpoint_uri_isolation.py` covers `#`, spaces, `%`,
Unicode and URI-level `?`; the end-to-end `?` file case runs on POSIX and is
skipped on Windows, which forbids `?` in filenames.
